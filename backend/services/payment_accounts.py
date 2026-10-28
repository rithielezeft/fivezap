"""Payment accounts (InfinitePay handles + Mercado Pago tokens) with monthly caps.

Stored as JSON in the `payment_accounts` setting. Routing: the first enabled
account (in list order) that has not reached its monthly limit receives the
payment; when every account is full, the LAST one keeps receiving."""
import json
import uuid
from datetime import datetime

import aiosqlite

from database import DB_PATH, get_setting, set_setting

PROVIDERS = ("infinitepay", "mercadopago")
RECEIVED_STATUSES = ("paid", "paid_renewal_failed")
MP_PIX_FEE_PERCENT = 0.99


def mp_amount(cents: int) -> int:
    """Pass the 0,99% Pix fee on to the customer (exact, rounded to the cent)."""
    return int(round(cents * (1 + MP_PIX_FEE_PERCENT / 100)))


async def load_accounts() -> list:
    raw = await get_setting("payment_accounts") or ""
    try:
        accounts = json.loads(raw) if raw else []
    except Exception:
        accounts = []
    if not raw and not any(a.get("provider") == "infinitepay" for a in accounts):
        handle = (await get_setting("infinitepay_handle") or "").strip()
        if handle:  # legacy single-handle config becomes the default account
            accounts.insert(0, {"id": "default", "provider": "infinitepay", "label": "InfinitePay",
                                "handle": handle, "monthly_limit_cents": 0, "enabled": True})
    return accounts


async def save_accounts(accounts: list) -> None:
    clean = []
    for a in accounts:
        if a.get("provider") not in PROVIDERS:
            continue
        clean.append({
            "id": a.get("id") or uuid.uuid4().hex[:10],
            "provider": a["provider"],
            "label": (a.get("label") or "").strip()[:60],
            "handle": (a.get("handle") or "").strip().lstrip("$"),
            "access_token": (a.get("access_token") or "").strip(),
            "monthly_limit_cents": max(0, int(a.get("monthly_limit_cents") or 0)),
            "enabled": bool(a.get("enabled", True)),
        })
    await set_setting("payment_accounts", json.dumps(clean))


async def month_totals() -> dict:
    """Received cents this calendar month per account_id (NULL → 'default')."""
    start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()[:10]
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COALESCE(account_id, 'default'), COALESCE(SUM(amount_cents), 0) FROM payments "
            f"WHERE status IN ({','.join('?' * len(RECEIVED_STATUSES))}) AND COALESCE(paid_at, created_at) >= ? "
            "GROUP BY 1",
            (*RECEIVED_STATUSES, start),
        )
        return {r[0]: int(r[1]) for r in await cur.fetchall()}


def _usable(a: dict) -> bool:
    if not a.get("enabled"):
        return False
    return bool(a.get("handle") if a["provider"] == "infinitepay" else a.get("access_token"))


async def enabled_providers() -> list:
    accounts = await load_accounts()
    return [p for p in PROVIDERS if any(a["provider"] == p and _usable(a) for a in accounts)]


async def pick_account(provider: str):
    candidates = [a for a in await load_accounts() if a["provider"] == provider and _usable(a)]
    if not candidates:
        return None
    totals = await month_totals()
    for a in candidates:
        limit = int(a.get("monthly_limit_cents") or 0)
        if limit <= 0 or totals.get(a["id"], 0) < limit:
            return a
    return candidates[-1]


async def get_account(account_id):
    for a in await load_accounts():
        if a["id"] == (account_id or "default"):
            return a
    return None


def public_view(a: dict, totals: dict) -> dict:
    tok = a.get("access_token") or ""
    return {
        **{k: v for k, v in a.items() if k != "access_token"},
        "access_token_masked": (tok[:8] + "…" + tok[-4:]) if tok else "",
        "has_token": bool(tok),
        "month_received_cents": totals.get(a["id"], 0),
    }


async def check_paid(pmt: dict) -> tuple:
    """Ask the payment's own provider/account whether it was paid → (paid, raw)."""
    acc = await get_account(pmt.get("account_id"))
    if (pmt.get("provider") or "infinitepay") == "mercadopago":
        from services import mercadopago
        if not acc or not acc.get("access_token") or not pmt.get("mp_payment_id"):
            return False, {"error": "mercadopago account/payment missing"}
        d = await mercadopago.get_payment(acc["access_token"], pmt["mp_payment_id"])
        paid = d.get("status") == "approved"
        return paid, {"transaction_nsu": f"mp-{pmt['mp_payment_id']}", "paid": paid,
                      "paid_amount": int(round(float(d.get("transaction_amount") or 0) * 100)),
                      "capture_method": "pix", "mp_status": d.get("status")}
    from services import infinitepay
    check = await infinitepay.check_payment(pmt["order_nsu"], handle=(acc or {}).get("handle"))
    return check.get("paid") is True, check
