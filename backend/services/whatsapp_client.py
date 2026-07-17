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


async def send_message(phone: str, message: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{WA_SERVICE_URL}/send",
            json={"phone": phone, "message": message},
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
