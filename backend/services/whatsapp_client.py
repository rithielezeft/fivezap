"""Client to communicate with the Node.js whatsapp-web.js service."""
import logging
import os
import httpx

logger = logging.getLogger(__name__)

WA_SERVICE_URL = os.environ.get("WHATSAPP_SERVICE_URL", "http://localhost:3001")


async def get_status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{WA_SERVICE_URL}/status")
            return resp.json()
    except Exception as e:
        logger.warning("WA service unreachable: %s", e)
        return {"ready": False, "state": "disconnected", "error": str(e)}


async def get_qr() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{WA_SERVICE_URL}/qr")
            return resp.json()
    except Exception as e:
        return {"qr": None, "error": str(e)}


async def send_message(phone: str, message: str, image_url: str = None,
                       typing_ms: int = 0) -> dict:
    """Send a WhatsApp message. Optionally shows "digitando..." for
    `typing_ms` milliseconds before the message is delivered (max 15s).
    Useful for expiration reminders to feel human, not batch-blasted."""
    # httpx client timeout must exceed typing_ms + wa network overhead.
    total_timeout = max(30, (typing_ms // 1000) + 20)
    async with httpx.AsyncClient(timeout=total_timeout) as client:
        payload = {"phone": phone, "message": message}
        if image_url:
            payload["image_url"] = image_url
        if typing_ms and typing_ms > 0:
            payload["typing_ms"] = int(typing_ms)
        resp = await client.post(
            f"{WA_SERVICE_URL}/send",
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"WA send failed: {resp.status_code} {resp.text[:200]}")
        return resp.json()


async def logout() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{WA_SERVICE_URL}/logout")
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def request_pairing_code(phone: str) -> dict:
    """Request an 8-char pairing code as an alternative to QR scanning.
    User types this code in the phone's WhatsApp under
    Settings → Linked Devices → Link with phone number.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{WA_SERVICE_URL}/pairing-code",
            json={"phone": phone},
        )
        if resp.status_code >= 400:
            try:
                err = resp.json().get("error", resp.text)
            except Exception:
                err = resp.text
            raise RuntimeError(err)
        return resp.json()


async def list_chats(chat_type: str = "group") -> dict:
    """List chats of a given type. `chat_type` in {"group","newsletter"}."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{WA_SERVICE_URL}/chats",
                                params={"type": chat_type})
        if resp.status_code >= 400:
            raise RuntimeError(f"WA list_chats failed: {resp.status_code} {resp.text[:200]}")
        return resp.json()
