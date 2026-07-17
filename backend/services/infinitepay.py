"""InfinitePay Checkout integration."""
import logging
import httpx

from database import get_setting

logger = logging.getLogger(__name__)

INFINITEPAY_API = "https://api.checkout.infinitepay.io"


async def create_payment_link(
    order_nsu: str,
    amount_cents: int,
    description: str,
    redirect_url: str,
    webhook_url: str,
) -> dict:
    """Create InfinitePay checkout link."""
    handle = await get_setting("infinitepay_handle")
    if not handle:
        raise RuntimeError("InfinitePay handle not configured. Set it in Settings.")

    payload = {
        "handle": handle,
        "redirect_url": redirect_url,
        "webhook_url": webhook_url,
        "order_nsu": order_nsu,
        "items": [
            {
                "quantity": 1,
                "price": amount_cents,
                "description": description,
            }
        ],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{INFINITEPAY_API}/links", json=payload)
        if resp.status_code >= 400:
            logger.error("InfinitePay error %s: %s", resp.status_code, resp.text)
            raise RuntimeError(f"InfinitePay error: {resp.status_code} — {resp.text[:200]}")
        return resp.json()


async def check_payment(order_nsu: str) -> dict:
    """Check payment status."""
    handle = await get_setting("infinitepay_handle")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{INFINITEPAY_API}/payment_check",
            params={"handle": handle, "order_nsu": order_nsu},
        )
        if resp.status_code >= 400:
            return {"paid": False, "error": resp.text}
        return resp.json()
