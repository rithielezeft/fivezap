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

    Also used by refresh_cache_task to merge painel results with previously
    known users, so a transient painel outage never makes previously-active
    payment links stop working ("Link inválido") for other customers.
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
        if k in by_key:
            # Merge: new fields overwrite old ones, but keep old fields we don't get
            by_key[k] = {**by_key[k], **u}
        else:
            by_key[k] = u
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
            # MERGE strategy: never wipe already-known users when painel
            # returns an empty/short list (transient error, throttling, etc.).
            # This guarantees active pay links stay valid.
            if users:
                added = await upsert_users_in_cache(users)
                logger.info("Painel cache refreshed: %d users (added %d new)", len(users), added)

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
async def list_users(search: Optional[str] = None, background_tasks: BackgroundTasks = None):
    """Return cached users. Kick off a refresh in background if the cache is old."""
    users, updated_at = await _read_cache()

    # Trigger background refresh if cache is empty or older than 10 minutes
    should_refresh = False
    if not users:
        should_refresh = True
    elif updated_at:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(updated_at)).total_seconds()
            if age > 600:
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
        result = await painel.renew_user(user_id=payload.user_id, package_id=package_id)
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
