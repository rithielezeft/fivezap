"""Background scheduler for expiration notifications."""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

import aiosqlite

from database import DB_PATH, get_setting
from services import whatsapp_client

logger = logging.getLogger(__name__)


async def check_expirations_loop():
    """Runs periodically. Sends WhatsApp notifications to customers about to expire."""
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

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM customers WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at != ''"
        )
        customers = [dict(r) for r in await cur.fetchall()]

    now = datetime.now(timezone.utc)
    for c in customers:
        try:
            exp = datetime.fromisoformat(c["expires_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        diff_days = (exp.date() - now.date()).days
        if diff_days not in days:
            continue

        # Idempotency: skip if already notified today for this day threshold
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            key = f"notified_{c['id']}_{diff_days}_{now.date().isoformat()}"
            cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            if await cur.fetchone():
                continue

        pay_link = f"{public_base}/pay/{c['id']}"
        if diff_days > 0:
            msg = (
                f"Olá {c['name']}, seu plano vence em {diff_days} dia(s).\n"
                f"Renove agora: {pay_link}"
            )
        else:
            msg = (
                f"Olá {c['name']}, seu plano venceu hoje.\n"
                f"Renove para não perder o acesso: {pay_link}"
            )
        try:
            await whatsapp_client.send_message(c["whatsapp"], msg)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, "1"),
                )
                await db.commit()
        except Exception as e:
            logger.warning("Failed to notify %s: %s", c["whatsapp"], e)
