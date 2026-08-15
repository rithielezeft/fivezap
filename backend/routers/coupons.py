"""Coupons — CRUD + public validation endpoint."""
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import aiosqlite

from database import DB_PATH
from models import new_id, now_iso
from services.coupon import (
    MAX_DISCOUNT_PERCENT, COOLDOWN_DAYS,
    normalize_code, clamp_percent, validate_coupon,
)

router = APIRouter(prefix="/api/coupons", tags=["coupons"])


class Coupon(BaseModel):
    id: str
    code: str
    discount_percent: float
    active: bool = True
    expires_at: Optional[str] = None
    max_uses: Optional[int] = None
    created_at: str
    updated_at: str
    usage_count: Optional[int] = 0


class CouponCreate(BaseModel):
    code: str
    discount_percent: float
    active: bool = True
    expires_at: Optional[str] = None  # ISO datetime — hard expiration cap
    max_uses: Optional[int] = None    # total redemptions allowed (all users)
    # If truthy, `expires_at` is auto-set to now + 24h (unless caller passed
    # an explicit `expires_at`). Convenience flag for the UI.
    auto_expire_24h: bool = False


class CouponUpdate(BaseModel):
    code: Optional[str] = None
    discount_percent: Optional[float] = None
    active: Optional[bool] = None
    expires_at: Optional[str] = None
    max_uses: Optional[int] = None


class CouponUsage(BaseModel):
    id: str
    coupon_id: str
    coupon_code: str
    customer_id: str
    payment_id: Optional[str] = None
    phone: Optional[str] = None
    discount_percent: int
    receipt_url: Optional[str] = None
    painel_username: Optional[str] = None
    used_at: str


class CouponValidateRequest(BaseModel):
    code: str
    customer_id: str


def _row_to_coupon(row) -> dict:
    d = dict(row)
    d["active"] = bool(d.get("active"))
    return d


@router.get("", response_model=List[Coupon])
async def list_coupons():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM coupon_usages u WHERE u.coupon_id = c.id) "
            "AS usage_count FROM coupons c ORDER BY c.created_at DESC"
        )
        rows = [_row_to_coupon(r) for r in await cur.fetchall()]
    return [Coupon(**r) for r in rows]


@router.post("", response_model=Coupon)
async def create_coupon(payload: CouponCreate):
    code = normalize_code(payload.code)
    if not code:
        raise HTTPException(400, "Código é obrigatório")
    percent = clamp_percent(payload.discount_percent)
    if percent < 0.1:
        raise HTTPException(400, f"Desconto deve ser entre 0.1 e {MAX_DISCOUNT_PERCENT}%")

    # expires_at: if auto_expire_24h flag is set and no explicit value,
    # default to now + 24h. Otherwise store the caller-provided ISO.
    from datetime import datetime, timezone, timedelta
    exp_at = (payload.expires_at or "").strip() or None
    if not exp_at and payload.auto_expire_24h:
        exp_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

    max_uses = int(payload.max_uses) if payload.max_uses and payload.max_uses > 0 else None

    coupon_id = new_id()
    ts = now_iso()
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO coupons (id, code, discount_percent, active, "
                "expires_at, max_uses, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (coupon_id, code, percent, 1 if payload.active else 0,
                 exp_at, max_uses, ts, ts),
            )
            await db.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(409, f"Já existe um cupom com o código '{code}'")

    return Coupon(
        id=coupon_id, code=code, discount_percent=percent,
        active=payload.active, expires_at=exp_at, max_uses=max_uses,
        created_at=ts, updated_at=ts, usage_count=0,
    )


@router.put("/{coupon_id}", response_model=Coupon)
async def update_coupon(coupon_id: str, payload: CouponUpdate):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM coupons WHERE id = ?", (coupon_id,))
        existing = await cur.fetchone()
        if not existing:
            raise HTTPException(404, "Cupom não encontrado")

        fields: dict = {}
        if payload.code is not None:
            new_code = normalize_code(payload.code)
            if not new_code:
                raise HTTPException(400, "Código não pode ser vazio")
            fields["code"] = new_code
        if payload.discount_percent is not None:
            percent = clamp_percent(payload.discount_percent)
            if percent < 0.1:
                raise HTTPException(400, f"Desconto deve ser entre 0.1 e {MAX_DISCOUNT_PERCENT}%")
            fields["discount_percent"] = percent
        if payload.active is not None:
            fields["active"] = 1 if payload.active else 0
        if payload.expires_at is not None:
            # Empty string clears the expiration; a valid ISO sets it.
            fields["expires_at"] = payload.expires_at.strip() or None
        if payload.max_uses is not None:
            fields["max_uses"] = int(payload.max_uses) if payload.max_uses > 0 else None
        if not fields:
            raise HTTPException(400, "Nenhum campo para atualizar")

        fields["updated_at"] = now_iso()
        sets = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [coupon_id]
        try:
            await db.execute(f"UPDATE coupons SET {sets} WHERE id = ?", values)
            await db.commit()
        except aiosqlite.IntegrityError:
            raise HTTPException(409, f"Código '{fields.get('code')}' já está em uso")

        cur = await db.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM coupon_usages u WHERE u.coupon_id = c.id) "
            "AS usage_count FROM coupons c WHERE c.id = ?",
            (coupon_id,),
        )
        row = await cur.fetchone()
    return Coupon(**_row_to_coupon(row))


@router.delete("/{coupon_id}")
async def delete_coupon(coupon_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM coupons WHERE id = ?", (coupon_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Cupom não encontrado")
        await db.commit()
    return {"ok": True}


@router.get("/{coupon_id}/usages", response_model=List[CouponUsage])
async def list_coupon_usages(coupon_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM coupon_usages WHERE coupon_id = ? ORDER BY used_at DESC",
            (coupon_id,),
        )
        return [CouponUsage(**dict(r)) for r in await cur.fetchall()]


@router.get("/usages/recent", response_model=List[CouponUsage])
async def list_recent_usages(limit: int = 50):
    limit = max(1, min(int(limit), 200))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM coupon_usages ORDER BY used_at DESC LIMIT ?", (limit,),
        )
        return [CouponUsage(**dict(r)) for r in await cur.fetchall()]


# PUBLIC endpoint — called by /pay/{id} page to validate before checkout.
@router.post("/validate")
async def validate_coupon_endpoint(payload: CouponValidateRequest):
    result = await validate_coupon(payload.code, payload.customer_id)
    result["max_percent"] = MAX_DISCOUNT_PERCENT
    result["cooldown_days"] = COOLDOWN_DAYS
    return result
