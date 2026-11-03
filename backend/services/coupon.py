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


def clamp_percent(percent) -> float:
    """Return the discount % as a float in [0.1, MAX_DISCOUNT_PERCENT].

    Accepts int, float or numeric string. Values > MAX are capped, values
    <= 0 become 0 (caller decides whether to reject 0).
    """
    try:
        p = float(percent)
    except (TypeError, ValueError):
        return 0.0
    if p <= 0:
        return 0.0
    return round(min(p, float(MAX_DISCOUNT_PERCENT)), 2)


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
      {valid: True, coupon: {...}, discount_percent: float}  OR
      {valid: False, reason: str, code: str}

    Validation order (fail-fast, most-specific first):
      1. Empty code
      2. Not found
      3. Inactive
      4. Expired (expires_at)
      5. Max uses reached
      6. 28-day cooldown per-customer
    """
    from services.customer_prefs import discount_blocked
    if await discount_blocked(customer_id):
        return {"valid": False, "reason": "Descontos não disponíveis para este cliente"}
    code_norm = normalize_code(code)
    if not code_norm:
        return {"valid": False, "reason": "Código vazio", "code": ""}

    coupon = await get_coupon_by_code(code_norm)
    if not coupon:
        return {"valid": False, "reason": "Cupom não encontrado", "code": code_norm}
    if not coupon.get("active"):
        return {"valid": False, "reason": "Cupom inativo", "code": code_norm}

    # Expires_at (if set) — hard time cap on the coupon itself
    exp = (coupon.get("expires_at") or "").strip()
    if exp:
        try:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp_dt:
                return {"valid": False, "reason": "Cupom expirado", "code": code_norm}
        except Exception:
            pass

    # Max uses (if set) — cap on total redemptions across ALL customers
    max_uses = coupon.get("max_uses")
    if max_uses is not None and int(max_uses) > 0:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT COUNT(*) AS c FROM coupon_usages WHERE coupon_id = ?",
                (coupon["id"],),
            )
            row = await cur.fetchone()
            used = int(row["c"] if row else 0)
        if used >= int(max_uses):
            return {"valid": False, "reason": f"Cupom esgotado (limite de {max_uses} usos atingido)", "code": code_norm}

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
