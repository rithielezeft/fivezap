"""InfinitePay Checkout integration.

Docs: https://www.infinitepay.io/checkout-documentacao

Two ways to generate a checkout link:
  1. API POST /links          → server-side, best (default)
  2. Direct URL (fallback)    → https://checkout.infinitepay.io/{handle}?items=[...]&...

We attempt #1 first; if it fails for any reason we fall back to #2 so the user
always gets a working payment link.
"""
import json
import logging
import urllib.parse
from typing import Optional

import httpx

from database import get_setting

logger = logging.getLogger(__name__)

INFINITEPAY_API = "https://api.checkout.infinitepay.io"
INFINITEPAY_CHECKOUT_BASE = "https://checkout.infinitepay.io"


def _sanitize_handle(raw: str) -> str:
    """Handle must not include the `$` prefix or spaces."""
    if not raw:
        return ""
    return raw.strip().lstrip("$").strip()


def _build_direct_url(
    handle: str,
    amount_cents: int,
    description: str,
    order_nsu: str,
    redirect_url: str,
) -> str:
    """Build a direct checkout URL manually (bypasses the API).

    Docs format:
      https://checkout.infinitepay.io/{handle}?items=[{"name":"..","price":1000,"quantity":1}]&order_nsu=...&redirect_url=...

    Note the direct URL uses `name` (not `description`) and the JSON must be URL-encoded.
    """
    items = [{
        "name": description[:100],   # trim to be safe
        "price": int(amount_cents),
        "quantity": 1,
    }]
    items_json = json.dumps(items, separators=(",", ":"), ensure_ascii=False)
    params = {
        "items": items_json,
        "order_nsu": order_nsu,
    }
    if redirect_url:
        params["redirect_url"] = redirect_url
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"{INFINITEPAY_CHECKOUT_BASE}/{handle}?{query}"


async def create_payment_link(
    order_nsu: str,
    amount_cents: int,
    description: str,
    redirect_url: Optional[str] = None,
    webhook_url: Optional[str] = None,
) -> dict:
    """Create an InfinitePay checkout link.

    Returns a dict with at least a `url` key. Falls back to a directly-built URL
    if the API call fails.
    """
    raw_handle = await get_setting("infinitepay_handle")
    handle = _sanitize_handle(raw_handle or "")
    if not handle:
        raise RuntimeError(
            "InfinitePay handle não configurado. Vá em Configurações → InfiniteTag."
        )
    if not amount_cents or amount_cents <= 0:
        raise RuntimeError(f"Valor inválido: {amount_cents} centavos")

    payload = {
        "handle": handle,
        "order_nsu": order_nsu,
        "items": [{
            "quantity": 1,
            "price": int(amount_cents),
            "description": description[:200] if description else "Renovação de assinatura",
        }],
    }
    if redirect_url:
        payload["redirect_url"] = redirect_url
    if webhook_url:
        payload["webhook_url"] = webhook_url

    logger.info(
        "InfinitePay create_link payload: handle=%s amount=%d order_nsu=%s",
        handle, amount_cents, order_nsu,
    )

    # ---- Try 1: official API endpoint ----
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{INFINITEPAY_API}/links", json=payload)
            logger.info("InfinitePay API response %d: %s", resp.status_code, resp.text[:400])
            if resp.status_code < 400:
                try:
                    data = resp.json()
                except Exception:
                    data = {}
                # Docs return `url`; older/legacy responses may use `checkout_url`
                url = data.get("url") or data.get("checkout_url") or data.get("payment_url")
                if url:
                    return {"url": url, "raw": data, "via": "api"}
                logger.warning(
                    "InfinitePay 2xx but no url in response: %s. Using direct URL fallback.",
                    data,
                )
            else:
                logger.warning(
                    "InfinitePay API HTTP %d: %s. Using direct URL fallback.",
                    resp.status_code, resp.text[:200],
                )
    except Exception as e:
        logger.warning("InfinitePay API request failed: %s. Using direct URL fallback.", e)

    # ---- Try 2: direct URL (always works if handle is valid) ----
    direct_url = _build_direct_url(
        handle=handle,
        amount_cents=amount_cents,
        description=description or "Renovação de assinatura",
        order_nsu=order_nsu,
        redirect_url=redirect_url or "",
    )
    logger.info("InfinitePay using direct URL: %s", direct_url)
    return {"url": direct_url, "raw": {"payload": payload}, "via": "direct"}


async def check_payment(order_nsu: str) -> dict:
    """Check payment status via the InfinitePay payment_check endpoint."""
    raw_handle = await get_setting("infinitepay_handle")
    handle = _sanitize_handle(raw_handle or "")
    if not handle:
        return {"paid": False, "error": "handle not configured"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{INFINITEPAY_API}/payment_check",
            params={"handle": handle, "order_nsu": order_nsu},
        )
        if resp.status_code >= 400:
            return {"paid": False, "error": resp.text[:300]}
        try:
            return resp.json()
        except Exception:
            return {"paid": False, "error": "non-JSON response"}
