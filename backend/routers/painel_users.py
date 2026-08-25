"""Painel.fun proxy endpoints with SQLite cache.

Because painel.fun requires solving a Cloudflare Turnstile via 2Captcha
on every fresh login (which takes 20-60 seconds), we cache the users list
in SQLite and refresh it in the background. The `GET /api/painel/users`
endpoint returns the cached list immediately.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from database import DB_PATH
from services import painel
from services.phone_extractor import extract_whatsapp
from services.system_detector import detect_system_type
from services.expiration import compute_expiration_info

router = APIRouter(prefix="/api/painel", tags=["painel"])
logger = logging.getLogger(__name__)

_refresh_lock = asyncio.Lock()
_refresh_state = {"running": False, "last_error": None, "last_refresh_at": None}


class RenewPayload(BaseModel):
    user_id: str
    system_type: str  # iptv | p2p | hybrid
    plan_months: int  # 1 | 3 | 6 | 12


async def _read_cache() -> tuple[list[dict], Optional[str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT data, updated_at FROM painel_users_cache WHERE id = 'all'")
        row = await cur.fetchone()
        if not row:
            return [], None
        return json.loads(row["data"]), row["updated_at"]


async def _write_cache(users: list[dict]):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO painel_users_cache (id, data, updated_at) VALUES ('all', ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (json.dumps(users), now),
        )
        await db.commit()


def _user_key(u: dict) -> Optional[str]:
    """Stable identity for a painel user record (used to dedupe on upsert)."""
    for k in ("id", "user_id", "username"):
        v = u.get(k)
        if v is not None and str(v).strip():
            return str(v)
    return None


async def upsert_users_in_cache(new_users: list[dict]) -> int:
    """Add or update the given users in the local cache WITHOUT wiping existing ones.

    This is called right after trial creation so `/pay/{id}` and `/customers`
    show the newly-created trial immediately — no waiting for a full painel
    refresh (which can take 30–90 seconds because of Turnstile solve).

    Every user injected here is tagged with `_pending_from_trial=True` so
    the next full refresh (which does a REPLACE from painel) knows to
    preserve it if painel hasn't reflected the trial yet.
    """
    if not new_users:
        return 0
    existing, _ = await _read_cache()
    by_key: dict = {}
    for u in existing:
        k = _user_key(u)
        if k:
            by_key[k] = u
    added = 0
    for u in new_users:
        k = _user_key(u)
        if not k:
            continue
        # Mark as pending-from-trial so refresh_cache_task can preserve it
        # until painel catches up.
        marked = {**u, "_pending_from_trial": True}
        if k in by_key:
            # Merge: new fields overwrite old ones, but keep old fields we don't get
            by_key[k] = {**by_key[k], **marked}
        else:
            by_key[k] = marked
            added += 1
    await _write_cache(list(by_key.values()))
    return added


async def refresh_cache_task():
    if _refresh_state["running"]:
        return
    async with _refresh_lock:
        _refresh_state["running"] = True
        _refresh_state["last_error"] = None
        try:
            logger.info("Refreshing painel.fun users cache...")
            users = await painel.list_users(limit=10000)
            # REPLACE strategy: painel.fun is the source of truth. If it
            # returned a real (non-empty) user list, we mirror it EXACTLY —
            # this purges users that were deleted on painel so the Clientes
            # page never shows ghost/stale users.
            #
            # If painel returned empty (transient error, throttling, WAF
            # block etc.) we skip the write entirely so active pay links
            # stay valid.
            if users:
                # Preserve any locally-injected trials that painel hasn't
                # reflected yet (upsert_users_in_cache in trials.py adds
                # a `_pending_from_trial` marker on injected rows).
                existing_cache, _ = await _read_cache()
                painel_keys = {_user_key(u) for u in users if _user_key(u)}
                pending_trials = [
                    u for u in existing_cache
                    if u.get("_pending_from_trial")
                    and _user_key(u) not in painel_keys
                ]
                merged = users + pending_trials
                await _write_cache(merged)
                logger.info(
                    "Painel cache refreshed (REPLACE): %d users from painel + %d "
                    "pending-trial (not yet on painel)",
                    len(users), len(pending_trials),
                )

                # Mirror ALL users to MongoDB Atlas so /pay/{painel_id} works
                # globally for EVERY existing customer — not just newly-created
                # trials. This is what makes the payment page reachable from
                # any browser worldwide, even for legacy customers.
                try:
                    from services import mongo_store
                    synced = 0
                    for u in users:
                        pid = u.get("id") or u.get("user_id")
                        if pid is None:
                            continue
                        doc = {
                            "_id": str(pid),
                            "id": pid if isinstance(pid, int) else (int(pid) if str(pid).isdigit() else pid),
                            "painel_username": u.get("username") or u.get("login"),
                            "painel_password": u.get("password"),
                            "full_name": u.get("full_name") or u.get("name"),
                            "whatsapp": u.get("_whatsapp") or extract_whatsapp(u) or u.get("whatsapp") or u.get("as_number"),
                            "system_type": detect_system_type(u),
                            "is_trial": bool(u.get("is_trial")),
                            "mac": u.get("macaddr") or u.get("mac"),
                            "exp_date_iso": (compute_expiration_info(u) or {}).get("expires_at_iso"),
                            "enabled": bool(u.get("enabled", 1)),
                        }
                        result = await mongo_store.upsert_customer(doc)
                        if result:
                            synced += 1
                    logger.info("MongoDB Atlas synced: %d of %d users", synced, len(users))
                except Exception:
                    logger.exception("Failed to sync painel users to MongoDB (non-fatal)")
            else:
                logger.warning("Painel returned empty user list — keeping existing cache intact")
            _refresh_state["last_refresh_at"] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            logger.exception("Painel cache refresh failed — keeping existing cache")
            _refresh_state["last_error"] = str(e)
        finally:
            _refresh_state["running"] = False


@router.get("/users")
async def list_users(search: Optional[str] = None, force: bool = False,
                    background_tasks: BackgroundTasks = None):
    """Return users. When `force=true` we do a SYNCHRONOUS refresh from
    painel.fun before responding — this is what the Clientes page uses
    for the "Atualizar do painel" button.

    Without `force`, we return cached data and kick off a background
    refresh whenever the cache is older than 60 seconds.
    """
    # Force-refresh path: block until we have fresh data from painel.fun.
    # Any exception here we log but fall through to the cache so the UI
    # never breaks completely.
    if force:
        try:
            await refresh_cache_task()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("force refresh failed — serving cache")

    users, updated_at = await _read_cache()

    # Trigger background refresh only when the cache is older than the
    # admin-configured `painel_refresh_interval_seconds` (default 300s).
    # Every refresh burns 2Captcha credits, so raising this saves money.
    from database import get_setting as _get_setting
    try:
        ttl_raw = (await _get_setting("painel_refresh_interval_seconds") or "300").strip()
        ttl_seconds = max(30, int(ttl_raw))  # never below 30s to keep sane
    except (TypeError, ValueError):
        ttl_seconds = 300
    should_refresh = False
    if not users:
        should_refresh = True
    elif updated_at:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(updated_at)).total_seconds()
            if age > ttl_seconds:
                should_refresh = True
        except Exception:
            should_refresh = True

    if should_refresh and background_tasks and not _refresh_state["running"]:
        background_tasks.add_task(refresh_cache_task)

    # Build public pay link + extract WhatsApp (from structured fields OR notes)
    from database import get_setting
    public_base = await get_setting("public_base_url", "")
    for u in users:
        uid = u.get("id") or u.get("user_id") or u.get("username") or u.get("login")
        if uid and public_base:
            u["_pay_link"] = f"{public_base}/pay/{uid}"

        extracted = extract_whatsapp(u)
        u["_whatsapp"] = extracted
        u["_has_whatsapp"] = bool(extracted)

        u["_system_type"] = detect_system_type(u)

        exp = compute_expiration_info(u)
        u["_expires_at"] = exp["expires_at_iso"]
        u["_days_until_expiry"] = exp["days_until_expiry"]
        u["_status"] = exp["status"]

    if search:
        s = search.lower()
        def match(u):
            for k in ("name", "full_name", "username", "login", "whatsapp", "phone", "_whatsapp", "notes", "notas", "obs"):
                v = u.get(k)
                if v and s in str(v).lower():
                    return True
            return False
        users = [u for u in users if match(u)]

    with_wa = sum(1 for u in users if u.get("_has_whatsapp"))
    by_status = {}
    for u in users:
        s = u.get("_status") or "unknown"
        by_status[s] = by_status.get(s, 0) + 1
    return {
        "users": users,
        "count": len(users),
        "count_with_whatsapp": with_wa,
        "by_status": by_status,
        "cache_updated_at": updated_at,
        "refreshing": _refresh_state["running"],
        "last_error": _refresh_state["last_error"],
    }


@router.post("/users/refresh")
async def refresh_now():
    """Trigger an immediate cache refresh. Awaits result (may take up to 90s)."""
    await refresh_cache_task()
    users, updated_at = await _read_cache()
    return {
        "success": _refresh_state["last_error"] is None,
        "count": len(users),
        "cache_updated_at": updated_at,
        "error": _refresh_state["last_error"],
    }


@router.get("/status")
async def status():
    _, updated_at = await _read_cache()
    return {
        "cache_updated_at": updated_at,
        "refreshing": _refresh_state["running"],
        "last_error": _refresh_state["last_error"],
        "last_refresh_at": _refresh_state["last_refresh_at"],
    }


@router.get("/test-connection")
async def test_connection():
    """Log into painel.fun and return credits + account info."""
    try:
        info = await painel.get_account_info()
        data = info.get("data", {})

        # Try common credit field names
        def dig(obj, keys):
            if not isinstance(obj, dict):
                return None
            for k in keys:
                v = obj.get(k)
                if v is not None:
                    return v
            # nested lookup
            for v in obj.values():
                if isinstance(v, dict):
                    r = dig(v, keys)
                    if r is not None:
                        return r
            return None

        credits = dig(data, ["credits", "credit", "balance", "saldo", "creditos", "available_credits"])
        username = dig(data, ["username", "login", "name", "email"])

        return {
            "success": True,
            "credits": credits,
            "username": username,
            "path": info.get("path"),
            "raw": data if isinstance(data, dict) and len(str(data)) < 2000 else "<truncated>",
        }
    except Exception as e:
        logger.exception("test_connection failed")
        return {"success": False, "error": str(e)}


@router.post("/renew")
async def renew(payload: RenewPayload):
    """Manually renew a painel user by ID."""
    package_id = painel.get_package_id(payload.system_type, payload.plan_months)
    try:
        result = await painel.renew_user(
            user_id=payload.user_id,
            package_id=package_id,
            months=payload.plan_months,
        )
        return {"success": True, "package_id": package_id, "raw": result}
    except Exception as e:
        logger.exception("renew failed")
        raise HTTPException(502, str(e))


@router.get("/package-ids")
async def package_ids():
    """Return the mapping so the frontend can display."""
    return painel.PACKAGE_IDS


@router.get("/debug-sample")
async def debug_sample():
    """Return the raw JSON of the FIRST cached user, plus the list of top-level
    field names present across all users. Use this to discover the actual
    field names used by painel.fun so we can add them to the extractors."""
    users, updated_at = await _read_cache()
    if not users:
        return {
            "error": "cache is empty — click 'Atualizar do painel' first",
            "cache_updated_at": updated_at,
        }

    all_keys: dict[str, int] = {}
    for u in users:
        if isinstance(u, dict):
            for k in u.keys():
                if k.startswith("_"):
                    continue  # skip our own enrichment fields
                all_keys[k] = all_keys.get(k, 0) + 1

    # Sort by frequency desc
    field_summary = sorted(all_keys.items(), key=lambda x: -x[1])

    # Strip our _-prefixed keys from the sample for clarity
    sample = {k: v for k, v in users[0].items() if not str(k).startswith("_")}

    return {
        "total_users": len(users),
        "cache_updated_at": updated_at,
        "sample_first_user_raw": sample,
        "all_field_names": [
            {"field": f, "present_in_users": n, "coverage_pct": round(100 * n / len(users), 1)}
            for f, n in field_summary
        ],
    }


@router.get("/expiring")
async def expiring_soon():
    """Preview which users would receive notifications now (does not send)."""
    from services.scheduler import _event_for_days
    from database import get_setting

    days_str = await get_setting("notification_days", "3,1,0")
    days = [int(d.strip()) for d in days_str.split(",") if d.strip()]
    users, _ = await _read_cache()

    result = []
    for u in users:
        d = u.get("_days_until_expiry")
        if d is None or d not in days:
            continue
        result.append({
            "user_id": u.get("id") or u.get("user_id") or u.get("username"),
            "name": u.get("name") or u.get("full_name") or u.get("username"),
            "whatsapp": u.get("_whatsapp"),
            "has_whatsapp": u.get("_has_whatsapp"),
            "system_type": u.get("_system_type"),
            "expires_at": u.get("_expires_at"),
            "days_until_expiry": d,
            "template_event": _event_for_days(d),
            "status": u.get("_status"),
        })
    # Sort: most urgent first (smallest days, negatives last)
    result.sort(key=lambda x: (x["days_until_expiry"] < 0, abs(x["days_until_expiry"])))
    return {"count": len(result), "days_thresholds": days, "users": result}


@router.post("/notify-now")
async def notify_now():
    """Trigger the expiration notification loop immediately."""
    from services.scheduler import _check_and_notify
    try:
        await _check_and_notify()
        return {"success": True}
    except Exception as e:
        logger.exception("notify-now failed")
        raise HTTPException(500, str(e))



class NotifyExpiredPayload(BaseModel):
    """Which users to notify. Empty `user_ids` → all currently-expired
    users with WhatsApp available. Otherwise notify only the listed ones.

    `force=True` bypasses the "already-sent-recently" dedup check and
    enqueues every selected user, even those who got the same template
    within the past 60 minutes."""
    user_ids: list[str] = []
    force: bool = False


@router.get("/expired")
async def list_expired():
    """Return the current list of expired users (with WhatsApp available),
    so the frontend can render a preview + selection UI before firing the
    manual-expired notification wave.
    """
    users, _ = await _read_cache()
    result = []
    for u in users:
        # Cache stores raw painel data — compute status server-side here so
        # we don't rely on any enrichment done by list_users().
        exp = compute_expiration_info(u)
        if exp["status"] != "expired":
            continue
        uid = u.get("id") or u.get("user_id") or u.get("username")
        if uid is None:
            continue
        wa = extract_whatsapp(u) or u.get("whatsapp") or u.get("_whatsapp")
        result.append({
            "user_id": str(uid),
            "name": u.get("full_name") or u.get("name") or u.get("username") or "",
            "username": u.get("username") or u.get("login") or "",
            "whatsapp": wa,
            "has_whatsapp": bool(wa),
            "system_type": detect_system_type(u),
            "expires_at": exp.get("expires_at_iso"),
            "days_expired": abs(exp.get("days_until_expiry") or 0),
        })
    # Sort: with-WhatsApp first, then by days_expired asc (most recent).
    result.sort(key=lambda x: (not x["has_whatsapp"], x["days_expired"]))
    return {
        "count": len(result),
        "count_with_whatsapp": sum(1 for r in result if r["has_whatsapp"]),
        "users": result,
    }


@router.post("/notify-expired")
async def notify_expired(payload: NotifyExpiredPayload):
    """Enqueue the `manual_expired_alert` template for expired users.

    When `user_ids` is empty → target ALL currently-expired users with a
    WhatsApp available. Otherwise only the listed ones. Uses the delivery
    queue so failures auto-retry every 10s.

    Two-step confirmation flow:
    1. If `force=False` (default) and any target already got the SAME
       template within the last 60 min (or has a pending queue entry),
       returns `{needs_confirmation: True, duplicates: [...]}` WITHOUT
       enqueuing — so the frontend can ask "enviar mesmo assim?".
    2. If `force=True`, dedup is bypassed and every selected user is
       enqueued (used by the confirmation button in the UI).
    """
    from services.notifier import send_notification
    from services.delivery_queue import find_recent_delivery, _resolve_dedup_config, _USE_SETTING
    from database import get_setting

    users, _ = await _read_cache()
    selected_ids = {str(x) for x in (payload.user_ids or [])}
    public_base = await get_setting("public_base_url", "")
    # Effective dedup window from settings (0 = disabled).
    dedup_window = await _resolve_dedup_config(_USE_SETTING)

    # First pass: filter valid + expired + with WhatsApp
    targets = []
    skipped_no_wa = 0
    skipped_not_expired = 0
    skipped_trial = 0
    count_active_skips = bool(selected_ids)

    # Trial package_id — skip trial users when NOT explicitly selected by admin
    # (they get their own trial_expired flow at trial creation time).
    try:
        trial_pkg_id = int(await get_setting("trial_package_id", "61"))
    except (TypeError, ValueError):
        trial_pkg_id = 61

    for u in users:
        uid = u.get("id") or u.get("user_id") or u.get("username")
        if uid is None:
            continue
        uid_str = str(uid)
        if selected_ids and uid_str not in selected_ids:
            continue

        # Skip trials unless admin explicitly picked this ID.
        if not selected_ids:
            u_pkg = u.get("package_id") or u.get("current_package_id")
            is_trial = (
                (u_pkg is not None and str(u_pkg).isdigit() and int(u_pkg) == trial_pkg_id)
                or bool(u.get("is_trial"))
                or "trial" in str(u.get("type") or "").lower()
                or "trial" in str(u.get("group") or "").lower()
            )
            if is_trial:
                skipped_trial += 1
                continue

        exp = compute_expiration_info(u)
        if exp["status"] != "expired":
            if count_active_skips:
                skipped_not_expired += 1
            continue

        phone = (extract_whatsapp(u) or u.get("whatsapp") or "").strip()
        if not phone:
            skipped_no_wa += 1
            continue

        targets.append({"user": u, "uid_str": uid_str, "phone": phone, "exp": exp})

    # Dedup check (unless force=True OR dedup disabled globally). Any target
    # with a recent send is collected into `duplicates` and — if the caller
    # didn't force — we short-circuit and let the frontend ask for
    # confirmation.
    duplicates = []
    if not payload.force and dedup_window > 0:
        for t in targets:
            recent = await find_recent_delivery(
                t["phone"], "manual_expired_alert", window_minutes=dedup_window,
            )
            if recent:
                from datetime import datetime as _dt, timezone as _tz
                # Prefer sent_at when the delivery is already sent, else use
                # created_at (still pending in queue).
                ref = recent.get("sent_at") or recent.get("created_at")
                minutes_ago = None
                try:
                    ref_dt = _dt.fromisoformat(ref.replace("Z", "+00:00")) if ref else None
                    if ref_dt:
                        if ref_dt.tzinfo is None:
                            ref_dt = ref_dt.replace(tzinfo=_tz.utc)
                        minutes_ago = int(
                            (_dt.now(_tz.utc) - ref_dt).total_seconds() / 60
                        )
                except Exception:
                    minutes_ago = None
                u = t["user"]
                duplicates.append({
                    "user_id": t["uid_str"],
                    "phone": t["phone"],
                    "name": u.get("full_name") or u.get("name")
                            or u.get("username") or "",
                    "username": u.get("username") or u.get("login") or "",
                    "status": recent["status"],
                    "sent_at": recent.get("sent_at"),
                    "created_at": recent.get("created_at"),
                    "minutes_ago": minutes_ago,
                })

        if duplicates:
            # Also compute how many WOULD be sent if the admin confirms.
            dup_ids = {d["user_id"] for d in duplicates}
            fresh_count = sum(1 for t in targets if t["uid_str"] not in dup_ids)
            return {
                "success": False,
                "needs_confirmation": True,
                "duplicates": duplicates,
                "duplicate_count": len(duplicates),
                "fresh_count": fresh_count,
                "dedup_window_minutes": dedup_window,
                "message": (
                    f"{len(duplicates)} cliente(s) já receberam esse aviso "
                    f"nos últimos {dedup_window} min. Clique em 'Enviar mesmo assim' "
                    f"para reenviar ou desmarque-os."
                ),
            }

    # Actually enqueue.
    enqueued = 0
    resent = 0
    errors = []
    for t in targets:
        u = t["user"]
        phone = t["phone"]
        uid_str = t["uid_str"]
        exp = t["exp"]
        pay_link = f"{public_base}/pay/{uid_str}" if public_base else ""
        try:
            from services.pay_link import resolve_pay_link
            pay_link = await resolve_pay_link(uid_str, pay_link)
        except Exception:
            pass
        name = u.get("full_name") or u.get("name") or u.get("username") or "cliente"
        username = u.get("username") or u.get("login") or ""

        try:
            # Track whether this send BYPASSED dedup (i.e. was a re-send).
            was_recent = False
            if payload.force:
                was_recent = bool(
                    await find_recent_delivery(
                        phone, "manual_expired_alert",
                        window_minutes=dedup_window if dedup_window > 0 else 60,
                    )
                )
            await send_notification(
                "manual_expired_alert", phone,
                {
                    "name": name,
                    "user": username or name,
                    "expires_at": exp.get("expires_at_iso") or "",
                    "pay_link": pay_link,
                    "system_type": (detect_system_type(u) or "").upper(),
                },
                customer_id=uid_str,
                force=payload.force,
            )
            enqueued += 1
            if was_recent:
                resent += 1
        except Exception as e:
            logger.exception("notify_expired for %s failed", uid_str)
            errors.append({"user_id": uid_str, "error": str(e)})

    return {
        "success": True,
        "enqueued": enqueued,
        "resent": resent,
        "skipped_no_whatsapp": skipped_no_wa,
        "skipped_not_expired": skipped_not_expired,
        "skipped_trial": skipped_trial,
        "errors": errors,
    }
