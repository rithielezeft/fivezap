"""Admin: manage InfinitePay / Mercado Pago accounts and their monthly caps."""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import payment_accounts as pa

router = APIRouter(prefix="/api/payment-accounts", tags=["payment-accounts"])


class AccountIn(BaseModel):
    id: Optional[str] = None
    provider: str
    label: Optional[str] = ""
    handle: Optional[str] = ""
    access_token: Optional[str] = ""  # empty = keep the stored token
    monthly_limit_cents: int = 0
    enabled: bool = True


class AccountsIn(BaseModel):
    accounts: List[AccountIn]


async def _view() -> dict:
    totals = await pa.month_totals()
    accounts = await pa.load_accounts()
    return {
        "accounts": [pa.public_view(a, totals) for a in accounts],
        "providers_enabled": await pa.enabled_providers(),
        "mp_fee_percent": pa.MP_PIX_FEE_PERCENT,
    }


@router.get("")
async def list_accounts():
    return await _view()


@router.put("")
async def save_accounts(body: AccountsIn):
    current = {a["id"]: a for a in await pa.load_accounts()}
    merged = []
    for a in body.accounts:
        d = a.model_dump()
        if a.provider not in pa.PROVIDERS:
            raise HTTPException(400, f"Provedor inválido: {a.provider}")
        if not d["access_token"] and a.id in current:
            d["access_token"] = current[a.id].get("access_token") or ""
        merged.append(d)
    await pa.save_accounts(merged)
    return await _view()


@router.post("/{account_id}/test")
async def test_account(account_id: str):
    acc = await pa.get_account(account_id)
    if not acc:
        raise HTTPException(404, "Conta não encontrada")
    if acc["provider"] == "mercadopago":
        from services import mercadopago
        return await mercadopago.check_token(acc.get("access_token") or "")
    return {"ok": bool(acc.get("handle")), "handle": acc.get("handle")}
