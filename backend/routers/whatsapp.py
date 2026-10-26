"""WhatsApp endpoints — proxy to Node service + incoming webhook."""
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from services import whatsapp_client
from services.bot import process_incoming_message, save_message

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


class PairingCodePayload(BaseModel):
    phone: str  # digits with country code, e.g. "5547999999999"


@router.post("/pairing-code")
async def pairing_code(payload: PairingCodePayload):
    """Generate an 8-character pairing code so the user can link WhatsApp
    by typing the code on their phone (Settings → Linked Devices →
    Link with phone number) instead of scanning a QR code."""
    try:
        return await whatsapp_client.request_pairing_code(payload.phone)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e))


@router.post("/send")
async def send(payload: SendPayload):
    """Send a message with the SAME anti-duplicate + pacing rules as
    automated notifications. Two identical payloads within the dedup
    window are collapsed into a single WA send; the pacer enforces the
    global `send_min_gap_seconds` between actual sends.

    Use `/send-immediate` if you need to bypass the queue (admin tests).
    """
    from services.delivery_queue import enqueue, _attempt
    from services.bot import normalize_phone, find_or_create_customer

    try:
        phone_clean = normalize_phone(payload.phone)
        # Ensure customer exists so save_message has a customer_id and
        # the delivery log ties back to a client.
        customer = await find_or_create_customer(phone_clean)

        # Enqueue with default dedup (settings-driven). Same event_key for
        # all manual sends → duplicates within the window are collapsed.
        delivery_id = await enqueue(
            event_key="manual_send",
            phone=phone_clean,
            body=payload.message or "",
            image_url=payload.image_url,
            customer_id=customer["id"],
            # dedup_window_minutes=-1 (default) → obey admin's settings
        )
        # Fire the first attempt immediately (subsequent retries are handled
        # by the queue loop). This gives the admin instant feedback.
        sent = await _attempt(delivery_id)

        note = payload.message or ("[imagem] " + (payload.image_url or ""))
        await save_message(phone_clean, note, "out", customer["id"])
        return {
            "success": sent,
            "queued": True,
            "dedup_applied": True,
            "delivery_id": delivery_id,
        }
    except Exception as e:
        raise HTTPException(502, str(e))


@router.post("/send-immediate")
async def send_immediate(payload: SendPayload):
    """Escape hatch: send immediately WITHOUT the dedup queue. Only use
    for admin tests where you WANT to burst identical messages."""
    try:
        result = await whatsapp_client.send_message(
            payload.phone, payload.message, image_url=payload.image_url,
        )
        from services.bot import normalize_phone, find_or_create_customer
        phone_clean = normalize_phone(payload.phone)
        customer = await find_or_create_customer(phone_clean)
        note = payload.message or ("[imagem] " + (payload.image_url or ""))
        await save_message(phone_clean, note, "out", customer["id"])
        return {**result, "queued": False, "dedup_applied": False}
    except Exception as e:
        raise HTTPException(502, str(e))


@router.post("/logout")
async def logout():
    return await whatsapp_client.logout()


# ---------- Groups & Channels ----------

class GroupSendPayload(BaseModel):
    chat_id: str  # full JID (`123@g.us` for groups, `123@newsletter` for channels)
    message: str = ""
    image_url: Optional[str] = None


async def _list_chats_typed(chat_type: str):
    try:
        return await whatsapp_client.list_chats(chat_type)
    except RuntimeError as e:
        # Node returned an error status. If it's "not ready" (503), return a
        # clean empty list + a hint so the frontend can render a friendly
        # empty state without triggering the Cloudflare 502 error page.
        msg = str(e)
        if "503" in msg or "not ready" in msg.lower():
            return {"chats": [], "count": 0,
                    "not_ready": True,
                    "message": "WhatsApp não conectado. Escaneie o QR primeiro."}
        raise HTTPException(502, f"Falha ao listar {chat_type}s: {e}")
    except Exception as e:
        raise HTTPException(502, f"Falha ao listar {chat_type}s: {e}")


async def _send_to_chat(payload: GroupSendPayload, expected_suffix: tuple):
    if not any(payload.chat_id.endswith(s) for s in expected_suffix):
        raise HTTPException(400, f"chat_id inválido — deve terminar em {' ou '.join(expected_suffix)}")
    if not payload.message and not payload.image_url:
        raise HTTPException(400, "message ou image_url obrigatório")
    try:
        result = await whatsapp_client.send_message(
            payload.chat_id, payload.message,
            image_url=payload.image_url,
        )
        return result
    except Exception as e:
        raise HTTPException(502, str(e))


@router.get("/groups")
async def list_groups():
    """List all WhatsApp groups the bot participates in."""
    return await _list_chats_typed("group")


@router.get("/channels")
async def list_channels():
    """List all WhatsApp channels (newsletters) the bot follows/owns."""
    return await _list_chats_typed("newsletter")


@router.post("/groups/send")
async def send_to_group(payload: GroupSendPayload):
    """Send a text (and/or image_url) message to a WhatsApp group.
    chat_id must be a full group JID ending in `@g.us`.
    """
    return await _send_to_chat(payload, ("@g.us",))


@router.post("/channels/send")
async def send_to_channel(payload: GroupSendPayload):
    """Send a text (and/or image_url) message to a WhatsApp channel.
    chat_id must be a full channel JID ending in `@newsletter`.
    """
    return await _send_to_chat(payload, ("@newsletter",))


@router.post("/groups/send-image")
async def send_image_to_group(payload: GroupSendPayload):
    """Explicit image-send convenience alias — same behavior as `/groups/send`
    with image_url set (kept as a separate endpoint per client spec).
    """
    if not payload.image_url:
        raise HTTPException(400, "image_url é obrigatório neste endpoint")
    return await _send_to_chat(payload, ("@g.us",))


@router.post("/channels/send-image")
async def send_image_to_channel(payload: GroupSendPayload):
    """Explicit image-send convenience alias for channels."""
    if not payload.image_url:
        raise HTTPException(400, "image_url é obrigatório neste endpoint")
    return await _send_to_chat(payload, ("@newsletter",))


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
