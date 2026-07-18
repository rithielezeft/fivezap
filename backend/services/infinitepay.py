"""InfinitePay Checkout integration.

Official docs: https://docs.infinitepay.io/checkout (also seen at
docs.infinitepay.io/docs/interativo).

Minimum required payload:
    {
      "handle": "your-handle",   # without $
      "items": [
        {"quantity": 1, "price": 1000, "description": "..."}  # price in CENTS
      ]
    }

Optional: order_nsu, redirect_url, webhook_url, customer, address.

Endpoint returns { url: "https://checkout.infinitepay.io/..." }.
"""
import logging
import urllib.parse
import json
from typing import Optional

import httpx

from database import get_setting

logger = logging.getLogger(__name__)

INFINITEPAY_API = "https://api.checkout.infinitepay.io"
INFINITEPAY_CHECKOUT_BASE = "https://checkout.infinitepay.io"


async def build_webhook_url(public_base: str) -> Optional[str]:
    """Build the webhook URL we hand to InfinitePay's /links endpoint.

    If `infinitepay_webhook_secret` is set in settings, embed it as `?s=<secret>`
    so the /api/payments/webhook route can verify the caller (blocks random
    attackers hitting the public endpoint).
    """
    if not public_base:
        return None
    secret = (await get_setting("infinitepay_webhook_secret") or "").strip()
    base = f"{public_base}/api/payments/webhook"
    if secret:
        return f"{base}?s={urllib.parse.quote(secret, safe='')}"
    return base


def _sanitize_handle(raw: str) -> str:
    """Handle must not include the `$` prefix or spaces."""
    if not raw:
        return ""
    return raw.strip().lstrip("$").strip()


async def create_payment_link(
    order_nsu: str,
    amount_cents: int,
    description: str,
    redirect_url: Optional[str] = None,
    webhook_url: Optional[str] = None,
    customer_name: Optional[str] = None,
    customer_phone: Optional[str] = None,
    customer_email: Optional[str] = None,
) -> dict:
    """Create an InfinitePay checkout link via the official API.

    Returns { "url": str, "raw": dict, "handle": str, "http_status": int }.

    Raises RuntimeError with a detailed message on any failure — the caller
    (or the /test-link endpoint) will show the exact API error to the user
    so they can fix the root cause (bad handle, unverified account, etc).
    """
    raw_handle = await get_setting("infinitepay_handle")
    handle = _sanitize_handle(raw_handle or "")
    if not handle:
        raise RuntimeError(
            "InfinitePay handle não configurado. Vá em Configurações → "
            "'InfinitePay — Handle (InfiniteTag)' e informe sua tag "
            "(sem o $ na frente)."
        )
    if not amount_cents or amount_cents <= 0:
        raise RuntimeError(f"Valor inválido: {amount_cents} centavos (mínimo 1).")

    items = [{
        "quantity": 1,
        "price": int(amount_cents),
        "description": (description or "Renovação de assinatura")[:200],
    }]

    payload: dict = {
        "handle": handle,
        "items": items,
    }
    if order_nsu:
        payload["order_nsu"] = order_nsu
    if redirect_url:
        payload["redirect_url"] = redirect_url
    if webhook_url:
        payload["webhook_url"] = webhook_url
    if customer_name or customer_phone or customer_email:
        cust: dict = {}
        if customer_name:  cust["name"] = customer_name
        if customer_email: cust["email"] = customer_email
        if customer_phone: cust["phone_number"] = customer_phone
        payload["customer"] = cust

    logger.info(
        "InfinitePay POST /links | handle=%s amount=%d order_nsu=%s",
        handle, amount_cents, order_nsu,
    )
    logger.debug("Payload: %s", json.dumps(payload, ensure_ascii=False))

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{INFINITEPAY_API}/links",
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
    except Exception as e:
        raise RuntimeError(f"Falha de rede ao contatar InfinitePay: {e}")

    logger.info(
        "InfinitePay response HTTP %d | body=%s",
        resp.status_code, resp.text[:600],
    )

    # Try to parse JSON regardless of status
    try:
        data = resp.json()
    except Exception:
        data = None

    if resp.status_code >= 400:
        # Surface the ACTUAL error from InfinitePay
        error_msg = ""
        if isinstance(data, dict):
            error_msg = (
                data.get("error")
                or data.get("message")
                or data.get("detail")
                or json.dumps(data, ensure_ascii=False)
            )
        else:
            error_msg = resp.text[:400] or f"HTTP {resp.status_code}"
        raise RuntimeError(
            f"InfinitePay recusou o pedido (HTTP {resp.status_code}): {error_msg}"
        )

    if not isinstance(data, dict):
        raise RuntimeError(
            f"Resposta inesperada da InfinitePay (HTTP {resp.status_code}): "
            f"{resp.text[:300]}"
        )

    # Docs: response returns `url`. Some legacy responses may use different names.
    url = (
        data.get("url")
        or data.get("checkout_url")
        or data.get("payment_url")
        or data.get("link")
    )
    if not url:
        raise RuntimeError(
            f"InfinitePay respondeu 2xx mas sem campo 'url' na resposta. "
            f"Corpo: {json.dumps(data, ensure_ascii=False)[:400]}"
        )

    return {
        "url": url,
        "raw": data,
        "handle": handle,
        "http_status": resp.status_code,
        "payload_sent": payload,
    }


def build_direct_url(handle: str, amount_cents: int, description: str) -> str:
    """Emergency manual URL builder — use ONLY if the API is unreachable.

    NOT officially documented for /links checkout; this is a best-effort
    construction based on observed URLs in the wild. Prefer the API.
    """
    handle = _sanitize_handle(handle)
    items = [{
        "quantity": 1,
        "price": int(amount_cents),
        "description": description[:100],
    }]
    query = urllib.parse.urlencode(
        {"items": json.dumps(items, separators=(",", ":"), ensure_ascii=False)},
        quote_via=urllib.parse.quote,
    )
    return f"{INFINITEPAY_CHECKOUT_BASE}/{handle}?{query}"


async def check_payment(
    order_nsu: str,
    transaction_nsu: Optional[str] = None,
    slug: Optional[str] = None,
) -> dict:
    """Check payment status via /payment_check.

    Docs: POST https://api.checkout.infinitepay.io/payment_check
    Body: { handle, order_nsu, transaction_nsu?, slug? }
    Returns: { success, paid, amount, paid_amount, installments, capture_method }
    """
    raw_handle = await get_setting("infinitepay_handle")
    handle = _sanitize_handle(raw_handle or "")
    if not handle:
        return {"paid": False, "error": "handle not configured"}

    body: dict = {"handle": handle, "order_nsu": order_nsu}
    if transaction_nsu: body["transaction_nsu"] = transaction_nsu
    if slug:            body["slug"] = slug

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{INFINITEPAY_API}/payment_check", json=body)
        logger.info("payment_check HTTP %d body=%s", resp.status_code, resp.text[:300])
        if resp.status_code >= 400:
            return {"paid": False, "error": resp.text[:300]}
        try:
            return resp.json()
        except Exception:
            return {"paid": False, "error": "non-JSON response"}
