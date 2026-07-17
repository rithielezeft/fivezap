"""Painel.fun proxy endpoints."""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import painel

router = APIRouter(prefix="/api/painel", tags=["painel"])
logger = logging.getLogger(__name__)


class RenewPayload(BaseModel):
    user_id: str
    system_type: str  # iptv | p2p | hybrid
    plan_months: int  # 1 | 3 | 6 | 12


@router.get("/users")
async def list_users(search: str = None, limit: int = 500):
    """Fetch users directly from painel.fun."""
    try:
        users = await painel.list_users(limit=limit, search=search)
        return {"users": users, "count": len(users)}
    except Exception as e:
        logger.exception("list_users failed")
        raise HTTPException(502, str(e))


@router.post("/renew")
async def renew(payload: RenewPayload):
    """Manually renew a painel user by ID."""
    package_id = painel.get_package_id(payload.system_type, payload.plan_months)
    try:
        result = await painel.renew_user(user_id=payload.user_id, package_id=package_id)
        return {"success": True, "package_id": package_id, "raw": result}
    except Exception as e:
        logger.exception("renew failed")
        raise HTTPException(502, str(e))


@router.get("/package-ids")
async def package_ids():
    """Return the mapping so the frontend can display."""
    return painel.PACKAGE_IDS
