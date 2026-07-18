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
        # Try MongoDB Atlas first (works globally)
        try:
            from services import mongo_store
            mongo_doc = await mongo_store.find_customer_by_painel_id(str(payload.customer_id))
        except Exception:
            mongo_doc = None
        if mongo_doc:
            customer = {
                "id": str(mongo_doc.get("_id") or mongo_doc.get("id") or payload.customer_id),
                "name": (mongo_doc.get("full_name") or mongo_doc.get("name")
                         or mongo_doc.get("username") or "Cliente"),
                "system_type": mongo_doc.get("system_type") or "iptv",
                "expires_at": mongo_doc.get("exp_date_iso") or mongo_doc.get("expires_at") or "",
                "whatsapp": mongo_doc.get("whatsapp") or "",
                "painel_username": mongo_doc.get("painel_username") or mongo_doc.get("username") or "",
            }
            # Persist locally so the webhook can find it later
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO customers "
                    "(id, name, whatsapp, system_type, painel_username, expires_at, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                    (
                        customer["id"], customer["name"], customer["whatsapp"],
                        customer["system_type"], customer["painel_username"],
                        customer["expires_at"], now_iso(), now_iso(),
                    ),
                )
                await db.commit()

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
    # order_nsu MUST include the painel id so the webhook can call
    # /api/users/{painel_id}/renew even without querying local DB.
    # Format: `renew-{painel_id}-{months}m` (matches _extract_painel_id_from_nsu)
    order_nsu = f"renew-{payload.customer_id}-{payload.plan_months}m"
    payment_id = new_id()

    try:
        # Bind the InfinitePay payment to the customer's PAINEL USERNAME (not
        # full name) — this way, the checkout shows "oscarnew" (or whatever
        # username was created in the panel) and it stays traceable back to
        # the exact user_id being renewed. Phone is left empty so the
        # customer fills it themselves at checkout (opcional).
        painel_username = (customer.get("painel_username")
                           or customer.get("username")
                           or customer.get("name")
                           or "")

        link_data = await infinitepay.create_payment_link(
            order_nsu=order_nsu,
            amount_cents=amount,
            description=f"Renovação {customer['system_type'].upper()} — {payload.plan_months} mês(es)",
            redirect_url=f"{public_base}/pay/{payload.customer_id}?ok=1",
            webhook_url=f"{public_base}/api/payments/webhook",
            customer_name=painel_username or None,
            customer_phone=None,
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

    # Mirror to MongoDB Atlas so admins can inspect the payment from any env
    try:
        from services import mongo_store
        await mongo_store.upsert_payment({
            "_id": payment_id,
            "customer_id": payload.customer_id,
            "customer_name": customer["name"],
            "customer_whatsapp": customer.get("whatsapp") or "",
            "plan_months": payload.plan_months,
            "amount_cents": amount,
            "package_id": package_id,
            "system_type": customer["system_type"],
            "status": "pending",
            "infinitepay_url": link_data.get("url"),
            "order_nsu": order_nsu,
            "created_at": now_iso(),
        })
    except Exception:
        logger.exception("Failed to mirror payment to MongoDB (non-fatal)")

    await log_activity("payment_created", f"Cobrança criada para {customer['name']}", payload.customer_id, "info", link_data)

    return {
        "payment_id": payment_id,
        "url": link_data.get("url"),
        "amount_cents": amount,
        "order_nsu": order_nsu,
    }


def _extract_painel_id_from_nsu(nsu: str) -> str:
    """Order NSU format is `trial-{painel_id}-{months}m` (or {plan}). Extract painel_id."""
    if not nsu:
        return ""
    parts = str(nsu).split("-")
    if len(parts) >= 2:
        return parts[1]
    return ""


@router.post("/webhook")
async def webhook(request: Request):
    """Called by InfinitePay when a payment succeeds.

    InfinitePay sends different field names depending on the integration version.
    We accept several shapes and log the full body for future debugging.
    """
    body = await request.json()
    logger.info("InfinitePay webhook received: %s", body)

    # Try multiple field name variations
    order_nsu = (body.get("order_nsu") or body.get("orderNsu")
                 or body.get("reference") or body.get("external_reference")
                 or body.get("nsu"))
    paid = (
        body.get("paid") is True
        or body.get("status") in ("paid", "approved", "PAID", "APPROVED", "completed")
        or body.get("payment_status") in ("approved", "paid", "APPROVED", "PAID")
    )

    if not order_nsu:
        logger.warning("InfinitePay webhook missing order_nsu: %s", body)
        return {"ok": False, "error": "missing order_nsu"}

    result = await _process_payment_confirmation(str(order_nsu), paid=paid, source="webhook", raw=body)
    return result


async def _process_payment_confirmation(order_nsu: str, paid: bool, source: str = "webhook", raw: dict = None):
    """Shared logic: mark payment paid + call painel renew_user + notify client.

    Used by both /webhook (InfinitePay callback) and /reprocess/{payment_id}
    (admin manual re-trigger when webhook didn't arrive).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM payments WHERE order_nsu = ?", (order_nsu,))
        payment_row = await cur.fetchone()
        if not payment_row:
            logger.warning("Payment not found for order_nsu=%s (source=%s)", order_nsu, source)
            return {"ok": False, "error": "payment not found", "order_nsu": order_nsu}
        payment = dict(payment_row)

    if not paid:
        return {"ok": True, "status": "not_paid", "payment_id": payment["id"]}

    if payment["status"] == "paid":
        return {"ok": True, "status": "already_processed", "payment_id": payment["id"]}

    # Mark paid
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE payments SET status = 'paid', paid_at = ? WHERE id = ?",
            (now_iso(), payment["id"]),
        )
        await db.commit()

    # Resolve customer info + painel_id
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM customers WHERE id = ?", (payment["customer_id"],))
        customer_row = await cur.fetchone()
        customer = dict(customer_row) if customer_row else {"id": payment["customer_id"], "name": "?", "whatsapp": "", "system_type": ""}

    # If customer info is missing (e.g. legacy customer only in Mongo), fill from Mongo
    if not customer.get("whatsapp") or not customer.get("name") or customer.get("name") == "?":
        try:
            from services import mongo_store
            mongo_doc = await mongo_store.find_customer_by_painel_id(str(payment["customer_id"]))
            if mongo_doc:
                if not customer.get("name") or customer.get("name") == "?":
                    customer["name"] = (mongo_doc.get("full_name") or mongo_doc.get("name")
                                        or mongo_doc.get("username") or "Cliente")
                if not customer.get("whatsapp"):
                    customer["whatsapp"] = mongo_doc.get("whatsapp") or ""
                if not customer.get("system_type"):
                    customer["system_type"] = mongo_doc.get("system_type") or ""
        except Exception:
            logger.exception("Mongo lookup for customer fallback failed")

    # PAINEL ID = the numeric id painel.fun uses in /api/users/{id}/renew.
    # We prefer the id embedded in order_nsu (`trial-{painel_id}-{months}m`),
    # then fall back to any trial we have for this customer.
    painel_id = _extract_painel_id_from_nsu(order_nsu)
    if not painel_id or not painel_id.isdigit():
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT trial_user_id FROM trials WHERE customer_id = ? AND trial_user_id != '' "
                "ORDER BY created_at DESC LIMIT 1",
                (customer["id"],),
            )
            trow = await cur.fetchone()
            if trow and trow["trial_user_id"]:
                painel_id = str(trow["trial_user_id"])

    if not painel_id:
        await log_activity(
            "renewal_pending",
            f"Pagamento confirmado ({source}) mas painel_id não encontrado — renovar manualmente para {customer['name']}",
            customer["id"], "warning", raw or {},
        )
        return {"ok": True, "status": "paid_no_painel_id", "payment_id": payment["id"]}

    # Trigger painel renewal
    try:
        result = await painel.renew_user(user_id=painel_id, package_id=payment["package_id"])
        await log_activity(
            "renewal_success",
            f"Renovação {payment['plan_months']}m para {customer['name']} (painel_id={painel_id}, source={source})",
            customer["id"], "success", result,
        )

        # Compute new expiration string (best-effort — supports several shapes)
        new_expires = (
            result.get("expires_at") or result.get("expiration")
            or result.get("exp_date_iso") or result.get("exp_date") or ""
        )
        # If painel returned Unix timestamp, convert for display
        if isinstance(new_expires, (int, float)):
            try:
                from datetime import datetime as _dt, timezone as _tz
                new_expires = _dt.fromtimestamp(int(new_expires), tz=_tz.utc).strftime("%d/%m/%Y")
            except Exception:
                new_expires = str(new_expires)

        # Notify client via WhatsApp — this is what the customer sees ("Renovação confirmada")
        try:
            from services.notifier import send_notification
            phone = customer.get("whatsapp") or ""
            if phone:
                notified = await send_notification(
                    "renewal_success", phone,
                    {
                        "name": customer["name"],
                        "plan_months": payment["plan_months"],
                        "new_expires_at": new_expires,
                        "system_type": customer.get("system_type") or "",
                    },
                )
                if notified:
                    await save_message(phone, "renewal_confirmed", "out", customer["id"])
                    logger.info("Renewal confirmation sent to %s", phone)
                else:
                    logger.warning("Renewal template disabled/missing — no message sent to %s", phone)
            else:
                logger.warning("No whatsapp on customer %s — skipping renewal notification", customer["id"])
        except Exception:
            logger.exception("Post-renewal notification failed (non-fatal)")

        # Mirror payment update to MongoDB Atlas
        try:
            from services import mongo_store
            await mongo_store.upsert_payment({
                "_id": payment["id"],
                "status": "renewed",
                "paid_at": now_iso(),
                "renewed_at": now_iso(),
                "painel_id": painel_id,
                "new_expires_at": new_expires,
                "package_id": payment["package_id"],
                "plan_months": payment["plan_months"],
                "customer_id": customer["id"],
                "customer_name": customer["name"],
                "source": source,
                "raw_renewal_response": result if isinstance(result, dict) else {},
            })
            # Also update the customer's expiration in Mongo
            if painel_id and new_expires:
                await mongo_store.upsert_customer({
                    "_id": painel_id,
                    "exp_date_iso": new_expires,
                    "last_renewed_at": now_iso(),
                })
        except Exception:
            logger.exception("Failed to mirror renewal to MongoDB (non-fatal)")

        return {"ok": True, "status": "renewed", "payment_id": payment["id"], "painel_id": painel_id, "result": result}
    except Exception as e:
        logger.exception("Renewal painel call failed for payment %s", payment["id"])
        await log_activity(
            "renewal_error",
            f"{customer['name']}: {e}",
            customer["id"], "error",
        )
        # Mirror the failure to Mongo too
        try:
            from services import mongo_store
            await mongo_store.upsert_payment({
                "_id": payment["id"],
                "status": "paid_renewal_failed",
                "paid_at": now_iso(),
                "renewal_error": str(e),
                "painel_id": painel_id,
            })
        except Exception:
            pass
        return {"ok": False, "status": "renewal_failed", "payment_id": payment["id"], "error": str(e)}


@router.post("/reprocess/{payment_id}")
async def reprocess_payment(payment_id: str, request: Request):
    """Admin: manually re-trigger renewal for a payment whose webhook didn't arrive
    or whose renewal failed. Idempotent: if already renewed, returns success."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
        payment = await cur.fetchone()
        if not payment:
            raise HTTPException(404, f"Payment {payment_id} not found")
        payment = dict(payment)

    # Force-mark as paid if admin says so (manual override)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        pass
    force_paid = bool(payload.get("force_paid", True))

    return await _process_payment_confirmation(
        payment["order_nsu"], paid=force_paid,
        source="admin_reprocess",
        raw={"admin": True, "payment_id": payment_id},
    )


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
