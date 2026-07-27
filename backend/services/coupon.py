"""Coupon business logic.

Rules (agreed with product):
- Discount percent is capped at 50%.
- A given customer can only USE a coupon once every 28 days
  (any coupon — not per-code). "Use" = confirmed payment.
- Only ACTIVE coupons validate.
- Coupon code is stored uppercase (case-insensitive lookup).
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiosqlite

from database import DB_PATH

MAX_DISCOUNT_PERCENT = 50
COOLDOWN_DAYS = 28


def normalize_code(code: str) -> str:
    return (code or "").strip().upper()


def clamp_percent(percent) -> int:
    try:
        p = int(percent)
    except (TypeError, ValueError):
        return 0
    return max(1, min(MAX_DISCOUNT_PERCENT, p))


async def get_coupon_by_code(code: str) -> Optional[dict]:
    code_norm = normalize_code(code)
    if not code_norm:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM coupons WHERE code = ?", (code_norm,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def has_recent_usage(customer_id: str) -> Optional[str]:
    """Return the last used_at ISO if the customer used ANY coupon in the last
    COOLDOWN_DAYS days, else None."""
    if not customer_id:
        return None
    cutoff = (datetime.now(timezone.utc) - timedelta(days=COOLDOWN_DAYS)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT used_at FROM coupon_usages WHERE customer_id = ? AND used_at >= ? "
            "ORDER BY used_at DESC LIMIT 1",
            (str(customer_id), cutoff),
        )
        row = await cur.fetchone()
        return row["used_at"] if row else None


async def validate_coupon(code: str, customer_id: str) -> dict:
    """Validate a coupon for a customer.

    Returns dict:
      {valid: True, coupon: {...}, discount_percent: int}  OR
      {valid: False, reason: str, code: str}
    """
    code_norm = normalize_code(code)
    if not code_norm:
        return {"valid": False, "reason": "Código vazio", "code": ""}

    coupon = await get_coupon_by_code(code_norm)
    if not coupon:
        return {"valid": False, "reason": "Cupom não encontrado", "code": code_norm}
    if not coupon.get("active"):
        return {"valid": False, "reason": "Cupom inativo", "code": code_norm}

    last_used = await has_recent_usage(str(customer_id))
    if last_used:
        return {
            "valid": False,
            "reason": (
                f"Você já usou um cupom nos últimos {COOLDOWN_DAYS} dias. "
                "Aguarde o próximo ciclo para usar um cupom novamente."
            ),
            "code": code_norm,
            "last_used_at": last_used,
        }

    percent = clamp_percent(coupon["discount_percent"])
    return {
        "valid": True,
        "code": code_norm,
        "coupon_id": coupon["id"],
        "discount_percent": percent,
    }


async def record_usage(
    *, coupon_id: str, coupon_code: str, customer_id: str,
    payment_id: str, phone: str = "", discount_percent: int = 0,
    receipt_url: str = "", painel_username: str = "",
) -> str:
    """Insert a coupon_usages row. Returns the new id."""
    import uuid as _uuid
    usage_id = str(_uuid.uuid4())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO coupon_usages (id, coupon_id, coupon_code, customer_id, "
            "payment_id, phone, discount_percent, receipt_url, painel_username, used_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (usage_id, coupon_id, normalize_code(coupon_code), str(customer_id),
             payment_id or "", phone or "", int(discount_percent or 0),
             receipt_url or "", painel_username or "",
             datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
    return usage_id


async def already_recorded_for_payment(payment_id: str) -> bool:
    if not payment_id:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id FROM coupon_usages WHERE payment_id = ? LIMIT 1", (payment_id,),
        )
        return (await cur.fetchone()) is not None
