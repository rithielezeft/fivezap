"""Mercado Pago Pix (Checkout API) — create + check payments with plain httpx."""
import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)
MP_API = "https://api.mercadopago.com"


async def create_pix(access_token: str, amount_cents: int, description: str,
                     external_reference: str, payer_email: str,
                     notification_url: str | None = None, expires_minutes: int = 60 * 24) -> dict:
    expires = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {
        "transaction_amount": round(amount_cents / 100, 2),
        "description": description[:200],
        "payment_method_id": "pix",
        "external_reference": external_reference,
        "date_of_expiration": expires.strftime("%Y-%m-%dT%H:%M:%S.000-00:00"),
        "payer": {"email": payer_email},
    }
    if notification_url and notification_url.startswith("https://"):
        payload["notification_url"] = notification_url
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{MP_API}/v1/payments", json=payload,
            headers={"Authorization": f"Bearer {access_token}",
                     "X-Idempotency-Key": external_reference or str(uuid.uuid4())},
        )
    logger.info("MercadoPago POST /v1/payments HTTP %d ref=%s", resp.status_code, external_reference)
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        msg = data.get("message") or data.get("error") or resp.text[:300]
        raise RuntimeError(f"Mercado Pago recusou (HTTP {resp.status_code}): {msg}")
    tx = (data.get("point_of_interaction") or {}).get("transaction_data") or {}
    return {
        "id": str(data.get("id")),
        "status": data.get("status"),
        "qr_code": tx.get("qr_code"),
        "qr_code_base64": tx.get("qr_code_base64"),
        "ticket_url": tx.get("ticket_url"),
    }


async def get_payment(access_token: str, mp_payment_id: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{MP_API}/v1/payments/{mp_payment_id}",
                                headers={"Authorization": f"Bearer {access_token}"})
    if resp.status_code >= 400:
        return {"status": "error", "error": resp.text[:300]}
    return resp.json()


async def check_token(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{MP_API}/users/me", headers={"Authorization": f"Bearer {access_token}"})
    if resp.status_code >= 400:
        return {"ok": False, "error": resp.text[:200]}
    d = resp.json()
    return {"ok": True, "nickname": d.get("nickname"), "email": d.get("email"), "id": d.get("id")}
