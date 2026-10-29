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


async def _cache_user(painel_id) -> dict:
    from routers.painel_users import _read_cache
    users, _ = await _read_cache()
    return next((u for u in users or [] if str(u.get("id") or u.get("user_id")) == str(painel_id)), None) or {}


def _has_adult(u: dict) -> bool:
    import json as _json
    raw = u.get("bouquet") or u.get("packages") or "[]"
    try:
        ids = _json.loads(raw) if isinstance(raw, str) else list(raw)
    except Exception:
        ids = []
    return painel.ADULT_BOUQUET_ID in [int(x) for x in ids if str(x).isdigit()]


async def _clover_vars(payment: dict) -> dict:
    if "clovers" not in payment and payment.get("id"):
        async with aiosqlite.connect(DB_PATH) as db:
            row = await (await db.execute("SELECT clovers FROM payments WHERE id = ?", (payment["id"],))).fetchone()
        payment = {**payment, "clovers": row[0] if row else 0}
    n = int(payment.get("clovers") or 0)
    coupons = []
    if n:
        try:
            from services.raffle import coupons_for_payment
            coupons = await coupons_for_payment(payment["id"])
        except Exception:
            logger.exception("clover coupons lookup failed")
    return {"clovers": n, "clover_coupons": ", ".join(f"#{c}" for c in coupons) if coupons else ("—" if not n else "")}


async def _public_raffle():
    from routers.raffle import raffle_public
    try:
        return await raffle_public()
    except Exception:
        logger.exception("raffle info failed")
        return {"enabled": False}


async def _linked_accounts(painel_id) -> list:
    """Other (non-trial) painel logins registered with the same WhatsApp number."""
    from routers.painel_users import _read_cache
    from services.phone_extractor import extract_whatsapp
    from services.expiration import compute_expiration_info
    users, _ = await _read_cache()
    main = next((u for u in users or [] if str(u.get("id") or u.get("user_id")) == str(painel_id)), None)
    phone = extract_whatsapp(main) if main else ""
    if not phone:
        return []
    out = []
    for u in users:
        uid = str(u.get("id") or u.get("user_id") or "")
        if uid == str(painel_id) or u.get("is_trial") or extract_whatsapp(u) != phone:
            continue
        from services.customer_prefs import price_for
        out.append({"id": uid, "login": u.get("username"),
                    "expires_at": compute_expiration_info(u).get("expires_at_iso"),
                    "prices": {m: await price_for(uid, m) for m in (1, 3, 6, 12)}})
    return out


async def _renew_extra_accounts(payment: dict, phone: str, source: str) -> list:
    """Renew the additional logins bought in the same checkout + notify each."""
    import json as _json
    try:
        extra_ids = _json.loads(payment.get("extra_customer_ids") or "[]")
    except Exception:
        extra_ids = []
    results = []
    adult = payment.get("adult_channels")
    for eid in extra_ids:
        try:
            res = await painel.renew_user(user_id=str(eid), package_id=payment["package_id"],
                                          months=payment.get("plan_months"),
                                          adult=None if adult is None else bool(adult))
            u = await _cache_user(eid)
            new_exp = res.get("exp_date") or res.get("expires_at") or ""
            if isinstance(new_exp, (int, float)):
                from datetime import datetime as _dt, timezone as _tz
                new_exp = _dt.fromtimestamp(int(new_exp), tz=_tz.utc).strftime("%d/%m/%Y")
            await log_activity("renewal_success", f"Renovação extra {payment['plan_months']}m (painel_id={eid}, source={source})",
                               str(eid), "success", res)
            if phone:
                from services.notifier import send_notification
                await send_notification("renewal_success", phone, {
                    "name": u.get("full_name") or u.get("username") or "cliente",
                    "user": u.get("username") or str(eid),
                    "password": u.get("password") or "",
                    "plan_months": payment["plan_months"],
                    "new_expires_at": new_exp,
                    "system_type": "",
                    **(await _clover_vars(payment)),
                }, customer_id=str(eid))
            results.append({"id": eid, "ok": True})
        except Exception as e:
            logger.exception("Extra renewal failed for %s", eid)
            results.append({"id": eid, "ok": False, "error": str(e)[:200]})
            try:
                from services.notifier import send_admin_alert
                await send_admin_alert(f"⚠️ *Renovação extra falhou*\n\nPainel ID: {eid}\nPagamento: {payment['id']}\nErro: {str(e)[:150]}\n\nRenove manualmente no painel.")
            except Exception:
                pass
    return results


@router.get("", response_model=List[Payment])
async def list_payments():
    """Admin list — enriched with `customer_login` (painel.fun username) and
    `customer_name` (real name), plus `receipt_url` for the Comprovante column.

    The `customer_login` cascade in the UI is: painel_username → id.
    Backfill of missing `receipt_url` for paid payments is best-effort via a
    single InfinitePay `check_payment` call per row (skipped on errors so the
    admin page always loads fast even when InfinitePay is slow).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT p.*, c.painel_username, c.name as customer_name"
            " FROM payments p LEFT JOIN customers c ON c.id = p.customer_id"
            " ORDER BY p.created_at DESC LIMIT 200"
        )
        rows = [dict(r) for r in await cur.fetchall()]

    # Backfill painel_username from the painel.fun cache for rows where it's
    # missing — this happens for customers auto-created via /pay/{id} public
    # link before we started persisting the username. Small in-memory index
    # so we only scan the cache once per request.
    missing_login = [r for r in rows if not r.get("painel_username")]
    if missing_login:
        try:
            from routers.painel_users import _read_cache
            users, _ = await _read_cache()
            by_id = {}
            for u in users:
                uid = str(u.get("id") or u.get("user_id") or u.get("username") or "")
                if uid:
                    by_id[uid] = u.get("username") or u.get("login") or ""
            async with aiosqlite.connect(DB_PATH) as db:
                for r in missing_login:
                    login = by_id.get(str(r["customer_id"]))
                    if login:
                        r["painel_username"] = login
                        await db.execute(
                            "UPDATE customers SET painel_username = ? WHERE id = ?",
                            (login, r["customer_id"]),
                        )
                await db.commit()
        except Exception:
            logger.exception("painel_username backfill failed")

    # Best-effort receipt_url backfill for paid rows missing it. We only
    # try the first 10 to keep the admin page snappy — subsequent visits
    # will fill in the rest.
    to_backfill = [r for r in rows if r["status"] == "paid" and not r.get("receipt_url") and r.get("order_nsu")]
    for r in to_backfill[:10]:
        try:
            check = await infinitepay.check_payment(
                r["order_nsu"], transaction_nsu=r.get("transaction_nsu"),
            )
            r_url = str(check.get("receipt_url") or "").strip()
            if r_url:
                r["receipt_url"] = r_url
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE payments SET receipt_url = ? WHERE id = ?",
                        (r_url, r["id"]),
                    )
                    await db.commit()
        except Exception:
            # Silent — non-critical enrichment
            pass

    return [
        Payment(
            **{k: v for k, v in r.items() if k in Payment.model_fields},
            customer_login=r.get("painel_username") or None,
        )
        for r in rows
    ]


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

    from services import customer_prefs
    fixed = (await customer_prefs.get_prefs(payload.customer_id)).get("fixed_plan")
    if fixed and int(fixed) != int(payload.plan_months):
        raise HTTPException(400, "Plano indisponível para este cliente")
    amount = await customer_prefs.price_for(payload.customer_id, payload.plan_months)
    original_amount = amount

    # Coupon (optional) — validates + applies discount. Cap 50%. Enforces
    # the "one coupon per customer per 28 days" rule via services/coupon.py.
    # We validate here at link creation to fail fast; the usage row is only
    # recorded on payment confirmation (services/coupon.record_usage).
    coupon_code_norm = ""
    coupon_id_final = ""
    coupon_percent = 0
    if getattr(payload, "coupon_code", None):
        from services.coupon import validate_coupon
        v = await validate_coupon(payload.coupon_code, str(payload.customer_id))
        if not v.get("valid"):
            raise HTTPException(400, v.get("reason") or "Cupom inválido")
        coupon_code_norm = v["code"]
        coupon_id_final = v["coupon_id"]
        coupon_percent = int(v["discount_percent"])

    # Apply same-day 7d discount if active. Coupon (when present) REPLACES
    # the 7d discount when it offers a bigger %. Simpler UX than stacking.
    from services.discount import get_active_discount, apply_discount
    discount = await get_active_discount(str(payload.customer_id))
    d7_percent = int(discount["percent"]) if discount else 0

    if coupon_percent >= d7_percent and coupon_percent > 0:
        discount_percent = coupon_percent
        amount = apply_discount(amount, discount_percent)
        logger.info(
            "Applied coupon %s for %s: %d%% (R$%.2f → R$%.2f)",
            coupon_code_norm, payload.customer_id, discount_percent,
            original_amount / 100, amount / 100,
        )
    elif d7_percent > 0:
        discount_percent = d7_percent
        amount = apply_discount(amount, discount_percent)
        logger.info(
            "Applied 7d same-day discount for %s: %d%% (R$%.2f → R$%.2f)",
            payload.customer_id, discount_percent,
            original_amount / 100, amount / 100,
        )
        # Coupon requested but its % was lower than the active auto-discount
        # → drop coupon so we don't record its usage on payment. Keeps the
        # 28-day cooldown fair (client didn't actually spend their coupon).
        if coupon_code_norm:
            logger.info(
                "Coupon %s ignored (7d discount %d%% > coupon %d%%)",
                coupon_code_norm, d7_percent, coupon_percent,
            )
            coupon_code_norm = ""
            coupon_id_final = ""
            coupon_percent = 0
    else:
        discount_percent = 0

    package_id = painel.get_package_id(customer["system_type"], payload.plan_months)

    # Multi-points: extra logins must share this customer's WhatsApp number.
    import json as _json
    extra_ids = []
    if payload.extra_customer_ids:
        allowed = {a["id"] for a in await _linked_accounts(payload.customer_id)}
        extra_ids = [str(x) for x in dict.fromkeys(payload.extra_customer_ids) if str(x) in allowed]
    points = 1 + len(extra_ids)
    # Each extra login pays its own (custom or default) price; it gets the same
    # discount % unless that login is blocked from discounts.
    for eid in extra_ids:
        e_price = await customer_prefs.price_for(eid, payload.plan_months)
        original_amount += e_price
        blocked = await customer_prefs.discount_blocked(eid)
        amount += apply_discount(e_price, 0 if blocked else discount_percent) if discount_percent else e_price

    from services import payment_accounts
    providers = await payment_accounts.enabled_providers()
    provider = payload.provider if payload.provider in providers else (providers[0] if providers else "infinitepay")
    account = await payment_accounts.pick_account(provider)
    clovers = 0
    from services import raffle as raffle_svc
    rcfg = await raffle_svc.config()
    if rcfg["enabled"] and payload.clovers:
        clovers = max(0, min(int(payload.clovers), rcfg["max_clovers"]))
        amount += clovers * rcfg["clover_cents"]
    if provider == "mercadopago":
        amount = payment_accounts.mp_amount(amount)

    public_base = await get_setting("public_base_url")
    payment_id = new_id()
    order_nsu = (f"mp-{payload.customer_id}-{payload.plan_months}m-{payment_id[:8]}" if provider == "mercadopago"
                 else f"renew-{payload.customer_id}-{payload.plan_months}m")
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

        description = f"Renovação {customer['system_type'].upper()} — {payload.plan_months} mês(es)" + (f" × {points} pontos" if points > 1 else "")
        if provider == "mercadopago":
            from services import mercadopago
            host = (public_base or "").split("://")[-1].split("/")[0] or "whatsflow.app"
            pix = await mercadopago.create_pix(
                account["access_token"], amount, description, external_reference=payment_id,
                payer_email=(await get_setting("mercadopago_payer_email") or "").strip() or f"cliente{payload.customer_id}@{host}",
                notification_url=f"{public_base}/api/payments/mp-webhook" if public_base else None,
            )
            link_data = {"url": pix.get("ticket_url"), **pix}
        else:
            link_data = await infinitepay.create_payment_link(
                order_nsu=order_nsu,
                amount_cents=amount,
                description=description,
                redirect_url=f"{public_base}/pay/{payload.customer_id}?ok=1&t={confirmation_token}",
                webhook_url=await infinitepay.build_webhook_url(public_base),
                customer_name=painel_username or None,
                customer_phone=None,
                handle=(account or {}).get("handle"),
            )
    except Exception as e:
        raise HTTPException(502, f"{'Mercado Pago' if provider == 'mercadopago' else 'InfinitePay'} error: {e}")

    # Sanitize/whitelist the attribution bucket. Values must be one of the
    # known reminder events or a short admin-supplied label — never an
    # arbitrary string from the URL (SQL/log injection guard).
    _ALLOWED_REFS = {
        "expiration_7d", "expiration_3d", "expiration_1d", "expiration_0d",
        "expired_1d", "expired_3d", "expired_7d",
        "trial_ready", "manual", "direct", "renewal_success",
    }
    ref_bucket = str(payload.ref or "").strip()[:32]
    if ref_bucket and ref_bucket not in _ALLOWED_REFS:
        ref_bucket = "other"
    if not ref_bucket:
        ref_bucket = "direct"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO payments (id, customer_id, plan_months, amount_cents, package_id, status, infinitepay_url, order_nsu, confirmation_token, discount_percent, original_amount_cents, ref_bucket, coupon_code, coupon_id, created_at,"
            " provider, account_id, extra_customer_ids, mp_payment_id, adult_channels, pix_qr_code, pix_qr_base64, pix_ticket_url, clovers)"
            " VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (payment_id, payload.customer_id, payload.plan_months, amount, package_id,
             link_data.get("url"), order_nsu, confirmation_token,
             discount_percent, original_amount, ref_bucket,
             coupon_code_norm or None, coupon_id_final or None, now_iso(),
             provider, (account or {}).get("id"), _json.dumps(extra_ids) if extra_ids else None,
             link_data.get("id") if provider == "mercadopago" else None,
             None if payload.adult_channels is None else int(bool(payload.adult_channels)),
             link_data.get("qr_code"), link_data.get("qr_code_base64"), link_data.get("ticket_url"), clovers),
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
        "provider": provider,
        "url": link_data.get("url"),
        "pix_qr_code": link_data.get("qr_code"),
        "pix_qr_base64": link_data.get("qr_code_base64"),
        "points": points,
        "clovers": clovers,
        "amount_cents": amount,
        "original_amount_cents": original_amount,
        "discount_percent": discount_percent,
        "coupon_code": coupon_code_norm or None,
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
    try:
        result = await _process_payment_confirmation(str(order_nsu), paid=paid, source="webhook", raw=body)
        logger.info(
            "🎯 WEBHOOK RESULT order_nsu=%s → %s",
            order_nsu, result,
        )
        return result
    except Exception as e:
        # NEVER return 5xx to InfinitePay — they will spam-retry indefinitely.
        # Log full context and return 200 so InfinitePay marks delivered;
        # the payment_poller / renewal_retry loops will pick up the slack.
        logger.exception(
            "💥 WEBHOOK CRASHED order_nsu=%s raw=%s → returning 200 to avoid retry storm",
            order_nsu, body,
        )
        return {"ok": False, "status": "webhook_crashed", "error": str(e)[:400]}


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
            # Trial-flow order_nsus ("trial-{painel_id}-{months}m") are
            # created directly at InfinitePay by services.bot when the client
            # takes the test — WITHOUT any local `payments` row. When that
            # link is later paid, the webhook fires with an order_nsu we've
            # never stored. Auto-create the row here so the normal renewal
            # + notification flow can proceed for these trial converts.
            if str(order_nsu).startswith("trial-"):
                logger.info(
                    "Trial webhook (order_nsu=%s) — auto-creating payment row "
                    "so we can renew + notify the client",
                    order_nsu,
                )
                painel_id = _extract_painel_id_from_nsu(order_nsu)
                parts = str(order_nsu).split("-")
                months_str = parts[2].rstrip("m") if len(parts) >= 3 else "1"
                try:
                    plan_months = int(months_str)
                except (TypeError, ValueError):
                    plan_months = 1

                # Locate the trial in our local trials table, then fill in
                # customer_id + system_type from there. If nothing found,
                # we still try to renew using the painel_id from order_nsu.
                trial_customer_id = ""
                trial_system_type = ""
                cur2 = await db.execute(
                    "SELECT customer_id, system_type FROM trials "
                    "WHERE trial_user_id = ? ORDER BY created_at DESC LIMIT 1",
                    (painel_id,),
                )
                trow = await cur2.fetchone()
                if trow:
                    trial_customer_id = trow["customer_id"] or ""
                    trial_system_type = trow["system_type"] or ""

                # Fallback: use painel_id as customer_id (matches renew flow
                # where the local customers row is auto-created keyed on the
                # painel id).
                customer_id_for_payment = trial_customer_id or painel_id or "unknown"

                # Package id — need system_type. If missing, default iptv.
                system_type_for_pkg = trial_system_type or "iptv"
                try:
                    package_id = painel.get_package_id(system_type_for_pkg, plan_months)
                except Exception:
                    package_id = 0

                # paid_amount from InfinitePay (already in cents in
                # transaction_nsu-bearing webhooks)
                amount_cents_from_raw = raw.get("paid_amount") or raw.get("amount") or 0
                try:
                    amount_cents_int = int(amount_cents_from_raw)
                except (TypeError, ValueError):
                    amount_cents_int = 0

                new_payment_id = new_id()
                await db.execute(
                    "INSERT INTO payments (id, customer_id, plan_months, "
                    "amount_cents, package_id, status, order_nsu, created_at) "
                    "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                    (new_payment_id, customer_id_for_payment, plan_months,
                     amount_cents_int, package_id, order_nsu, now_iso()),
                )
                await db.commit()

                # Re-read the row so downstream code has a proper dict.
                cur3 = await db.execute(
                    "SELECT * FROM payments WHERE id = ?", (new_payment_id,),
                )
                payment_row = await cur3.fetchone()
                logger.info(
                    "Trial payment auto-created: payment_id=%s customer_id=%s "
                    "painel_id=%s plan_months=%s system=%s",
                    new_payment_id, customer_id_for_payment, painel_id,
                    plan_months, system_type_for_pkg,
                )
            else:
                logger.warning("Payment not found for order_nsu=%s (source=%s)", order_nsu, source)
                return {"ok": False, "error": "payment not found", "order_nsu": order_nsu}
        payment = dict(payment_row)

    if not paid:
        logger.warning(
            "❌ WEBHOOK RECEIVED but paid=False → SKIP RENEWAL. "
            "payment=%s order_nsu=%s source=%s raw=%s",
            payment["id"], order_nsu, source, raw,
        )
        return {"ok": True, "status": "not_paid", "payment_id": payment["id"]}

    # If the original payment row is already marked paid AND we got a NEW
    # transaction_nsu, this is a subsequent capture on the same checkout link.
    # Clone the payment row so we track each capture independently and can
    # renew the client again.
    #
    # IMPORTANT: only clone when the existing row ALREADY has a stored
    # `transaction_nsu` different from the incoming one. If the stored value
    # is empty, this is not a new capture — it just means the previous
    # confirmation came through a non-webhook path (poller / pay-page return
    # / signed-redirect) which doesn't carry a transaction_nsu. In that case
    # we simply backfill the transaction_nsu on the existing row and return
    # idempotent, so we DO NOT re-notify the client or re-renew the plan.
    if payment["status"] == "paid":
        existing_txn = (payment.get("transaction_nsu") or "").strip()
        if transaction_nsu and existing_txn and transaction_nsu != existing_txn:
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
            # Same transaction, no incoming transaction_nsu, or existing row
            # has no stored transaction_nsu yet → already handled. Backfill
            # missing fields silently so future webhooks stay idempotent, but
            # DO NOT re-notify or re-renew.
            if transaction_nsu and not existing_txn:
                receipt_url = str(raw.get("receipt_url") or "").strip()
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE payments SET "
                        "transaction_nsu = ?, "
                        "receipt_url = COALESCE(NULLIF(?, ''), receipt_url) "
                        "WHERE id = ?",
                        (transaction_nsu, receipt_url, payment["id"]),
                    )
                    await db.commit()
                logger.info(
                    "Backfilled transaction_nsu=%s onto already-paid payment=%s "
                    "(previous confirmation via non-webhook path, no re-notify)",
                    transaction_nsu, payment["id"],
                )
            return {"ok": True, "status": "already_processed",
                    "payment_id": payment["id"], "idempotent_by": "order_nsu"}
    else:
        # First-time confirmation for this pending payment: mark paid + store txn.
        # Concurrency guard: use WHERE status='pending' so only ONE concurrent
        # caller flips the row. rowcount==0 means someone else already flipped
        # it → treat as already_processed and return without re-notifying.
        receipt_url = str(raw.get("receipt_url") or "").strip()
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "UPDATE payments SET status = 'paid', paid_at = ?, "
                "transaction_nsu = COALESCE(NULLIF(?, ''), transaction_nsu), "
                "receipt_url = COALESCE(NULLIF(?, ''), receipt_url) "
                "WHERE id = ? AND status = 'pending'",
                (now_iso(), transaction_nsu, receipt_url, payment["id"]),
            )
            await db.commit()
            if cur.rowcount == 0:
                logger.info(
                    "Race lost on payment=%s — another caller already flipped "
                    "status to paid. Returning idempotent (no re-notify).",
                    payment["id"],
                )
                return {"ok": True, "status": "already_processed",
                        "payment_id": payment["id"], "idempotent_by": "race_guard"}
        payment["status"] = "paid"
        payment["transaction_nsu"] = transaction_nsu or payment.get("transaction_nsu")
        payment["receipt_url"] = receipt_url or payment.get("receipt_url")

    # Record coupon usage (once) if this payment had a coupon applied.
    # Idempotent: `already_recorded_for_payment` guards against duplicate
    # inserts across webhook retries / poller re-runs.
    if payment.get("coupon_id") and payment.get("coupon_code"):
        try:
            from services.coupon import record_usage, already_recorded_for_payment
            if not await already_recorded_for_payment(payment["id"]):
                await record_usage(
                    coupon_id=payment["coupon_id"],
                    coupon_code=payment["coupon_code"],
                    customer_id=str(payment["customer_id"]),
                    payment_id=payment["id"],
                    phone="",  # filled below once we resolve customer
                    discount_percent=int(payment.get("discount_percent") or 0),
                    receipt_url=payment.get("receipt_url") or "",
                    painel_username="",
                )
                logger.info(
                    "Coupon usage recorded: coupon=%s customer=%s payment=%s",
                    payment["coupon_code"], payment["customer_id"], payment["id"],
                )
        except Exception:
            logger.exception("record_usage failed (non-fatal)")

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
    # Pre-init vars at outer scope so exception handlers can safely reference them
    # even if `painel.renew_user` throws before they get resolved inside the try.
    phone = ""
    painel_user = ""
    logger.info(
        "🔎 START RENEWAL payment=%s customer=%s painel_id=%s package_id=%s plan_months=%s source=%s",
        payment["id"], customer["id"], painel_id, payment["package_id"],
        payment["plan_months"], source,
    )
    try:
        adult_pref = payment.get("adult_channels")
        result = await painel.renew_user(
            user_id=painel_id,
            package_id=payment["package_id"],
            months=payment.get("plan_months"),
            adult=None if adult_pref is None else bool(adult_pref),
        )
        logger.info(
            "✅ PAINEL RENEWED payment=%s painel_id=%s result=%s",
            payment["id"], painel_id, str(result)[:400],
        )
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
                                # Persist so next time it's instant — BUT
                                # respect manual lock (admin edited it via
                                # Customers page → don't overwrite).
                                async with aiosqlite.connect(DB_PATH) as db:
                                    await db.execute(
                                        "UPDATE customers SET whatsapp = ?, updated_at = ? "
                                        "WHERE id = ? AND (whatsapp_locked IS NULL OR whatsapp_locked = 0)",
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
            # Fetch painel_username for the {user} template variable — some
            # admins prefer showing the login ("joao_iptv44") over the display
            # name, especially for verifying identity.
            painel_user = ""
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    cur = await db.execute(
                        "SELECT painel_username FROM customers WHERE id = ?",
                        (customer["id"],),
                    )
                    row = await cur.fetchone()
                    if row:
                        painel_user = (row["painel_username"] or "").strip()
            except Exception:
                pass

            if phone:
                # Cancel any pending trial reminders + queued deliveries —
                # the client just paid + renewed. They don't need to hear
                # "seu teste está acabando" 5 min after receiving "renovação
                # confirmada". Covers all known trial event keys.
                try:
                    from services.reminders import cancel_pending_for_phone
                    cancelled = await cancel_pending_for_phone(
                        phone,
                        event_keys=[
                            "trial_1h_reminder",
                            "trial_3h_reminder",
                            "trial_expired",
                            "trial_ready",  # in case queue is retrying a failed trial_ready
                        ],
                    )
                    if cancelled > 0:
                        logger.info(
                            "Cancelled %d pending trial reminder(s)/deliveries for %s "
                            "(client already renewed)", cancelled, phone,
                        )
                except Exception:
                    logger.exception("Failed to cancel pending reminders for %s", phone)

                client_notified = await send_notification(
                    "renewal_success", phone,
                    {
                        "name": customer["name"],
                        "user": painel_user or customer["name"],
                        "password": (await _cache_user(painel_id)).get("password") or "",
                        **(await _clover_vars(payment)),
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
                import json as _j
                _extra = len(_j.loads(payment.get("extra_customer_ids") or "[]"))
                _clov = int(payment.get("clovers") or 0)
                _prov = "Mercado Pago (Pix)" if payment.get("provider") == "mercadopago" else "InfinitePay"
                admin_msg = (
                    "💰 *Pagamento confirmado*\n\n"
                    f"👤 Cliente: {customer['name']}\n"
                    f"👥 Login: {painel_user or '-'}\n"
                    f"📱 WhatsApp: {phone or '-'}\n"
                    f"📦 Plano: {payment['plan_months']} mês(es)  |  {amount_brl}\n"
                    f"💳 Pagamento: {_prov}" + (f" · conta {payment.get('account_id')}" if payment.get("account_id") else "") + "\n"
                    + (f"👥 Logins no pagamento: {1 + _extra}\n" if _extra else "")
                    + (f"🍀 Trevo da Sorte: sim — {_clov} {'trevo' if _clov == 1 else 'trevos'}\n" if _clov else "🍀 Trevo da Sorte: não\n")
                    + (f"🏷️ Desconto: {payment.get('discount_percent')}%" + (f" (cupom {payment.get('coupon_code')})" if payment.get("coupon_code") else "") + "\n" if payment.get("discount_percent") else "")
                    + f"🎯 Sistema: {(customer.get('system_type') or '-').upper()}\n"
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

        extra_results = []
        if payment.get("extra_customer_ids"):
            extra_results = await _renew_extra_accounts(payment, phone, source)
        return {"ok": True, "status": "renewed", "payment_id": payment["id"], "painel_id": painel_id,
                "result": result, "extra_renewals": extra_results}
    except Exception as e:
        logger.exception("Renewal painel call failed for payment %s", payment["id"])
        err_str = str(e)
        err_upper = err_str.upper()
        # Classify — some painel.fun errors are transient (slot temporarily
        # unavailable, network hiccup) and should be RETRIED automatically.
        is_transient = any(k in err_upper for k in (
            "NO_SLOT_AVAILABLE", "TIMEOUT", "TIMED OUT", "TEMPORARY", "TRY AGAIN",
            "GATEWAY", "503", "502", "504", "CONNECTION",
        ))

        await log_activity(
            "renewal_error",
            f"{customer['name']}: {err_str}",
            customer["id"], "error",
        )

        # Schedule automatic retry (backoff: 5min, 15min, 30min, 1h, 4h, 12h)
        # The retry loop in services/renewal_retry.py picks these up.
        BACKOFF_MINUTES = [5, 15, 30, 60, 240, 720]
        attempts = 0
        if is_transient:
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    cur = await db.execute(
                        "SELECT renewal_attempts FROM payments WHERE id = ?",
                        (payment["id"],),
                    )
                    row = await cur.fetchone()
                    attempts = int((row["renewal_attempts"] if row else 0) or 0)
                    if attempts < len(BACKOFF_MINUTES):
                        delay_min = BACKOFF_MINUTES[attempts]
                        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
                        next_at = (_dt.now(_tz.utc) + _td(minutes=delay_min)).isoformat()
                        await db.execute(
                            "UPDATE payments SET status = 'paid_renewal_failed', "
                            "renewal_attempts = ?, renewal_next_retry_at = ?, "
                            "renewal_last_error = ? WHERE id = ?",
                            (attempts + 1, next_at, err_str[:400], payment["id"]),
                        )
                        await db.commit()
                        logger.info(
                            "Scheduled auto-retry #%d for payment=%s at %s (%s)",
                            attempts + 1, payment["id"], next_at, err_str[:80],
                        )
            except Exception:
                logger.exception("Failed to schedule renewal retry")

        # Notify the CLIENT so they don't feel abandoned — pagamento chegou,
        # ativação está sendo processada. Only on FIRST failure to avoid spam.
        try:
            first_failure = (attempts == 0) if is_transient else True
            if first_failure and phone:
                from services.notifier import send_hardcoded
                friendly = (
                    f"✅ Recebemos seu pagamento, {customer['name']}!\n\n"
                    "Estamos ativando sua renovação — pode levar alguns minutos "
                    "por instabilidade no servidor. Você receberá uma nova "
                    "mensagem assim que ficar pronto. 💙\n\n"
                    "Se preferir falar com um atendente, é só responder aqui."
                )
                await send_hardcoded(
                    phone, friendly,
                    event_key="renewal_processing",
                    customer_id=customer["id"],
                )
        except Exception:
            logger.exception("Failed to send 'processing' client message")

        # Alert admin — the customer paid but painel.fun refused/errored on renewal.
        try:
            from services.notifier import send_admin_alert
            amount_brl = f"R$ {payment['amount_cents']/100:.2f}".replace(".", ",")
            # Friendly guidance depending on the error type
            if "NO_SLOT_AVAILABLE" in err_upper:
                guidance = (
                    "⚠️ *Painel sem vaga disponível.* Tentaremos renovar "
                    "automaticamente nos próximos minutos. Verifique seu "
                    "estoque de vagas no painel.fun se persistir."
                )
            elif is_transient:
                guidance = (
                    "⏳ Erro transitório do painel — retry automático agendado. "
                    "Nenhuma ação necessária por enquanto."
                )
            else:
                guidance = (
                    "❌ Erro persistente. Renove esse cliente manualmente no painel."
                )
            retry_line = (
                f"\n🔁 Tentativa {attempts + 1} — próximo retry em {BACKOFF_MINUTES[min(attempts, len(BACKOFF_MINUTES)-1)]} min"
                if is_transient else ""
            )
            await send_admin_alert(
                f"❌ *Renovação FALHOU no painel.fun*{retry_line}\n\n"
                f"👤 Cliente: {customer['name']}\n"
                f"📱 WhatsApp: {phone or customer.get('whatsapp') or '-'}\n"
                f"👥 Login: {painel_user or '-'}\n"
                f"📦 {payment['plan_months']} mês(es) | {amount_brl}\n"
                f"🔗 Painel ID: {painel_id}\n"
                f"🛰️ Origem: {source}\n\n"
                f"Erro: {err_str[:200]}\n\n"
                f"{guidance}"
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
                "renewal_error": err_str,
                "painel_id": painel_id,
            })
        except Exception:
            pass
        return {"ok": False, "status": "renewal_failed", "payment_id": payment["id"], "error": err_str}


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

    # Persist so future notifications are instant — but respect manual lock.
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE customers SET whatsapp = ?, updated_at = ? "
            "WHERE id = ? AND (whatsapp_locked IS NULL OR whatsapp_locked = 0)",
            (phone, now_iso(), pmt["customer_id"]),
        )
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
            **(await _clover_vars({"id": pmt["id"]})),
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


@router.get("/trace/{key}")
async def trace_payment(key: str):
    """Admin: complete lifecycle trace for a payment. Returns:
      • the payment row (raw)
      • all activity_log entries for the customer around this payment
      • the last 5 webhook-related log lines (from activity_log)
      • what the code would do RIGHT NOW if this webhook fired again

    `key` accepts either payment_id, order_nsu, or a painel_id.
    Zero side-effects — read-only diagnostic.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Resolve by id, order_nsu, or customer_id
        cur = await db.execute(
            "SELECT * FROM payments WHERE id = ? OR order_nsu = ? OR customer_id = ? "
            "ORDER BY created_at DESC LIMIT 5",
            (key, key, key),
        )
        payments = [dict(r) for r in await cur.fetchall()]

        activity = []
        if payments:
            customer_ids = list({p["customer_id"] for p in payments if p.get("customer_id")})
            if customer_ids:
                placeholders = ",".join("?" for _ in customer_ids)
                cur = await db.execute(
                    f"SELECT * FROM activity_logs WHERE customer_id IN ({placeholders}) "
                    f"ORDER BY created_at DESC LIMIT 30",
                    tuple(customer_ids),
                )
                activity = [dict(r) for r in await cur.fetchall()]

        # Customer + trials context
        customer = None
        trials = []
        if payments:
            cur = await db.execute(
                "SELECT * FROM customers WHERE id = ?",
                (payments[0]["customer_id"],),
            )
            crow = await cur.fetchone()
            customer = dict(crow) if crow else None
            cur = await db.execute(
                "SELECT trial_user_id, system_type, created_at FROM trials "
                "WHERE customer_id = ? ORDER BY created_at DESC LIMIT 5",
                (payments[0]["customer_id"],),
            )
            trials = [dict(r) for r in await cur.fetchall()]

    # What would `_process_payment_confirmation` do RIGHT NOW?
    diagnosis = {"can_renew": False, "reason": "no payment found"}
    if payments:
        p = payments[0]
        painel_id = _extract_painel_id_from_nsu(p["order_nsu"] or "")
        if not painel_id or not painel_id.isdigit():
            painel_id = next(
                (t["trial_user_id"] for t in trials if t.get("trial_user_id")),
                "",
            )
        if painel_id and str(painel_id).isdigit() and p.get("package_id"):
            diagnosis = {
                "can_renew": True,
                "would_call": f"painel.renew_user(user_id='{painel_id}', package_id={p['package_id']})",
                "current_status": p["status"],
            }
        elif not painel_id:
            diagnosis = {
                "can_renew": False,
                "reason": "painel_id could not be extracted from order_nsu and no trial found",
                "order_nsu": p["order_nsu"],
            }
        elif not p.get("package_id"):
            diagnosis = {
                "can_renew": False,
                "reason": "package_id is 0/empty — check plan_months mapping in painel.PACKAGE_IDS",
                "plan_months": p.get("plan_months"),
            }

    return {
        "key": key,
        "payments": payments,
        "customer": customer,
        "trials": trials,
        "activity_log": activity,
        "diagnosis": diagnosis,
        "next_step": (
            "Se can_renew=true e status ainda é 'pending', chame "
            "POST /api/payments/reprocess/{payment_id} para forçar. "
            "Se status='paid_renewal_failed', o retry automático vai tentar novamente "
            "(veja renewal_next_retry_at). Se painel_id não foi encontrado, "
            "renove manualmente no painel.fun."
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

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=168)).isoformat()  # 7 days

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, order_nsu, infinitepay_url, confirmation_token, created_at, provider, account_id, mp_payment_id "
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
            from services.payment_accounts import check_paid
            is_paid, check = await check_paid(pmt)
            if is_paid:
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
            if pmt.get("provider") == "mercadopago":
                continue
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
    from services import customer_prefs
    prefs = await customer_prefs.get_prefs(customer["id"])
    prices = {m: await customer_prefs.price_for(customer["id"], m) for m in (1, 3, 6, 12)}
    if prefs.get("fixed_plan"):
        prices = {prefs["fixed_plan"]: prices[prefs["fixed_plan"]]}

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
                " receipt_url, infinitepay_url, order_nsu, transaction_nsu,"
                " coupon_code, discount_percent, original_amount_cents"
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

    # Login shown on the checkout ("Cobrança para <login>").
    login = None
    try:
        from routers.painel_users import _read_cache
        cached, _ = await _read_cache()
        u = next((x for x in cached or [] if str(x.get("id") or x.get("user_id")) == str(customer["id"])), None)
        login = u and (u.get("username") or u.get("login"))
        if not login:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("SELECT painel_username FROM customers WHERE id = ?", (customer["id"],))
                row = await cur.fetchone()
                login = row[0] if row else None
    except Exception:
        logger.exception("login lookup failed for %s", customer["id"])
    customer["login"] = login

    from services import payment_accounts
    providers = await payment_accounts.enabled_providers()
    cu = await _cache_user(customer["id"])
    return {
        "customer": customer,
        "prices_cents": prices,
        "discounts_blocked": bool(prefs.get("no_discount")),
        "providers": providers or ["infinitepay"],
        "mp_fee_percent": payment_accounts.MP_PIX_FEE_PERCENT,
        "linked_accounts": await _linked_accounts(customer["id"]),
        "adult_default": _has_adult(cu) if cu else True,
        "raffle": await _public_raffle(),
        "payments_history": payments_history,
        "messages_history": messages_history,
        "active_discount": await _get_active_discount_for_public(str(customer["id"])),
        # Which payment provider is currently active. When "painel", the /pay page
        # will redirect straight to the painel-generated pagme.xyz link.
        "payment_link_provider": (await get_setting("payment_link_provider") or "infinitepay").strip().lower(),
        "brand": {
            "name": (await get_setting("brand_name") or "").strip() or "WhatsFlow",
            "logo_url": (await get_setting("brand_logo_url") or "").strip() or None,
        },
    }


@router.get("/painel-link/{customer_id}")
async def get_painel_payment_link(customer_id: str):
    """Public: resolve the painel.fun-generated payment link for a customer.

    Called by /pay/{customer_id} when `payment_link_provider == "painel"`.
    Painel returns a `pagme.xyz` URL where the customer pays; upon payment
    the panel renews the user internally — we don't need webhook or /renew.
    """
    # Resolve painel_id from local records (trials first, then Mongo)
    painel_id = None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT trial_user_id FROM trials WHERE trial_user_id = ? OR customer_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (str(customer_id), str(customer_id)),
        )
        row = await cur.fetchone()
        if row:
            painel_id = row["trial_user_id"]

    if not painel_id:
        # Direct fallback: if customer_id is already a painel id (numeric)
        if str(customer_id).isdigit():
            painel_id = str(customer_id)
        else:
            # Try Mongo lookup for painel_id
            try:
                from services import mongo_store
                doc = await mongo_store.find_customer_by_painel_id(str(customer_id))
                if doc and doc.get("painel_id"):
                    painel_id = str(doc["painel_id"])
            except Exception:
                pass

    if not painel_id:
        raise HTTPException(404, "Painel ID not found for this customer")

    try:
        from services import painel
        data = await painel.get_client_payment_link(painel_id)
        return {"url": data["url"], "token": data.get("token"), "painel_id": painel_id}
    except Exception as e:
        logger.exception("Failed to fetch painel payment link for %s", painel_id)
        raise HTTPException(502, f"Painel error: {e}")


async def _get_active_discount_for_public(customer_id: str) -> dict | None:
    """Public-facing wrapper — returns None or {'percent': int, 'source': str}
    so the client sees on /pay/{id} why they should pay today."""
    try:
        from services.discount import get_active_discount
        return await get_active_discount(customer_id)
    except Exception:
        return None


@router.get("/mp-status/{payment_id}")
async def mp_payment_status(payment_id: str):
    """Public: polled by the /pay page while the customer pays the Mercado Pago Pix."""
    from services.payment_accounts import check_paid
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute(
            "SELECT id, order_nsu, status, provider, account_id, mp_payment_id FROM payments WHERE id = ?",
            (payment_id,))).fetchone()
    if not row or row["provider"] != "mercadopago":
        raise HTTPException(404, "Pagamento não encontrado")
    pmt = dict(row)
    if pmt["status"] != "pending":
        return {"status": "renewed" if pmt["status"] == "paid" else pmt["status"]}
    paid, raw = await check_paid(pmt)
    if not paid:
        return {"status": "pending", "mp_status": raw.get("mp_status")}
    proc = await _process_payment_confirmation(pmt["order_nsu"], paid=True, source="mercadopago_page", raw=raw)
    return {"status": proc.get("status")}


@router.post("/mp-webhook")
async def mp_webhook(request: Request):
    """Mercado Pago notification → re-check the payment with its own account token."""
    from services.payment_accounts import check_paid
    try:
        body = await request.json()
    except Exception:
        body = {}
    mp_id = str((body.get("data") or {}).get("id") or request.query_params.get("data.id")
                or request.query_params.get("id") or "").strip()
    if not mp_id:
        return {"received": True}
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute(
            "SELECT id, order_nsu, status, provider, account_id, mp_payment_id FROM payments WHERE mp_payment_id = ?",
            (mp_id,))).fetchone()
    if not row or row["status"] != "pending":
        return {"received": True}
    paid, raw = await check_paid(dict(row))
    if paid:
        await _process_payment_confirmation(row["order_nsu"], paid=True, source="mercadopago_webhook", raw=raw)
    return {"received": True, "paid": paid}
