"""WhatsApp endpoints — proxy to Node service + incoming webhook."""
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


@router.post("/incoming")
async def incoming(payload: IncomingPayload):
    """Called by Node.js service when a message arrives on WhatsApp."""
    # Process asynchronously so we can return 200 immediately
    asyncio.create_task(process_incoming_message(payload.phone, payload.message, payload.from_me))
    return {"ok": True}
