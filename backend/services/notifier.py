"""Helper: fetch notification template + render + send with optional image."""
import aiosqlite
import logging

import database
from database import get_setting
from services import whatsapp_client

logger = logging.getLogger(__name__)


async def get_template(event_key: str) -> dict | None:
    async with aiosqlite.connect(database.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM notification_templates WHERE event_key = ? AND enabled = 1",
            (event_key,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


def render(template: str, ctx: dict) -> str:
    if not template:
        return ""
    out = template
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", str(v if v is not None else ""))
    return out


async def send_notification(event_key: str, phone: str, ctx: dict,
                            customer_id: str | None = None,
                            typing_ms: int = 0) -> bool:
    """Enqueue a template-rendered notification. Returns True if the FIRST
    attempt succeeded synchronously (message delivered inline), False if it
    was queued for retry. Missing/disabled template → returns False without
    enqueuing anything (caller decides fallback).

    `typing_ms`: optional "digitando..." duration before the actual send.
    Passed through to the WhatsApp service.
    """
    tpl = await get_template(event_key)
    if not tpl:
        logger.info("Notification template '%s' disabled or missing", event_key)
        return False
    body = render(tpl["body"], ctx)
    image = tpl.get("image_url") or None
    try:
        from services.delivery_queue import enqueue
        delivery_id = await enqueue(
            event_key=event_key,
            phone=phone,
            body=body,
            image_url=image,
            customer_id=customer_id,
            typing_ms=typing_ms,
        )
        # `enqueue` already tried once synchronously — re-read to see the outcome.
        import aiosqlite
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT status FROM notification_deliveries WHERE id = ?",
                (delivery_id,),
            )
            row = await cur.fetchone()
            return bool(row and row["status"] == "sent")
    except Exception as e:
        logger.warning("send_notification %s -> %s failed: %s", event_key, phone, e)
        return False


async def send_hardcoded(phone: str, body: str, event_key: str = "hardcoded",
                        customer_id: str | None = None) -> bool:
    """Send a raw message (not from template) through the delivery queue.
    Same retry semantics — the client is never left without confirmation."""
    try:
        from services.delivery_queue import enqueue
        delivery_id = await enqueue(
            event_key=event_key, phone=phone, body=body,
            image_url=None, customer_id=customer_id,
        )
        import aiosqlite
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT status FROM notification_deliveries WHERE id = ?",
                (delivery_id,),
            )
            row = await cur.fetchone()
            return bool(row and row["status"] == "sent")
    except Exception as e:
        logger.warning("send_hardcoded -> %s failed: %s", phone, e)
        return False


async def send_admin_alert(message: str) -> bool:
    """Send a plain-text alert to the admin/owner WhatsApp — via the queue,
    so admin alerts also survive momentary WhatsApp downtime.

    Reads `admin_whatsapp` from settings. Returns True if delivered on the
    first attempt, False if queued for retry (or if admin_whatsapp is empty).
    """
    phone = (await get_setting("admin_whatsapp") or "").strip()
    if not phone:
        logger.info("admin_whatsapp not configured — skipping admin alert")
        return False
    return await send_hardcoded(phone, message, event_key="admin_alert")
