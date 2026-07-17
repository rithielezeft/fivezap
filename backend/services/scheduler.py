"""Background scheduler for expiration notifications.

Iterates painel.fun users (source of truth) and sends WhatsApp reminders
based on `notification_days` (e.g. "3,1,0"). Uses editable notification
templates (`expiration_3d`, `expiration_1d`, `expiration_0d`) with optional
image support and per-user personalization (name, expires, pay_link).
"""
import asyncio
import logging
from datetime import datetime, timezone

import aiosqlite

from database import DB_PATH, get_setting, set_setting
from services import painel
from services.notifier import send_notification

logger = logging.getLogger(__name__)


def _pick(d, keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def _event_for_days(diff_days: int) -> str | None:
    if diff_days == 0:
        return "expiration_0d"
    if diff_days == 1:
        return "expiration_1d"
    if diff_days == 3:
        return "expiration_3d"
    # fallback to generic 3d template if the day is configured but not standard
    return "expiration_3d"


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

    # Try to fetch users from painel.fun
    try:
        users = await painel.list_users(limit=1000)
    except Exception as e:
        logger.warning("Skipping expiration check — painel.fun unreachable: %s", e)
        return

    now = datetime.now(timezone.utc)
    logger.info("Notification check: %d users to scan, thresholds=%s", len(users), days)

    for u in users:
        try:
            exp_raw = _pick(u, ["expires_at", "expiration", "expiry_date", "expire_date"])
            if not exp_raw:
                continue
            try:
                exp = datetime.fromisoformat(str(exp_raw).replace("Z", "+00:00"))
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            diff_days = (exp.date() - now.date()).days
            if diff_days not in days:
                continue

            user_id = str(_pick(u, ["id", "user_id", "username", "login"]) or "")
            phone = _pick(u, ["whatsapp", "phone", "telephone", "mobile"])
            if not phone or not user_id:
                continue

            # Idempotency: only send once per day per threshold per user
            key = f"notified_{user_id}_{diff_days}_{now.date().isoformat()}"
            already = await get_setting(key, "")
            if already:
                continue

            name = _pick(u, ["name", "full_name", "customer_name"]) or "cliente"
            pay_link = f"{public_base}/pay/{user_id}"
            ctx = {
                "name": name,
                "user_id": user_id,
                "expires_at": exp.astimezone(timezone.utc).strftime("%d/%m/%Y"),
                "pay_link": pay_link,
                "days": diff_days,
            }

            event = _event_for_days(diff_days)
            sent = await send_notification(event, str(phone), ctx)
            if sent:
                await set_setting(key, "1")
                logger.info("Sent %s reminder to %s (%s)", event, name, phone)
        except Exception:
            logger.exception("Failed to process user for notification")
