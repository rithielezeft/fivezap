"""WhatsApp endpoints — proxy to Node service + incoming webhook."""
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from services import whatsapp_client
from services.bot import process_incoming_message

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])
logger = logging.getLogger(__name__)


class SendPayload(BaseModel):
    phone: str
    message: str = ""
    image_url: str | None = None


class IncomingPayload(BaseModel):
    phone: str
    message: str
    from_me: bool = False
    name: Optional[str] = None
    # Real phone number extracted from Contact — critical for LID users
    # (WhatsApp privacy protocol) so we can persist it in painel reseller_notes.
    real_phone: Optional[str] = None


@router.get("/status")
async def status():
    return await whatsapp_client.get_status()


@router.get("/qr")
async def qr():
    return await whatsapp_client.get_qr()


@router.post("/send")
async def send(payload: SendPayload):
    try:
        result = await whatsapp_client.send_message(payload.phone, payload.message, image_url=payload.image_url)
        # Save outgoing message
        from services.bot import save_message, normalize_phone, find_or_create_customer
        phone_clean = normalize_phone(payload.phone)
        customer = await find_or_create_customer(phone_clean)
        note = payload.message or ("[imagem] " + (payload.image_url or ""))
        await save_message(phone_clean, note, "out", customer["id"])
        return result
    except Exception as e:
        raise HTTPException(502, str(e))


@router.post("/logout")
async def logout():
    return await whatsapp_client.logout()


@router.post("/restart")
async def restart():
    """Kill the Node WhatsApp child process and respawn it.

    Use this when Puppeteer/whatsapp-web.js gets stuck in a bad state
    (`All connection attempts failed`, protocol errors, session zombies).
    The service starts fresh; if it was authenticated, the local session
    files persist so no QR re-scan is needed most of the time.
    """
    import server as _srv
    try:
        _srv._stop_whatsapp_service()
    except Exception as e:
        logger.exception("stop_whatsapp_service failed during restart")
        raise HTTPException(500, f"stop failed: {e}")
    # Small pause so the OS releases the port + puppeteer chrome fully exits.
    await asyncio.sleep(2)
    try:
        _srv._start_whatsapp_service()
    except Exception as e:
        logger.exception("start_whatsapp_service failed during restart")
        raise HTTPException(500, f"start failed: {e}")
    # Give the Node service ~5s to boot before returning so the frontend
    # doesn't immediately show "disconnected".
    await asyncio.sleep(5)
    return {
        "success": True,
        "pid": _srv._wa_process.pid if _srv._wa_process else None,
        "message": "WhatsApp Node service reiniciado. Aguarde alguns segundos e verifique o status.",
    }


@router.post("/incoming")
async def incoming(payload: IncomingPayload):
    """Called by Node.js service when a message arrives on WhatsApp."""
    # Process asynchronously so we can return 200 immediately
    asyncio.create_task(process_incoming_message(
        payload.phone, payload.message, payload.from_me, payload.name,
        real_phone=payload.real_phone,
    ))
    return {"ok": True}
