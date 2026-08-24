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


# Known non-BR country codes that MAY appear right after a legacy `55` prefix.
# ONLY multi-digit codes here — single-digit codes (1=USA, 7=RU) collide with
# Brazilian area codes (11=SP, 71=BA, etc), so we can't safely strip 55
# and retry as those. For US/RU cases, the admin should edit the phone
# manually via the Customers page (which sets whatsapp_locked=1).
_FOREIGN_CC_AFTER_55 = (
    "351",  # PT (must come before shorter codes)
    "353",  # IE
    "971",  # AE
    "966",  # SA
    "34",   # ES
    "44",   # UK
    "33",   # FR
    "49",   # DE
    "39",   # IT
    "31",   # NL
    "32",   # BE
    "41",   # CH
    "43",   # AT
    "30",   # GR
    "48",   # PL
    "40",   # RO
    "90",   # TR
    "52",   # MX
    "54",   # AR
    "56",   # CL
    "57",   # CO
    "58",   # VE
    "51",   # PE
    "61",   # AU
    "64",   # NZ
    "81",   # JP
    "82",   # KR
    "86",   # CN
    "91",   # IN
    "27",   # ZA
)


async def _try_send_once(phone: str, message: str, image_url: str = None,
                         typing_ms: int = 0) -> dict:
    """Actual HTTP call to whatsapp-service. Raises on non-2xx."""
    total_timeout = max(30, (typing_ms // 1000) + 20)
    async with httpx.AsyncClient(timeout=total_timeout) as client:
        payload = {"phone": phone, "message": message}
        if image_url:
            payload["image_url"] = image_url
        if typing_ms and typing_ms > 0:
            payload["typing_ms"] = int(typing_ms)
        resp = await client.post(f"{WA_SERVICE_URL}/send", json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"WA send failed: {resp.status_code} {resp.text[:200]}")
        return resp.json()


async def send_message(phone: str, message: str, image_url: str = None,
                       typing_ms: int = 0) -> dict:
    """Send a WhatsApp message with automatic 55→foreign fallback.

    Historically some numbers were saved as `55<foreign_cc><local>` because
    old code hardcoded a 55 prefix. If the WA service rejects the send with
    "número não está no WhatsApp" AND the phone starts with 55 followed by
    a known foreign country code (34=ES, 1=US, 351=PT, 44=UK, etc.), we
    retry ONCE stripping the leading 55.

    On successful fallback, we DON'T rewrite the DB automatically — the
    admin should confirm and edit via the Customers page (which sets
    `whatsapp_locked=1`). We just log so audits can find these cases.
    """
    try:
        return await _try_send_once(phone, message, image_url, typing_ms)
    except RuntimeError as e:
        err = str(e)
        # Only retry on the specific "not on WhatsApp" 404, not on connection issues
        if "não está no WhatsApp" not in err and "not registered" not in err.lower():
            raise
        if not (phone.startswith("55") and len(phone) >= 12):
            raise
        # Try stripping the 55 and check if what's left looks like foreign E.164
        stripped = phone[2:]
        matched_cc = next(
            (cc for cc in _FOREIGN_CC_AFTER_55 if stripped.startswith(cc)),
            None,
        )
        if not matched_cc:
            raise
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            "WA 404 for %s; retrying as foreign +%s%s (leading 55 stripped)",
            phone, matched_cc, stripped[len(matched_cc):],
        )
        result = await _try_send_once(stripped, message, image_url, typing_ms)
        result["fallback_applied"] = True
        result["original_phone"] = phone
        result["retried_phone"] = stripped
        return result


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
