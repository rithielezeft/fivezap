"""Admin: per-customer price/plan, discount block and reminder selection."""
from fastapi import APIRouter, HTTPException, Request

from services import customer_prefs as cp

router = APIRouter(prefix="/api/customer-prefs", tags=["customer-prefs"])


@router.get("/{painel_id}")
async def get_customer_prefs(painel_id: str):
    prefs = await cp.get_prefs(painel_id)
    defaults = {m: await cp.default_price(m) for m in cp.PLANS}
    return {"painel_id": painel_id, **prefs, "default_prices": defaults, "events": list(cp.EVENTS)}


@router.put("/{painel_id}")
async def put_customer_prefs(painel_id: str, request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Corpo inválido")
    try:
        return await cp.set_prefs(painel_id, body)
    except ValueError:
        raise HTTPException(400, "Valor inválido")
