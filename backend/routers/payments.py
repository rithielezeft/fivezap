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


@router.post("/test-link")
async def test_infinitepay_link():
    """Diagnostic endpoint: creates a R$ 1,00 test link so you can validate
    the InfinitePay integration end-to-end. Returns the URL + full request
    payload + raw response, so if it fails you know EXACTLY why."""
    public_base = await get_setting("public_base_url", "https://example.com")
    handle_raw = await get_setting("infinitepay_handle", "")
    order_nsu = f"test-{new_id()[:8]}"
    try:
        result = await infinitepay.create_payment_link(
            order_nsu=order_nsu,
            amount_cents=100,  # R$ 1,00
            description="Teste de integração — WhatsFlow",
            redirect_url=f"{public_base}/pay/test?ok=1",
            webhook_url=f"{public_base}/api/payments/webhook",
        )
        return {
            "success": True,
            "url": result["url"],
            "handle_used": result["handle"],
            "handle_raw_in_settings": handle_raw,
            "http_status": result["http_status"],
            "order_nsu": order_nsu,
            "payload_sent": result["payload_sent"],
            "response_raw": result["raw"],
        }
    except Exception as e:
        # Return the DETAILED error so user sees exactly what InfinitePay complained about
        raise HTTPException(400, str(e))


@router.post("")
async def create_payment(payload: PaymentCreate):
    """Create InfinitePay checkout link for a customer renewal.

    If customer doesn't exist in local `customers` table, auto-create it from
    the painel.fun cache. This lets any user shown in Clientes be paid for.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM customers WHERE id = ?", (payload.customer_id,))
        customer = await cur.fetchone()
        if customer:
            customer = dict(customer)

    if not customer:
        # Auto-create from painel.fun cache
        from routers.painel_users import _read_cache
        from services.system_detector import detect_system_type
        from services.expiration import compute_expiration_info
        from services.phone_extractor import extract_whatsapp

        users, _ = await _read_cache()
        found = None
        for u in users:
            uid = u.get("id") or u.get("user_id") or u.get("username")
            if str(uid) == str(payload.customer_id):
                found = u
                break
        if not found:
            raise HTTPException(
                404,
                f"Cliente {payload.customer_id} não encontrado (nem local, nem no painel). "
                f"Atualize o cache em Clientes → 'Atualizar do painel'."
            )

        exp_info = compute_expiration_info(found)
        customer = {
            "id": str(found.get("id") or found.get("user_id") or found.get("username")),
            "name": found.get("full_name") or found.get("name") or found.get("username") or "Cliente",
            "system_type": detect_system_type(found) or "iptv",
            "expires_at": exp_info["expires_at_iso"] or "",
            "whatsapp": extract_whatsapp(found) or "",
            "painel_username": found.get("username") or "",
        }
        # Persist so the webhook can find it later
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO customers "
                "(id, name, whatsapp, system_type, painel_username, expires_at, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                (
                    customer["id"],
                    customer["name"],
                    customer["whatsapp"] or "",
                    customer["system_type"],
                    customer["painel_username"],
                    customer["expires_at"],
                    now_iso(),
                    now_iso(),
                ),
            )
            await db.commit()
        logger.info("Auto-created customer from painel cache: %s (%s)", customer["name"], customer["id"])

    price_key = f"plan_price_{payload.plan_months}m"
    price_str = await get_setting(price_key, "35,00")
    # Convert "35,00" or "35.00" to cents
    normalized = price_str.replace(",", ".").strip()
    try:
        amount = int(round(float(normalized) * 100))
    except ValueError:
        amount = 3500
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
                from services.notifier import send_notification
                new_expires = result.get("expires_at") or result.get("expiration") or ""
                await send_notification(
                    "renewal_success",
                    customer["whatsapp"],
                    {
                        "name": customer["name"],
                        "plan_months": payment["plan_months"],
                        "new_expires_at": new_expires,
                    },
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
    """Public: fetch payment info for /pay/{customer_id} page.

    `customer_id` can be EITHER:
      - The painel.fun trial user id (e.g. 227453827) — used in the {pay_link}
        template placeholder, which is what we send to customers.
      - The local `customers.id` UUID — used by the admin panel.

    Lookup order (all local, never dependent on painel.fun availability):
      1. `trials.trial_user_id` — matches the painel id used in every {pay_link}
         we send. Joined with `customers` for name/whatsapp. **Primary source of truth.**
      2. Local `customers.id` — matches the UUID (admin-created).
      3. `customers.painel_username` — legacy fallback for old records.
      4. Painel cache — last resort for users created before we started
         persisting trials (or bulk-imported customers).

    Steps 1-3 are 100% local: SQLite on the Raspberry Pi. Once a trial is
    created, `/pay/{id}` works forever from any browser worldwide, no
    dependency on painel.fun uptime, cache freshness, or Turnstile solves.
    """
    customer = None

    # 0. FIRST: MongoDB Atlas (shared source of truth across all environments).
    #    This makes /pay/{painel_id} work anywhere in the world, regardless of
    #    which Raspberry Pi / preview / prod host is serving the request.
    try:
        from services import mongo_store
        mongo_doc = await mongo_store.find_customer_by_painel_id(str(customer_id))
        if mongo_doc:
            customer = {
                "id": str(mongo_doc.get("_id") or mongo_doc.get("id") or customer_id),
                "name": (mongo_doc.get("full_name") or mongo_doc.get("name")
                         or mongo_doc.get("username") or mongo_doc.get("painel_username")
                         or "Cliente"),
                "system_type": mongo_doc.get("system_type") or "iptv",
                "expires_at": (mongo_doc.get("exp_date_iso") or mongo_doc.get("expires_at")),
            }
    except Exception as e:
        logger.warning("mongo lookup failed for %s: %s", customer_id, e)

    if customer is None:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            # 1. Lookup by painel trial_user_id (JOIN with customers for the name/whatsapp).
            #    This is the PRIMARY LOCAL path — every {pay_link} we send uses the painel id.
            cur = await db.execute(
                """
                SELECT
                    t.trial_user_id AS painel_id,
                    t.system_type AS trial_system_type,
                    t.expires_at AS trial_expires_at,
                    c.id AS local_id,
                    c.name AS name,
                    c.whatsapp AS whatsapp,
                    c.system_type AS customer_system_type,
                    c.expires_at AS customer_expires_at
                FROM trials t
                LEFT JOIN customers c ON c.id = t.customer_id
                WHERE t.trial_user_id = ?
                ORDER BY t.created_at DESC
                LIMIT 1
                """,
                (str(customer_id),),
            )
            row = await cur.fetchone()
            if row:
                customer = {
                    "id": str(row["painel_id"] or row["local_id"] or customer_id),
                    "name": row["name"] or "Cliente",
                    "system_type": row["trial_system_type"] or row["customer_system_type"] or "iptv",
                    "expires_at": row["trial_expires_at"] or row["customer_expires_at"],
                }

            # 2. Lookup by local customer UUID
            if not customer:
                cur = await db.execute(
                    "SELECT id, name, system_type, expires_at FROM customers WHERE id = ?",
                    (str(customer_id),),
                )
                row = await cur.fetchone()
                if row:
                    customer = dict(row)

            # 3. Lookup by painel_username
            if not customer:
                cur = await db.execute(
                    "SELECT id, name, system_type, expires_at FROM customers WHERE painel_username = ?",
                    (str(customer_id),),
                )
                row = await cur.fetchone()
                if row:
                    customer = dict(row)

    # 4. Last resort: painel cache
    if not customer:
        from routers.painel_users import _read_cache
        from services.system_detector import detect_system_type
        from services.expiration import compute_expiration_info

        users, _ = await _read_cache()
        found = None
        for u in users:
            uid = u.get("id") or u.get("user_id") or u.get("username")
            if str(uid) == str(customer_id):
                found = u
                break

        if found:
            exp_info = compute_expiration_info(found)
            customer = {
                "id": str(found.get("id") or found.get("user_id") or found.get("username")),
                "name": found.get("full_name") or found.get("name") or found.get("username") or "Cliente",
                "system_type": detect_system_type(found) or "iptv",
                "expires_at": exp_info["expires_at_iso"],
            }

    if not customer:
        raise HTTPException(
            404,
            f"Cliente {customer_id} não encontrado. "
            f"Atualize o cache do painel em Clientes → 'Atualizar do painel'."
        )

    # Fetch prices for all 4 plans
    prices = {}
    for m in (1, 3, 6, 12):
        v = await get_setting(f"plan_price_{m}m", "35,00")
        try:
            prices[m] = int(round(float(v.replace(",", ".").strip()) * 100))
        except ValueError:
            prices[m] = 3500

    return {"customer": customer, "prices_cents": prices}
