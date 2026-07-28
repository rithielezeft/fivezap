"""Background scheduler for expiration notifications.

Iterates painel.fun users (source of truth) and sends WhatsApp reminders
based on `notification_days` (e.g. "3,1,0"). Uses editable notification
templates (`expiration_3d`, `expiration_1d`, `expiration_0d`) with optional
image support and per-user personalization (name, expires, pay_link).
"""
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiosqlite

from database import DB_PATH, get_setting, set_setting
from services import painel
from services.notifier import send_notification
from services.phone_extractor import extract_whatsapp
from services.expiration import compute_expiration_info

logger = logging.getLogger(__name__)


async def _get_display_tz():
    """Load admin's display timezone from settings, fallback to SP.

    Used for scheduling day boundaries: reminders fire based on the
    admin's calendar day, NOT UTC. Otherwise reminders fire ~3h early
    every night between 21:00-23:59 SP.
    """
    tz_name = (await get_setting("display_timezone", "America/Sao_Paulo")) or "America/Sao_Paulo"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning("Invalid display_timezone %r, falling back to SP", tz_name)
        return ZoneInfo("America/Sao_Paulo")


def _pick(d, keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def _event_for_days(diff_days: int) -> str | None:
    # Before expiration
    if diff_days == 7:
        return "expiration_7d"
    if diff_days == 3:
        return "expiration_3d"
    if diff_days == 1:
        return "expiration_1d"
    if diff_days == 0:
        return "expiration_0d"
    # After expiration (past due)
    if diff_days == -1:
        return "expired_1d"
    if diff_days == -3:
        return "expired_3d"
    if diff_days == -7:
        return "expired_7d"
    return None


async def check_expirations_loop():
    """Runs periodically. Notifies painel.fun users about to expire."""
    while True:
        try:
            await _check_and_notify()
        except Exception:
            logger.exception("Notification loop error")
        await asyncio.sleep(60 * 60)  # every hour


async def _check_and_notify():
    days_str = await get_setting("notification_days", "3,1,0")
    days = [int(d.strip()) for d in days_str.split(",") if d.strip()]
    public_base = await get_setting("public_base_url", "")
    # Pacing: seconds between sending to consecutive clients so we don't
    # look like a spam blast. Configurable; default 120s (2 min).
    try:
        pacing_seconds = int(await get_setting("notification_pacing_seconds", "120"))
    except Exception:
        pacing_seconds = 120
    # Typing indicator duration (ms) — makes the message feel human-typed
    # instead of instant-blasted. Default ~4s.
    try:
        typing_ms = int(await get_setting("notification_typing_ms", "4000"))
    except Exception:
        typing_ms = 4000

    # Load admin's display timezone once. Used for BOTH the days-until-expiry
    # calculation AND the dedup key so both use the admin's calendar day.
    display_tz = await _get_display_tz()

    # Try to fetch ALL users from painel.fun (paginated)
    try:
        users = await painel.list_users(limit=10000)
    except Exception as e:
        logger.warning("Skipping expiration check — painel.fun unreachable: %s", e)
        return

    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(display_tz)
    logger.info(
        "Notification check: %d users, thresholds=%s, pacing=%ds, typing=%dms, "
        "tz=%s (today=%s)",
        len(users), days, pacing_seconds, typing_ms,
        display_tz.key if hasattr(display_tz, "key") else str(display_tz),
        now_local.date().isoformat(),
    )

    sent_count = 0
    first_send = True
    for u in users:
        try:
            info = compute_expiration_info(u, tz=display_tz)
            diff_days = info["days_until_expiry"]
            exp_iso = info["expires_at_iso"]
            if diff_days is None or not exp_iso:
                continue
            if diff_days not in days:
                continue

            user_id = str(_pick(u, ["id", "user_id", "username", "login"]) or "")
            phone = extract_whatsapp(u)
            if not phone or not user_id:
                continue

            # Idempotency (STRICT): mark BEFORE sending. This guarantees
            # at most 1 attempt per day per (user, threshold). Uses the
            # admin's calendar day (NOT UTC) — otherwise the key rolls at
            # 21:00 SP and a reminder can fire twice on the same local day.
            key = f"notified_{user_id}_{diff_days}_{now_local.date().isoformat()}"
            already = await get_setting(key, "")
            if already:
                continue

            # ALSO: extra safety net — check if we already delivered this
            # exact event_key to this phone today (via /api/notifications
            # deliveries table). Prevents duplicates even if the daily
            # setting-key somehow got wiped (Mongo re-seed etc.).
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    # Start of day IN THE ADMIN'S TZ, converted back to UTC
                    # for the stored ISO comparison.
                    today_start_local = now_local.replace(
                        hour=0, minute=0, second=0, microsecond=0,
                    )
                    today_start = today_start_local.astimezone(timezone.utc).isoformat()
                    cur = await db.execute(
                        "SELECT 1 FROM notification_deliveries "
                        "WHERE phone = ? AND event_key = ? "
                        "  AND created_at >= ? LIMIT 1",
                        (str(phone), _event_for_days(diff_days) or "",
                         today_start),
                    )
                    existing_today = await cur.fetchone()
                    if existing_today:
                        logger.info(
                            "Skipping %s for %s — already delivered today "
                            "(protects against duplicate scheduler runs).",
                            _event_for_days(diff_days), phone,
                        )
                        # Mark daily-key too so next hourly cycle skips fast.
                        await set_setting(key, "1")
                        continue
            except Exception:
                logger.debug("delivery_history dedup check skipped")

            # Resolve real name — never send "cliente" if we can help it.
            name = _pick(u, ["full_name", "name", "customer_name", "display_name",
                             "username", "login"]) or ""
            if not name.strip():
                try:
                    from services.name_resolver import resolve_customer_name
                    name = await resolve_customer_name(user_id, fallback="cliente")
                except Exception:
                    name = "cliente"
            name = (name or "cliente").strip()

            # Try to grab painel_username for the {user} template variable
            # too — some admins prefer showing the login in the reminder.
            painel_login = _pick(u, ["username", "login"]) or user_id

            # Determine notification event key up-front so it can be used as
            # the attribution `?ref=` bucket in the pay_link. This lets the
            # dashboard tell us which reminder converted best.
            event = _event_for_days(diff_days)
            if not event:
                continue

            pay_link = f"{public_base}/pay/{user_id}?ref={event}"
            exp_dt = datetime.fromisoformat(exp_iso)
            ctx = {
                "name": name,
                "user": painel_login,  # painel.fun login/username
                "user_id": user_id,
                # Format in the admin's display timezone so "Expira em 03/03"
                # matches the client's actual local calendar day.
                "expires_at": exp_dt.astimezone(display_tz).strftime("%d/%m/%Y"),
                "pay_link": pay_link,
                "days": abs(diff_days),
                "discount_line": "",  # populated below only for the 7d reminder
                "discount_percent": "",
            }

            # 7-day reminder: if same-day discount is enabled, tell the client.
            # The discount is only valid *today* (same calendar day the
            # reminder is fired) — mentioning it here creates urgency.
            if diff_days == 7:
                try:
                    enabled_raw = (await get_setting("discount_7d_enabled") or "").strip().lower()
                    if enabled_raw in ("true", "1", "yes", "on"):
                        try:
                            pct = int(await get_setting("discount_7d_percent", "5"))
                        except (ValueError, TypeError):
                            pct = 5
                        if pct > 0:
                            ctx["discount_percent"] = str(pct)
                            ctx["discount_line"] = (
                                f"🎁 *Pague hoje e ganhe {pct}% de desconto* — "
                                "válido só até o fim do dia!\n\n"
                            )
                except Exception:
                    pass

            # Human-pacing: wait between clients (skip on the very first send
            # so the loop feels responsive when there's only one match).
            if not first_send and pacing_seconds > 0:
                logger.info("Pacing: sleeping %ds before next reminder", pacing_seconds)
                await asyncio.sleep(pacing_seconds)
            first_send = False

            # Mark daily-key FIRST so we never re-attempt this today, even
            # if send_notification raises or gets queued.
            await set_setting(key, "1")

            sent = await send_notification(
                event, str(phone), ctx, customer_id=user_id,
                typing_ms=typing_ms,
            )
            if sent:
                sent_count += 1
                logger.info("Sent %s reminder to %s (%s)", event, name, phone)
            else:
                logger.info(
                    "Queued %s for %s (%s) — delivery_queue will retry",
                    event, name, phone,
                )
        except Exception:
            logger.exception("Failed to process user for notification")

    logger.info("Notification check complete: %d messages sent", sent_count)
