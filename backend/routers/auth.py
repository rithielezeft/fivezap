"""Auth endpoints."""
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from services.auth import (
    verify_admin_password,
    create_token,
    require_admin,
    hash_password,
)
from database import set_setting

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

# Simple in-memory brute force map: ip -> [count, first_ts]
_failed = {}


class LoginPayload(BaseModel):
    password: str


class ChangePasswordPayload(BaseModel):
    current_password: str
    new_password: str


@router.post("/login")
async def login(payload: LoginPayload, request: Request):
    ip = request.client.host if request.client else "unknown"
    import time
    now = time.time()
    entry = _failed.get(ip, [0, now])
    if now - entry[1] > 900:  # reset after 15 min
        entry = [0, now]
    if entry[0] >= 8:
        raise HTTPException(429, "Muitas tentativas. Tente novamente em 15 minutos.")

    # tiny slowdown to prevent timing attacks
    await asyncio.sleep(0.1)

    ok = await verify_admin_password(payload.password)
    if not ok:
        entry[0] += 1
        entry[1] = now
        _failed[ip] = entry
        raise HTTPException(401, "Senha incorreta")

    _failed.pop(ip, None)
    token = create_token()
    return {"success": True, "access_token": token, "token_type": "bearer"}


@router.get("/me")
async def me(user=Depends(require_admin)):
    return {"authenticated": True, "sub": user.get("sub")}


@router.post("/change-password")
async def change_password(payload: ChangePasswordPayload, user=Depends(require_admin)):
    ok = await verify_admin_password(payload.current_password)
    if not ok:
        raise HTTPException(401, "Senha atual incorreta")
    if len(payload.new_password) < 6:
        raise HTTPException(400, "A nova senha precisa ter pelo menos 6 caracteres")
    await set_setting("admin_password_hash", hash_password(payload.new_password))
    return {"success": True}
