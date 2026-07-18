"""Helper: fetch notification template + render + send with optional image."""
import aiosqlite
import logging

from database import DB_PATH, get_setting
from services import whatsapp_client

logger = logging.getLogger(__name__)


async def get_template(event_key: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
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


async def send_notification(event_key: str, phone: str, ctx: dict) -> bool:
    tpl = await get_template(event_key)
    if not tpl:
        logger.info("Notification template '%s' disabled or missing", event_key)
        return False
    body = render(tpl["body"], ctx)
    image = tpl.get("image_url") or None
    try:
        await whatsapp_client.send_message(phone, body, image_url=image)
        return True
    except Exception as e:
        logger.warning("send_notification %s -> %s failed: %s", event_key, phone, e)
        return False


async def send_admin_alert(message: str) -> bool:
    """Send a plain-text alert to the admin/owner WhatsApp.

    Reads `admin_whatsapp` from settings. Returns False (silently) when the
    setting is empty — this makes the caller side simple: fire-and-forget.
    """
    phone = (await get_setting("admin_whatsapp") or "").strip()
    if not phone:
        logger.info("admin_whatsapp not configured — skipping admin alert")
        return False
    try:
        await whatsapp_client.send_message(phone, message)
        logger.info("Admin alert sent to %s", phone)
        return True
    except Exception as e:
        logger.warning("send_admin_alert -> %s failed: %s", phone, e)
        return False
