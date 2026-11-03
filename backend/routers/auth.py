"""Auth endpoints."""
import asyncio
import logging
import os
import re
import secrets
import time
from html import escape
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from services.auth import (
    verify_admin_password,
    create_token,
    require_admin,
    hash_password,
    verify_password,
)
from database import set_setting, get_setting
from services.email_sender import send_email

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

# Simple in-memory brute force map: ip -> [count, first_ts]
_failed = {}


class LoginPayload(BaseModel):
    password: str


class VerifyPayload(BaseModel):
    challenge_id: str
    code: str


class TwoFASetupPayload(BaseModel):
    email: str


class TwoFAConfirmPayload(BaseModel):
    code: str


class TwoFADisablePayload(BaseModel):
    password: str


# challenge_id -> {code_hash, exp, attempts}; setup -> {email, code_hash, exp, attempts}
_challenges = {}
_setup = {}
CODE_TTL = 600
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _mask(email: str) -> str:
    user, _, dom = email.partition("@")
    return f"{user[:2]}{'*' * max(len(user) - 2, 1)}@{dom}"


async def _send_code(email: str, code: str, purpose: str):
    brand = os.environ.get("EMAIL_FROM_NAME", "WhatsFlow")
    html = (
        '<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#111">'
        f'<p style="font-size:15px">Seu código para {escape(purpose)} no {escape(brand)}:</p>'
        f'<p style="font-size:32px;font-weight:bold;letter-spacing:8px;margin:16px 0">{escape(code)}</p>'
        '<p style="font-size:13px;color:#555">O código vale por 10 minutos. Se não foi você, troque sua senha.</p>'
        f'<p style="font-size:12px;color:#888">Enviado por {escape(brand)}. Nunca pedimos sua senha por e-mail.</p>'
        '</td></tr></table>'
    )
    await send_email(to=email, subject=f"{brand} — código de verificação", html=html)


def _check_code(entry: dict, code: str) -> bool:
    if not entry or entry["exp"] < time.time() or entry["attempts"] >= 5:
        return False
    entry["attempts"] += 1
    return verify_password(code.strip(), entry["code_hash"])


async def _twofa_on() -> bool:
    if os.environ.get("TWOFA_BYPASS", "").lower() == "true":
        return False
    return (await get_setting("twofa_enabled", "false")) == "true" and bool(await get_setting("twofa_email", ""))


class ChangePasswordPayload(BaseModel):
    current_password: str
    new_password: str


@router.post("/login")
async def login(payload: LoginPayload, request: Request):
    ip = request.client.host if request.client else "unknown"
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
    if await _twofa_on():
        email = await get_setting("twofa_email", "")
        code = f"{secrets.randbelow(1000000):06d}"
        cid = secrets.token_urlsafe(24)
        await _send_code(email, code, "entrar")
        _challenges[cid] = {"code_hash": hash_password(code), "exp": now + CODE_TTL, "attempts": 0}
        return {"success": True, "requires_2fa": True, "challenge_id": cid, "email_hint": _mask(email)}
    token = create_token()
    return {"success": True, "access_token": token, "token_type": "bearer"}


@router.post("/login/verify")
async def login_verify(payload: VerifyPayload):
    entry = _challenges.get(payload.challenge_id)
    if not _check_code(entry, payload.code):
        if entry and (entry["attempts"] >= 5 or entry["exp"] < time.time()):
            _challenges.pop(payload.challenge_id, None)
            raise HTTPException(401, "Código expirado. Faça login novamente.")
        raise HTTPException(401, "Código incorreto")
    _challenges.pop(payload.challenge_id, None)
    return {"success": True, "access_token": create_token(), "token_type": "bearer"}


@router.get("/2fa/status")
async def twofa_status(user=Depends(require_admin)):
    email = await get_setting("twofa_email", "")
    return {"enabled": await _twofa_on(), "email": email}


@router.post("/2fa/setup")
async def twofa_setup(payload: TwoFASetupPayload, user=Depends(require_admin)):
    email = payload.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "E-mail inválido")
    prev = _setup.get("admin")
    if prev and prev.get("sent_at", 0) > time.time() - 30:
        raise HTTPException(429, "Aguarde 30 segundos para reenviar o código")
    code = f"{secrets.randbelow(1000000):06d}"
    await _send_code(email, code, "ativar a verificação em 2 etapas")
    _setup["admin"] = {"email": email, "code_hash": hash_password(code), "exp": time.time() + CODE_TTL,
                       "attempts": 0, "sent_at": time.time()}
    return {"success": True, "email_hint": _mask(email)}


@router.post("/2fa/confirm")
async def twofa_confirm(payload: TwoFAConfirmPayload, user=Depends(require_admin)):
    entry = _setup.get("admin")
    if not _check_code(entry, payload.code):
        raise HTTPException(400, "Código incorreto ou expirado")
    await set_setting("twofa_email", entry["email"])
    await set_setting("twofa_enabled", "true")
    _setup.pop("admin", None)
    return {"success": True}


@router.post("/2fa/disable")
async def twofa_disable(payload: TwoFADisablePayload, user=Depends(require_admin)):
    if not await verify_admin_password(payload.password):
        raise HTTPException(400, "Senha incorreta")
    await set_setting("twofa_enabled", "false")
    return {"success": True}


@router.get("/me")
async def me(user=Depends(require_admin)):
    return {"authenticated": True, "sub": user.get("sub")}


@router.post("/change-password")
async def change_password(payload: ChangePasswordPayload, user=Depends(require_admin)):
    ok = await verify_admin_password(payload.current_password)
    if not ok:
        raise HTTPException(400, "Senha atual incorreta")
    if len(payload.new_password) < 6:
        raise HTTPException(400, "A nova senha precisa ter pelo menos 6 caracteres")
    await set_setting("admin_password_hash", hash_password(payload.new_password))
    return {"success": True}
