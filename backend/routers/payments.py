"""Payments — InfinitePay integration + webhook."""
import logging
from fastapi import APIRouter, HTTPException, Request
from typing import List
import aiosqlite

from database import DB_PATH, get_setting
from models import Payment, PaymentCreate, new_id, now_iso
from services import infinitepay, painel
from services.bot import log_activity, save_message
from services import whatsapp_client

router = APIRouter(prefix="/api/payments", tags=["payments"])
logger = logging.getLogger(__name__)


@router.get("", response_model=List[Payment])
async def list_payments():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM payments ORDER BY created_at DESC LIMIT 200")
        return [Payment(**dict(r)) for r in await cur.fetchall()]


@router.post("")
async def create_payment(payload: PaymentCreate):
    """Create InfinitePay checkout link for a customer renewal."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM customers WHERE id = ?", (payload.customer_id,))
        customer = await cur.fetchone()
        if not customer:
            raise HTTPException(404, "Customer not found")
        customer = dict(customer)

    price_key = f"plan_price_{payload.plan_months}m_cents"
    amount = int(await get_setting(price_key, "3500"))
    package_id = painel.get_package_id(customer["system_type"], payload.plan_months)

    public_base = await get_setting("public_base_url")
    order_nsu = f"ord-{new_id()[:8]}"
    payment_id = new_id()

    try:
        link_data = await infinitepay.create_payment_link(
            order_nsu=order_nsu,
            amount_cents=amount,
            description=f"Renovação {customer['system_type'].upper()} — {payload.plan_months} mês(es)",
            redirect_url=f"{public_base}/pay/{payload.customer_id}?ok=1",
            webhook_url=f"{public_base}/api/payments/webhook",
        )
    except Exception as e:
        raise HTTPException(502, f"InfinitePay error: {e}")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO payments (id, customer_id, plan_months, amount_cents, package_id, status, infinitepay_url, order_nsu, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (payment_id, payload.customer_id, payload.plan_months, amount, package_id,
             link_data.get("url"), order_nsu, now_iso()),
        )
        await db.commit()

    await log_activity("payment_created", f"Cobrança criada para {customer['name']}", payload.customer_id, "info", link_data)

    return {
        "payment_id": payment_id,
        "url": link_data.get("url"),
        "amount_cents": amount,
        "order_nsu": order_nsu,
    }


@router.post("/webhook")
async def webhook(request: Request):
    """Called by InfinitePay when a payment succeeds."""
    body = await request.json()
    logger.info("InfinitePay webhook: %s", body)

    order_nsu = body.get("order_nsu") or body.get("orderNsu")
    paid = body.get("paid") or body.get("status") == "paid" or body.get("payment_status") == "approved"

    if not order_nsu:
        return {"ok": False, "error": "missing order_nsu"}

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM payments WHERE order_nsu = ?", (order_nsu,))
        payment = await cur.fetchone()
        if not payment:
            return {"ok": False, "error": "payment not found"}
        payment = dict(payment)

    if not paid:
        return {"ok": True, "status": "not_paid"}

    if payment["status"] == "paid":
        return {"ok": True, "status": "already_processed"}

    # Mark paid and renew via painel
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "UPDATE payments SET status = 'paid', paid_at = ? WHERE id = ?",
            (now_iso(), payment["id"]),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM customers WHERE id = ?", (payment["customer_id"],))
        customer = dict(await cur.fetchone())

    # Trigger renewal
    try:
        # If we have painel user id, renew directly. Otherwise, we log a manual action needed
        if customer.get("painel_username"):
            result = await painel.renew_user(
                user_id=customer.get("painel_username"),
                package_id=payment["package_id"],
            )
            await log_activity("renewal_success", f"Renovação {payment['plan_months']}m para {customer['name']}", customer["id"], "success", result)
            try:
                await whatsapp_client.send_message(
                    customer["whatsapp"],
                    f"✅ Pagamento confirmado! Seu plano foi renovado por {payment['plan_months']} mês(es). Obrigado!"
                )
                await save_message(customer["whatsapp"], "renewal_confirmed", "out", customer["id"])
            except Exception:
                pass
        else:
            await log_activity("renewal_pending", f"Pagamento confirmado, renovação manual necessária para {customer['name']}", customer["id"], "warning")
    except Exception as e:
        logger.exception("Renewal failed")
        await log_activity("renewal_error", str(e), customer["id"], "error")

    return {"ok": True}


@router.get("/customer/{customer_id}")
async def get_customer_payment_info(customer_id: str):
    """Public: fetch payment info for /pay/{customer_id} page."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT id, name, system_type, expires_at FROM customers WHERE id = ?", (customer_id,))
        customer = await cur.fetchone()
        if not customer:
            raise HTTPException(404, "Customer not found")
        customer = dict(customer)

    prices = {}
    for m in (1, 3, 6, 12):
        prices[m] = int(await get_setting(f"plan_price_{m}m_cents", "3500"))

    return {"customer": customer, "prices_cents": prices}
