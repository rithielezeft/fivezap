"""Background loop that retries failed painel.fun renewals.

Handles transient errors like ERROR_NO_SLOT_AVAILABLE where the reseller
temporarily runs out of slots. Payments in status='paid_renewal_failed'
with `renewal_next_retry_at <= now` are picked up and re-processed by
calling `_process_payment_confirmation` again with `raw={"force_paid":true}`.

On success: status → 'paid', client gets renewal_success notification
that was missed on the first attempt.
On failure: renewal_attempts++, next_retry_at pushed further out (backoff).
After BACKOFF_MINUTES is exhausted (6 attempts, ~19h total), we stop
retrying and just leave the payment in 'paid_renewal_failed'.
"""
import asyncio
import logging
from datetime import datetime, timezone

import aiosqlite

from database import DB_PATH

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60  # sweep every minute


async def _sweep_once():
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, order_nsu, renewal_attempts FROM payments "
            "WHERE status = 'paid_renewal_failed' "
            "  AND renewal_next_retry_at IS NOT NULL "
            "  AND renewal_next_retry_at <= ? "
            "ORDER BY renewal_next_retry_at ASC LIMIT 20",
            (now_iso,),
        )
        rows = [dict(r) for r in await cur.fetchall()]

    if not rows:
        return

    logger.info("renewal_retry: sweeping %d due payments", len(rows))

    # Reset status to 'paid' BEFORE calling _process_payment_confirmation
    # so the shared handler treats this as a fresh attempt (the clone path
    # is guarded by transaction_nsu so we don't re-notify on success paths).
    # Actually simpler — call renew_user directly and mirror the update.
    from services import painel
    from services.notifier import send_notification, send_admin_alert, send_hardcoded
    from services import mongo_store

    for r in rows:
        pid = r["id"]
        try:
            # Fetch full payment + customer for the retry
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute("SELECT * FROM payments WHERE id = ?", (pid,))
                payment = dict(await cur.fetchone() or {})
                if not payment:
                    continue
                cur = await db.execute(
                    "SELECT * FROM customers WHERE id = ?", (payment["customer_id"],),
                )
                customer = dict(await cur.fetchone() or {})

            # Extract painel_id from order_nsu (same logic as main flow)
            from routers.payments import _extract_painel_id_from_nsu
            painel_id = _extract_painel_id_from_nsu(payment.get("order_nsu") or "")

            if not painel_id or not str(painel_id).isdigit():
                logger.warning("renewal_retry: skip %s (no painel_id in order_nsu=%s)",
                               pid, payment.get("order_nsu"))
                # Push next_retry to +12h so we don't loop
                await _reschedule(pid, r["renewal_attempts"], "no painel_id",
                                  far_future=True)
                continue

            logger.info("renewal_retry: attempting renewal for payment=%s "
                        "painel_id=%s attempt=%d",
                        pid, painel_id, (r["renewal_attempts"] or 0))

            try:
                result = await painel.renew_user(
                    user_id=painel_id,
                    package_id=payment.get("package_id") or 0,
                    months=payment.get("plan_months"),
                )
            except Exception as e:
                # Retry failed too — bump attempts + reschedule.
                await _reschedule(pid, r["renewal_attempts"], str(e))
                logger.warning("renewal_retry: still failing for %s (attempt=%d): %s",
                               pid, (r["renewal_attempts"] or 0) + 1, str(e)[:200])
                continue

            # SUCCESS — mark paid, resolve new_expires, notify client + admin.
            new_expires = _extract_expiration(result)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE payments SET status = 'paid', paid_at = COALESCE(paid_at, ?), "
                    "renewal_next_retry_at = NULL WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), pid),
                )
                await db.commit()

            logger.info("renewal_retry: SUCCESS payment=%s new_expires=%s",
                        pid, new_expires)

            phone = (customer.get("whatsapp") or "").strip()
            painel_login = (customer.get("painel_username") or "").strip()
            if phone:
                try:
                    ok = await send_notification(
                        "renewal_success", phone,
                        {
                            **(await __import__("routers.payments", fromlist=["_clover_vars"])._clover_vars(payment)),
                            "name": customer.get("name") or "",
                            "user": painel_login or customer.get("name") or "",
                            "plan_months": payment.get("plan_months") or 0,
                            "new_expires_at": new_expires,
                            "system_type": customer.get("system_type") or "",
                        },
                        customer_id=customer.get("id"),
                    )
                    if not ok:
                        # Fallback message so client isn't left hanging
                        await send_hardcoded(
                            phone,
                            f"✅ Renovação confirmada, {customer.get('name') or 'cliente'}!\n\n"
                            f"Seu plano foi renovado" +
                            (f" até {new_expires}. 🎉" if new_expires else ". 🎉") +
                            "\n\nObrigado pela paciência — houve um leve atraso na ativação.",
                            event_key="renewal_success_retry_fallback",
                            customer_id=customer.get("id"),
                        )
                except Exception:
                    logger.exception("renewal_retry: client notify failed")

            try:
                amount_brl = f"R$ {(payment.get('amount_cents') or 0)/100:.2f}".replace(".", ",")
                await send_admin_alert(
                    "✅ *Renovação recuperada (auto-retry)*\n\n"
                    f"👤 Cliente: {customer.get('name') or '-'}\n"
                    f"👥 Login: {painel_login or '-'}\n"
                    f"📦 {payment.get('plan_months')} mês(es) | {amount_brl}\n"
                    f"📆 Novo vencimento: {new_expires or '-'}\n"
                    f"🔁 Tentativa: {(r['renewal_attempts'] or 0) + 1}"
                )
            except Exception:
                pass

            try:
                await mongo_store.upsert_payment({
                    "_id": pid,
                    "status": "paid",
                    "renewal_recovered_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                pass
        except Exception:
            logger.exception("renewal_retry: sweep failed for %s", pid)


def _extract_expiration(result) -> str:
    """Same conversion logic as the main renewal flow — best-effort."""
    if not isinstance(result, dict):
        return ""
    candidates = [result]
    nested = result.get("original")
    if isinstance(nested, dict):
        candidates.append(nested)
    for c in candidates:
        for key in ("expires_at", "exp_date", "expiration", "new_expires_at"):
            v = c.get(key)
            if v:
                if isinstance(v, (int, float)):
                    from datetime import datetime as _dt
                    try:
                        ts = v / 1000 if v > 10**12 else v
                        return _dt.fromtimestamp(ts).strftime("%d/%m/%Y")
                    except Exception:
                        continue
                if isinstance(v, str):
                    return v
    return ""


async def _reschedule(payment_id: str, current_attempts: int, error: str,
                      far_future: bool = False):
    """Advance renewal_attempts + push next_retry_at further out."""
    BACKOFF_MINUTES = [5, 15, 30, 60, 240, 720]
    attempts = int(current_attempts or 0)
    from datetime import timedelta
    if far_future:
        delay_min = 12 * 60
    elif attempts < len(BACKOFF_MINUTES):
        delay_min = BACKOFF_MINUTES[attempts]
    else:
        # Exhausted — clear next_retry_at so we stop trying
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE payments SET renewal_next_retry_at = NULL, "
                "renewal_last_error = ? WHERE id = ?",
                (error[:400], payment_id),
            )
            await db.commit()
        try:
            from services.notifier import send_admin_alert
            await send_admin_alert(
                "🛑 *Renovação DESISTIDA após 6 tentativas*\n\n"
                f"Payment: {payment_id}\n"
                f"Último erro: {error[:200]}\n\n"
                "Renove manualmente no painel.fun."
            )
        except Exception:
            pass
        return
    next_at = (datetime.now(timezone.utc) + timedelta(minutes=delay_min)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE payments SET renewal_attempts = ?, "
            "renewal_next_retry_at = ?, renewal_last_error = ? WHERE id = ?",
            (attempts + 1, next_at, error[:400], payment_id),
        )
        await db.commit()


async def renewal_retry_loop():
    """Runs forever, sweeps due retries every CHECK_INTERVAL_SECONDS."""
    logger.info("renewal_retry_loop started (interval=%ds)", CHECK_INTERVAL_SECONDS)
    while True:
        try:
            await _sweep_once()
        except Exception:
            logger.exception("renewal_retry_loop iteration failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
