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
            webhook_url=await infinitepay.build_webhook_url(public_base),
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
    order_nsu = f"renew-{payload.customer_id}-{payload.plan_months}m"
    payment_id = new_id()
    # Per-payment secret used by /pay/{id}?ok=1&t=<token> to prove that the
    # browser actually returned from the InfinitePay checkout that we
    # ourselves created. Prevents attackers from POSTing to
    # /check-status/{customer_id} with a forged Referer.
    import secrets
    confirmation_token = secrets.token_urlsafe(24)

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
            redirect_url=f"{public_base}/pay/{payload.customer_id}?ok=1&t={confirmation_token}",
            webhook_url=await infinitepay.build_webhook_url(public_base),
            customer_name=painel_username or None,
            customer_phone=None,
        )
    except Exception as e:
        raise HTTPException(502, f"InfinitePay error: {e}")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO payments (id, customer_id, plan_months, amount_cents, package_id, status, infinitepay_url, order_nsu, confirmation_token, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
            (payment_id, payload.customer_id, payload.plan_months, amount, package_id,
             link_data.get("url"), order_nsu, confirmation_token, now_iso()),
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

    Real InfinitePay Checkout webhook payload (from docs @ infinitepay.io/checkout):
        {
          "invoice_slug": "...", "amount": 3500, "paid_amount": 3535,
          "installments": 1, "capture_method": "credit_card",
          "transaction_nsu": "UUID...", "order_nsu": "renew-228116806-1m",
          "receipt_url": "...", "items": [...]
        }
    IMPORTANT: this payload has NO `paid`/`status`/`event` field. The mere
    fact that InfinitePay fired the webhook IS the confirmation — they only
    call it after successful capture. We treat presence of `transaction_nsu`
    (and non-zero `paid_amount` when provided) as proof of paid=true.

    Optional origin check: if `infinitepay_webhook_secret` is set in settings,
    we require the same value on the URL as `?s=<secret>` (embedded in the
    webhook_url when the link was created). This blocks forged calls to
    /api/payments/webhook from random attackers.
    """
    body = await request.json()
    logger.info("InfinitePay webhook received: %s", body)
    # Also log headers to help debug missing webhooks
    hdrs = {k: v for k, v in request.headers.items()
            if k.lower() in ("user-agent", "referer", "origin", "x-forwarded-for",
                             "x-real-ip", "content-type", "x-webhook-signature")}
    logger.info("InfinitePay webhook headers: %s", hdrs)

    # Optional shared-secret origin check via ?s=<secret> query param
    expected_secret = (await get_setting("infinitepay_webhook_secret", "")).strip()
    if expected_secret:
        provided = str(request.query_params.get("s") or "").strip()
        import secrets as _secrets
        if not provided or not _secrets.compare_digest(expected_secret, provided):
            logger.warning("InfinitePay webhook rejected: bad/missing ?s= secret")
            return {"ok": False, "error": "bad_secret"}

    # Try multiple field name variations for the order id
    order_nsu = (body.get("order_nsu") or body.get("orderNsu")
                 or body.get("reference") or body.get("external_reference")
                 or body.get("external_order_nsu") or body.get("nsu"))

    # Detect "paid". Strategy in priority order:
    # 1) Real InfinitePay Checkout signature: `transaction_nsu` present AND
    #    (`paid_amount`>0 OR no paid_amount field but capture_method set) →
    #    InfinitePay only fires this webhook after captured payments.
    # 2) Legacy/other formats we've seen in the wild: paid=True, status=paid,
    #    payment_status=approved, event=payment.approved, etc.
    paid_amount = body.get("paid_amount")
    try:
        paid_amount_int = int(paid_amount) if paid_amount is not None else None
    except (ValueError, TypeError):
        paid_amount_int = None

    is_infinitepay_capture = bool(
        body.get("transaction_nsu")
        and (
            (paid_amount_int is not None and paid_amount_int > 0)
            or body.get("capture_method")
            or body.get("invoice_slug")
        )
    )
    paid = (
        is_infinitepay_capture
        or body.get("paid") is True
        or body.get("status") in ("paid", "approved", "PAID", "APPROVED", "completed", "captured")
        or body.get("payment_status") in ("approved", "paid", "APPROVED", "PAID", "captured")
        or body.get("event") in ("payment.approved", "checkout.paid", "transaction.captured")
    )

    if not order_nsu:
        logger.warning("InfinitePay webhook missing order_nsu — full body: %s", body)
        return {"ok": False, "error": "missing order_nsu", "received": body}

    logger.info(
        "InfinitePay webhook parsed: order_nsu=%s paid=%s (transaction_nsu=%s paid_amount=%s)",
        order_nsu, paid, body.get("transaction_nsu"), paid_amount,
    )
    result = await _process_payment_confirmation(str(order_nsu), paid=paid, source="webhook", raw=body)
    return result


async def _process_payment_confirmation(order_nsu: str, paid: bool, source: str = "webhook", raw: dict = None):
    """Shared logic: mark payment paid + call painel renew_user + notify client.

    Used by both /webhook (InfinitePay callback) and /reprocess/{payment_id}
    (admin manual re-trigger when webhook didn't arrive).

    Idempotency: keyed by `transaction_nsu` (unique per InfinitePay capture),
    NOT by `order_nsu`. This means the same checkout link can be paid multiple
    times and each capture triggers a fresh renewal — a client paying twice
    gets two months added. If the InfinitePay payload doesn't include a
    `transaction_nsu` (rare/legacy), we fall back to `order_nsu` as the
    idempotency key.
    """
    raw = raw or {}
    transaction_nsu = str(raw.get("transaction_nsu") or "").strip()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # First — if transaction_nsu was already processed, we're idempotent.
        if transaction_nsu:
            cur = await db.execute(
                "SELECT * FROM payments WHERE transaction_nsu = ? LIMIT 1",
                (transaction_nsu,),
            )
            already = await cur.fetchone()
            if already:
                logger.info(
                    "transaction_nsu=%s already processed as payment=%s → idempotent",
                    transaction_nsu, already["id"],
                )
                return {"ok": True, "status": "already_processed",
                        "payment_id": already["id"], "idempotent_by": "transaction_nsu"}
        # Otherwise look up the original pending payment for this order_nsu.
        cur = await db.execute(
            "SELECT * FROM payments WHERE order_nsu = ? ORDER BY created_at DESC LIMIT 1",
            (order_nsu,),
        )
        payment_row = await cur.fetchone()
        if not payment_row:
            logger.warning("Payment not found for order_nsu=%s (source=%s)", order_nsu, source)
            return {"ok": False, "error": "payment not found", "order_nsu": order_nsu}
        payment = dict(payment_row)

    if not paid:
        return {"ok": True, "status": "not_paid", "payment_id": payment["id"]}

    # If the original payment row is already marked paid AND we got a NEW
    # transaction_nsu, this is a subsequent capture on the same checkout link.
    # Clone the payment row so we track each capture independently and can
    # renew the client again.
    if payment["status"] == "paid":
        if transaction_nsu and transaction_nsu != (payment.get("transaction_nsu") or ""):
            new_id_val = new_id()
            receipt_url = str(raw.get("receipt_url") or "").strip()
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
                    " package_id, status, infinitepay_url, order_nsu, confirmation_token,"
                    " transaction_nsu, receipt_url, paid_at, created_at) VALUES (?, ?, ?, ?, ?, 'paid', ?, ?, ?, ?, ?, ?, ?)",
                    (new_id_val, payment["customer_id"], payment["plan_months"],
                     payment["amount_cents"], payment["package_id"],
                     payment.get("infinitepay_url"), order_nsu,
                     payment.get("confirmation_token"),
                     transaction_nsu, receipt_url or None,
                     now_iso(), now_iso()),
                )
                await db.commit()
            payment["id"] = new_id_val
            payment["status"] = "paid"
            payment["transaction_nsu"] = transaction_nsu
            payment["receipt_url"] = receipt_url
            logger.info(
                "New capture on existing link (order_nsu=%s) → cloned payment=%s "
                "(transaction_nsu=%s) — will renew again",
                order_nsu, new_id_val, transaction_nsu,
            )
        else:
            # Same transaction (or no transaction_nsu at all) → already handled.
            return {"ok": True, "status": "already_processed",
                    "payment_id": payment["id"], "idempotent_by": "order_nsu"}
    else:
        # First-time confirmation for this pending payment: mark paid + store txn.
        receipt_url = str(raw.get("receipt_url") or "").strip()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE payments SET status = 'paid', paid_at = ?, "
                "transaction_nsu = COALESCE(NULLIF(?, ''), transaction_nsu), "
                "receipt_url = COALESCE(NULLIF(?, ''), receipt_url) "
                "WHERE id = ?",
                (now_iso(), transaction_nsu, receipt_url, payment["id"]),
            )
            await db.commit()
        payment["transaction_nsu"] = transaction_nsu or payment.get("transaction_nsu")
        payment["receipt_url"] = receipt_url or payment.get("receipt_url")

    # Resolve customer info + painel_id
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM customers WHERE id = ?", (payment["customer_id"],))
        customer_row = await cur.fetchone()
        customer = dict(customer_row) if customer_row else {"id": payment["customer_id"], "name": "?", "whatsapp": "", "system_type": ""}

    # If customer info is missing (e.g. legacy customer only in Mongo), fill from Mongo
    if not customer.get("whatsapp") or not customer.get("name") or customer.get("name") in ("?", "cliente", "Cliente"):
        try:
            from services import mongo_store
            mongo_doc = await mongo_store.find_customer_by_painel_id(str(payment["customer_id"]))
            if mongo_doc:
                if not customer.get("name") or customer.get("name") in ("?", "cliente", "Cliente"):
                    customer["name"] = (mongo_doc.get("full_name") or mongo_doc.get("name")
                                        or mongo_doc.get("username") or "")
                if not customer.get("whatsapp"):
                    customer["whatsapp"] = mongo_doc.get("whatsapp") or ""
                if not customer.get("system_type"):
                    customer["system_type"] = mongo_doc.get("system_type") or ""
        except Exception:
            logger.exception("Mongo lookup for customer fallback failed")

    # Final resolver — always ends up with the real name from painel.fun
    # cache when local/mongo don't have it. Never leaves "?", "cliente", "".
    if not customer.get("name") or customer.get("name") in ("?", "cliente", "Cliente"):
        try:
            from services.name_resolver import resolve_customer_name
            customer["name"] = await resolve_customer_name(
                str(payment["customer_id"]), fallback="cliente"
            )
        except Exception:
            logger.exception("resolve_customer_name failed for %s", payment["customer_id"])
            customer["name"] = customer.get("name") or "cliente"

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

    if not painel_id or not str(painel_id).isdigit():
        await log_activity(
            "renewal_pending",
            f"Pagamento confirmado ({source}) mas painel_id não encontrado — renovar manualmente para {customer['name']}",
            customer["id"], "warning", raw or {},
        )
        # Alert admin — a payment came in but we need manual action.
        try:
            from services.notifier import send_admin_alert
            amount_brl = f"R$ {payment['amount_cents']/100:.2f}".replace(".", ",")
            await send_admin_alert(
                "⚠️ *Pagamento recebido — renovar manualmente*\n\n"
                f"👤 Cliente: {customer['name']}\n"
                f"📱 WhatsApp: {customer.get('whatsapp') or '-'}\n"
                f"📦 {payment['plan_months']} mês(es) | {amount_brl}\n"
                f"🛰️ Origem: {source}\n\n"
                "Não consegui identificar o `painel_id` para renovar automaticamente. "
                "Renove esse cliente pelo painel.fun."
            )
        except Exception:
            logger.exception("Admin alert (paid_no_painel_id) failed")
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
        # If painel returned ISO string like "2027-01-01" or "2027-01-01T00:00:00Z",
        # convert to Brazilian dd/mm/aaaa for the WhatsApp message.
        elif isinstance(new_expires, str) and new_expires:
            try:
                from datetime import datetime as _dt
                s = new_expires.replace("Z", "+00:00")
                # Accept both "2027-01-01" and full ISO
                fmt = "%Y-%m-%dT%H:%M:%S%z" if "T" in s else "%Y-%m-%d"
                dt = _dt.strptime(s, fmt) if "T" in s else _dt.strptime(s, fmt)
                new_expires = dt.strftime("%d/%m/%Y")
            except Exception:
                # Keep the original string — better than empty
                pass

        # Last-resort fallback: painel gave us nothing usable → compute locally
        # from the customer's current expires_at + plan_months. Client message
        # must NEVER show "ativo até " with an empty date.
        if not new_expires:
            try:
                from datetime import datetime as _dt, timezone as _tz
                base_expires = None
                cur_exp = (customer.get("expires_at") or "").strip()
                if cur_exp:
                    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
                        try:
                            base_expires = _dt.strptime(cur_exp.replace("Z", "+00:00"), fmt)
                            break
                        except Exception:
                            continue
                if base_expires is None or base_expires < _dt.now(_tz.utc).replace(tzinfo=None):
                    # Expired or unknown → count from today
                    base_expires = _dt.now(_tz.utc).replace(tzinfo=None)
                # Add plan_months (each = 30 days for a simple, predictable result)
                from datetime import timedelta as _td
                projected = base_expires + _td(days=30 * int(payment["plan_months"]))
                new_expires = projected.strftime("%d/%m/%Y")
                logger.info(
                    "painel didn't return expires_at — projected locally: %s (base=%s + %sm)",
                    new_expires, base_expires.date(), payment["plan_months"],
                )
            except Exception:
                logger.exception("Local expiration projection failed — leaving empty")

        # Notify client via WhatsApp — this is what the customer sees ("Renovação confirmada")
        try:
            from services.notifier import send_notification, send_admin_alert
            # Resolve client phone with cascading fallbacks: SQLite → Mongo → painel.fun cache.
            # This is the same cascade used to create the payment link, so if the client
            # was reachable at that moment, we can reach them now.
            phone = (customer.get("whatsapp") or "").strip()
            if not phone:
                try:
                    from services import mongo_store
                    mdoc = await mongo_store.find_customer_by_painel_id(str(customer["id"]))
                    if mdoc:
                        phone = (mdoc.get("whatsapp") or "").strip()
                except Exception:
                    logger.exception("Mongo phone-fallback lookup failed")
            if not phone:
                try:
                    from routers.painel_users import _read_cache
                    from services.phone_extractor import extract_whatsapp
                    users, _meta = await _read_cache()
                    for u in users:
                        uid = str(u.get("id") or u.get("user_id") or u.get("username") or "")
                        if uid == str(customer["id"]) or uid == str(painel_id):
                            phone = (extract_whatsapp(u) or "").strip()
                            if phone:
                                # Persist so next time it's instant.
                                async with aiosqlite.connect(DB_PATH) as db:
                                    await db.execute(
                                        "UPDATE customers SET whatsapp = ?, updated_at = ? WHERE id = ?",
                                        (phone, now_iso(), customer["id"]),
                                    )
                                    await db.commit()
                                customer["whatsapp"] = phone
                                logger.info("Resolved phone from painel cache for %s: %s",
                                            customer["id"], phone)
                            break
                except Exception:
                    logger.exception("Painel-cache phone-fallback failed")

            client_notified = False
            fallback_msg_sent = False
            if phone:
                client_notified = await send_notification(
                    "renewal_success", phone,
                    {
                        "name": customer["name"],
                        "plan_months": payment["plan_months"],
                        "new_expires_at": new_expires,
                        "system_type": customer.get("system_type") or "",
                    },
                    customer_id=customer["id"],
                )
                if client_notified:
                    await save_message(phone, "renewal_confirmed", "out", customer["id"])
                    logger.info("Renewal confirmation sent to %s", phone)
                else:
                    # Template `renewal_success` is missing/disabled → send a minimal
                    # hardcoded confirmation so the client never stays in the dark.
                    # Uses the delivery queue too (auto-retry every 10s).
                    logger.warning(
                        "renewal_success template disabled/missing — sending hardcoded fallback to %s",
                        phone,
                    )
                    try:
                        from services.notifier import send_hardcoded
                        expires_txt = f" até {new_expires}" if new_expires else ""
                        fallback_msg_sent = await send_hardcoded(
                            phone,
                            f"✅ Pagamento confirmado, {customer['name']}!\n\n"
                            f"Seu plano foi renovado por {payment['plan_months']} mês(es){expires_txt}. 🎉\n\n"
                            "Obrigado pela preferência!",
                            event_key="renewal_success_fallback",
                            customer_id=customer["id"],
                        )
                        if fallback_msg_sent:
                            await save_message(phone, "renewal_confirmed_fallback", "out", customer["id"])
                    except Exception:
                        logger.exception("Fallback renewal message failed for %s", phone)
            else:
                logger.warning("No whatsapp on customer %s — skipping renewal notification", customer["id"])

            # Also alert the admin/owner so they know a payment just came in.
            # Fire-and-forget: no-op when `admin_whatsapp` setting is empty.
            try:
                amount_brl = f"R$ {payment['amount_cents']/100:.2f}".replace(".", ",")
                if client_notified:
                    notify_status = "sim (template)"
                elif fallback_msg_sent:
                    notify_status = "sim (mensagem padrão — template desabilitado)"
                elif phone:
                    notify_status = "❌ falhou (WhatsApp indisponível)"
                else:
                    notify_status = "❌ falhou (sem número no cadastro)"
                admin_msg = (
                    "💰 *Pagamento confirmado*\n\n"
                    f"👤 Cliente: {customer['name']}\n"
                    f"📱 WhatsApp: {phone or '-'}\n"
                    f"📦 Plano: {payment['plan_months']} mês(es)  |  {amount_brl}\n"
                    f"🎯 Sistema: {(customer.get('system_type') or '-').upper()}\n"
                    f"🔗 Painel ID: {painel_id}\n"
                    f"📆 Novo vencimento: {new_expires or '-'}\n"
                    f"🛰️ Origem: {source}\n"
                    f"✉️ Cliente notificado: {notify_status}"
                )
                await send_admin_alert(admin_msg)
            except Exception:
                logger.exception("Admin alert failed (non-fatal)")
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
        # Alert admin — the customer paid but painel.fun refused/errored on renewal.
        try:
            from services.notifier import send_admin_alert
            amount_brl = f"R$ {payment['amount_cents']/100:.2f}".replace(".", ",")
            await send_admin_alert(
                "❌ *Renovação FALHOU no painel.fun*\n\n"
                f"👤 Cliente: {customer['name']}\n"
                f"📱 WhatsApp: {customer.get('whatsapp') or '-'}\n"
                f"📦 {payment['plan_months']} mês(es) | {amount_brl}\n"
                f"🔗 Painel ID: {painel_id}\n"
                f"🛰️ Origem: {source}\n\n"
                f"Erro: {str(e)[:200]}\n\n"
                "O pagamento foi recebido — renove esse cliente manualmente no painel."
            )
        except Exception:
            logger.exception("Admin alert (renewal_failed) failed")
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


@router.post("/resend-notification/{payment_id}")
async def resend_notification(payment_id: str):
    """Admin: re-send the "renewal confirmed" message to the client for a
    payment that was already renewed. Returns a DETAILED diagnostic so the
    admin knows exactly why the original notification didn't arrive.

    Never re-triggers the panel renewal — this is purely a message resend.
    Useful when the client claims they didn't receive the confirmation.
    """
    from services.notifier import send_notification
    from services import mongo_store
    from routers.painel_users import _read_cache
    from services.phone_extractor import extract_whatsapp

    diag = {"payment_id": payment_id, "steps": []}

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT p.*, c.name as customer_name, c.whatsapp as customer_whatsapp,"
            " c.system_type as customer_system_type"
            " FROM payments p LEFT JOIN customers c ON c.id = p.customer_id"
            " WHERE p.id = ?",
            (payment_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, f"Payment {payment_id} not found")
        pmt = dict(row)

    diag["customer_id"] = pmt["customer_id"]
    diag["customer_name"] = pmt["customer_name"]
    diag["payment_status"] = pmt["status"]
    diag["order_nsu"] = pmt["order_nsu"]

    if pmt["status"] != "paid":
        diag["result"] = "not_sent"
        diag["reason"] = f"payment status is '{pmt['status']}' (need 'paid')"
        return diag

    # Resolve phone with the same cascade _process_payment_confirmation uses.
    phone = (pmt.get("customer_whatsapp") or "").strip()
    diag["steps"].append({"source": "sqlite_customers", "phone": phone or None})

    if not phone:
        try:
            mdoc = await mongo_store.find_customer_by_painel_id(str(pmt["customer_id"]))
            phone = (mdoc.get("whatsapp") if mdoc else "" or "").strip()
            diag["steps"].append({"source": "mongo", "phone": phone or None})
        except Exception as e:
            diag["steps"].append({"source": "mongo", "error": str(e)})

    if not phone:
        try:
            users, _ = await _read_cache()
            for u in users:
                uid = str(u.get("id") or u.get("user_id") or u.get("username") or "")
                if uid == str(pmt["customer_id"]):
                    phone = (extract_whatsapp(u) or "").strip()
                    break
            diag["steps"].append({"source": "painel_cache", "phone": phone or None})
        except Exception as e:
            diag["steps"].append({"source": "painel_cache", "error": str(e)})

    if not phone:
        diag["result"] = "not_sent"
        diag["reason"] = "no whatsapp resolved from any source (SQLite/Mongo/painel cache)"
        return diag

    diag["resolved_phone"] = phone

    # Persist so future notifications are instant
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE customers SET whatsapp = ?, updated_at = ? WHERE id = ?",
                         (phone, now_iso(), pmt["customer_id"]))
        await db.commit()

    # WA service status
    wa_status = await whatsapp_client.get_status()
    diag["wa_service"] = {"ready": wa_status.get("ready"), "state": wa_status.get("state")}
    if not wa_status.get("ready"):
        diag["result"] = "not_sent"
        diag["reason"] = f"whatsapp service not ready (state={wa_status.get('state')})"
        return diag

    # Best-effort: fetch the CURRENT expires_at from the painel cache so the
    # message shows the real "active until" date (not blank).
    new_expires_at = ""
    try:
        from routers.painel_users import _read_cache
        from services.expiration import compute_expiration_info
        from datetime import datetime as _dt
        users, _ = await _read_cache()
        for u in users:
            uid = str(u.get("id") or u.get("user_id") or u.get("username") or "")
            if uid == str(pmt["customer_id"]):
                info = compute_expiration_info(u)
                iso = info.get("expires_at_iso")
                if iso:
                    try:
                        new_expires_at = _dt.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d/%m/%Y")
                    except Exception:
                        new_expires_at = iso
                break
    except Exception:
        pass

    # Try the template first; if disabled/missing, send hardcoded fallback.
    ok = await send_notification(
        "renewal_success", phone,
        {
            "name": pmt["customer_name"] or "",
            "plan_months": pmt["plan_months"],
            "new_expires_at": new_expires_at,
            "system_type": pmt["customer_system_type"] or "",
        },
    )
    if ok:
        await save_message(phone, "renewal_confirmed_manual", "out", pmt["customer_id"])
        diag["result"] = "sent"
        diag["method"] = "template"
        return diag

    # Fallback hardcoded
    try:
        await whatsapp_client.send_message(
            phone,
            f"✅ Pagamento confirmado, {pmt['customer_name'] or 'cliente'}!\n\n"
            f"Seu plano foi renovado por {pmt['plan_months']} mês(es). 🎉\n\n"
            "Obrigado pela preferência!"
        )
        await save_message(phone, "renewal_confirmed_manual_fallback", "out", pmt["customer_id"])
        diag["result"] = "sent"
        diag["method"] = "hardcoded_fallback"
        diag["note"] = "template 'renewal_success' is disabled or empty"
        return diag
    except Exception as e:
        diag["result"] = "not_sent"
        diag["reason"] = f"whatsapp send failed: {e}"
        return diag


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


@router.get("/diagnostics")
async def payments_diagnostics():
    """Admin diagnostic snapshot: reveals *why* recent payments may not have
    fired the confirmation flow. Read-only.

    Returns: settings health (admin_whatsapp/public_base_url), pending vs
    paid counts, last 10 payments with resolved customer/phone/status, and
    template `renewal_success` enabled state.
    """
    admin_wa = (await get_setting("admin_whatsapp") or "").strip()
    public_base = (await get_setting("public_base_url") or "").strip()
    handle = (await get_setting("infinitepay_handle") or "").strip()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Template health
        cur = await db.execute(
            "SELECT enabled, LENGTH(body) as body_len FROM notification_templates "
            "WHERE event_key = 'renewal_success'"
        )
        tpl_row = await cur.fetchone()
        tpl = dict(tpl_row) if tpl_row else None

        cur = await db.execute("SELECT status, COUNT(*) as c FROM payments GROUP BY status")
        by_status = {r["status"]: r["c"] for r in await cur.fetchall()}

        cur = await db.execute(
            "SELECT p.id, p.customer_id, p.order_nsu, p.transaction_nsu, p.status,"
            " p.plan_months, p.amount_cents, p.paid_at, p.created_at,"
            " c.name as customer_name, c.whatsapp as customer_whatsapp"
            " FROM payments p LEFT JOIN customers c ON c.id = p.customer_id"
            " ORDER BY p.created_at DESC LIMIT 10"
        )
        recent = [dict(r) for r in await cur.fetchall()]

    return {
        "settings_health": {
            "admin_whatsapp_configured": bool(admin_wa),
            "admin_whatsapp_masked": (admin_wa[:4] + "***" + admin_wa[-2:]) if admin_wa else "",
            "public_base_url": public_base,
            "public_base_url_ok": public_base.startswith("http"),
            "infinitepay_handle_configured": bool(handle),
        },
        "renewal_template": {
            "exists": tpl is not None,
            "enabled": bool(tpl and tpl["enabled"]),
            "body_length": tpl["body_len"] if tpl else 0,
        },
        "payment_counts_by_status": by_status,
        "recent_payments": recent,
        "hint": (
            "Se admin_whatsapp_configured=false → configure em Configurações → 'Admin — Seu WhatsApp'. "
            "Se public_base_url não é HTTPS público → InfinitePay não consegue chamar o webhook. "
            "Se renewal_template.enabled=false → cliente recebe apenas mensagem hardcoded."
        ),
    }


@router.post("/check-status/{customer_id}")
async def check_status_by_customer(customer_id: str, request: Request):
    """PUBLIC: called by /pay/{id}?ok=1&t=<token> after customer returns
    from InfinitePay. Multi-strategy confirmation:

    Strategy 1 (payment_check): query InfinitePay via `check_payment`.
                Only accepts if `paid is True` (strict).
    Strategy 2 (signed redirect trust): if body has a `token` matching
                the payment's `confirmation_token` (generated when the
                InfinitePay link was created and embedded in redirect_url
                as ?t=), we accept the redirect as payment confirmation.
                InfinitePay only redirects after successful capture, so
                the presence of our secret token in the URL is strong
                proof — attacker cannot forge because they don't know the
                per-payment secret.

    Either strategy → renewal fires. Idempotent (won't re-renew).
    """
    from services import infinitepay
    from datetime import datetime, timezone, timedelta

    body = {}
    try: body = await request.json()
    except Exception: pass
    provided_token = str(body.get("token") or body.get("t") or "").strip()

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, order_nsu, infinitepay_url, confirmation_token, created_at "
            "FROM payments WHERE customer_id = ? AND status = 'pending' AND created_at >= ? "
            "ORDER BY created_at DESC LIMIT 5",
            (str(customer_id), cutoff),
        )
        pendings = [dict(r) for r in await cur.fetchall()]

    if not pendings:
        return {"ok": True, "status": "no_pending", "checked": 0}

    # Strategy 1: InfinitePay official /payment_check (strict)
    for pmt in pendings:
        try:
            check = await infinitepay.check_payment(pmt["order_nsu"])
            if check.get("paid") is True:
                proc = await _process_payment_confirmation(
                    pmt["order_nsu"], paid=True, source="pay_page_return", raw=check,
                )
                return {"ok": True, "status": proc.get("status"), "payment_id": pmt["id"],
                        "strategy": "payment_check", "checked": len(pendings)}
        except Exception as e:
            logger.exception("payment_check failed for %s: %s", pmt["order_nsu"], e)

    # Strategy 2: SIGNED redirect trust — only accepts payments whose stored
    # confirmation_token matches the token provided by the client. Since the
    # token was embedded in the InfinitePay redirect_url and only InfinitePay
    # sends the browser back after successful capture, presenting a matching
    # token proves the redirect really came from a successful checkout.
    import secrets as _secrets
    if provided_token:
        for pmt in pendings:
            stored = (pmt.get("confirmation_token") or "")
            if stored and _secrets.compare_digest(stored, provided_token):
                logger.info("Signed redirect trust confirmed for %s (token match)",
                            pmt["order_nsu"])
                proc = await _process_payment_confirmation(
                    pmt["order_nsu"], paid=True, source="signed_redirect",
                    raw={"token_matched": True},
                )
                return {"ok": True, "status": proc.get("status"), "payment_id": pmt["id"],
                        "strategy": "signed_redirect", "checked": len(pendings)}

    return {"ok": True, "status": "still_pending", "checked": len(pendings),
            "hint": "InfinitePay ainda não confirmou. Se você pagou, a confirmação chega em alguns minutos."}


@router.post("/poll-now")
async def trigger_poll_now(request: Request):
    """Admin: force one immediate sweep of pending payments (dev/debug convenience)."""
    from services.payment_poller import check_pending_once
    return await check_pending_once()


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

    # If we resolved to a generic name, try harder — never show "Cliente"
    # or the raw painel_id when a real name exists in another source.
    if not customer.get("name") or customer["name"] in ("Cliente", "cliente"):
        try:
            from services.name_resolver import resolve_customer_name
            better = await resolve_customer_name(str(customer["id"]), fallback="")
            if better:
                customer["name"] = better
        except Exception:
            pass

    # Fetch prices for all 4 plans
    prices = {}
    for m in (1, 3, 6, 12):
        v = await get_setting(f"plan_price_{m}m", "35,00")
        try:
            prices[m] = int(round(float(v.replace(",", ".").strip()) * 100))
        except ValueError:
            prices[m] = 3500

    # Recent payments (last 10) — with receipts. Shown on /pay/{id} so the
    # client always sees their own history and proof-of-payment.
    # Backfill: for paid payments missing `receipt_url`, try InfinitePay's
    # /payment_check to fetch it now (in-page) so the client sees the
    # comprovante immediately even for older captures.
    payments_history = []
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, plan_months, amount_cents, status, paid_at, created_at,"
                " receipt_url, infinitepay_url, order_nsu, transaction_nsu"
                " FROM payments WHERE customer_id = ?"
                " ORDER BY created_at DESC LIMIT 10",
                (customer["id"],),
            )
            payments_history = [dict(r) for r in await cur.fetchall()]

        # Best-effort backfill of missing receipt_url for paid payments.
        # Non-blocking on failure — we always return whatever we already have.
        for p in payments_history:
            if p.get("status") == "paid" and not p.get("receipt_url") and p.get("order_nsu"):
                try:
                    from services import infinitepay
                    check = await infinitepay.check_payment(
                        p["order_nsu"], transaction_nsu=p.get("transaction_nsu"),
                    )
                    r_url = str(check.get("receipt_url") or "").strip()
                    if r_url:
                        p["receipt_url"] = r_url
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute(
                                "UPDATE payments SET receipt_url = ? WHERE id = ?",
                                (r_url, p["id"]),
                            )
                            await db.commit()
                except Exception:
                    logger.exception("receipt_url backfill failed for payment %s", p.get("id"))
    except Exception:
        logger.exception("Failed to load payments history for %s", customer["id"])

    # Recent WhatsApp messages this customer received from us (last 15).
    # Filtered to outgoing only — never expose incoming private chat back to
    # a public /pay/{id} page.
    messages_history = []
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, phone, message, direction, timestamp"
                " FROM messages"
                " WHERE customer_id = ? AND direction = 'out'"
                " ORDER BY timestamp DESC LIMIT 15",
                (customer["id"],),
            )
            messages_history = [dict(r) for r in await cur.fetchall()]
    except Exception:
        logger.exception("Failed to load messages history for %s", customer["id"])

    return {
        "customer": customer,
        "prices_cents": prices,
        "payments_history": payments_history,
        "messages_history": messages_history,
    }
