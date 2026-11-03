"""Email + password login via Supabase with authenticator-app (TOTP) 2-step verification."""
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from database import get_setting, set_setting
from services import supabase_auth as sb
from services.auth import create_token, require_admin

router = APIRouter(prefix="/api/auth", tags=["auth-supabase"])

TTL = 300
_pending = {}   # challenge_id -> {token, factor_id, exp, attempts}
_enrolls = {}   # enroll_id -> {token, factor_id, exp}
_failed = {}    # ip -> [count, first_ts]


class EmailLogin(BaseModel):
    email: str
    password: str


class CodePayload(BaseModel):
    challenge_id: str
    code: str


class PasswordPayload(BaseModel):
    password: str


class EnrollConfirm(BaseModel):
    enroll_id: str
    code: str


class DisablePayload(BaseModel):
    password: str
    code: str


class LegacyPayload(BaseModel):
    enabled: bool


def _need_config():
    if not sb.configured():
        raise HTTPException(503, "Supabase não configurado no servidor")


def _gc(store: dict):
    now = time.time()
    for k in [k for k, v in store.items() if v["exp"] < now]:
        store.pop(k, None)


async def _admin_email() -> str:
    return (await get_setting("supabase_admin_email") or "").strip().lower()


async def legacy_enabled() -> bool:
    if not await _admin_email():
        return True
    return (await get_setting("legacy_password_login") or "true") == "true"


async def _session_for_admin(password: str) -> dict:
    email = await _admin_email()
    if not email:
        raise HTTPException(400, "Crie a conta de e-mail primeiro")
    try:
        return await sb.sign_in(email, password)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _rate_limit(request: Request):
    fwd = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    ip = fwd or (request.client.host if request.client else "unknown")
    now = time.time()
    entry = _failed.get(ip, [0, now])
    if now - entry[1] > 900:
        entry = [0, now]
    if entry[0] >= 8:
        raise HTTPException(429, "Muitas tentativas. Tente novamente em 15 minutos.")
    return ip, entry


def _fail(ip, entry):
    entry[0] += 1
    _failed[ip] = entry


@router.get("/methods")
async def methods():
    return {"email_login": sb.configured() and bool(await _admin_email()), "password_login": await legacy_enabled()}


@router.post("/email-login")
async def email_login(payload: EmailLogin, request: Request):
    _need_config()
    ip, entry = _rate_limit(request)
    email = payload.email.strip().lower()
    admin = await _admin_email()
    if not admin or email != admin:
        _fail(ip, entry)
        raise HTTPException(401, "E-mail ou senha incorretos")
    try:
        session = await sb.sign_in(email, payload.password)
    except ValueError as e:
        _fail(ip, entry)
        raise HTTPException(401, str(e))
    _failed.pop(ip, None)
    factors = sb.verified_totp(session)
    if not factors:
        return {"success": True, "access_token": create_token(), "token_type": "bearer", "totp_missing": True}
    _gc(_pending)
    cid = secrets.token_urlsafe(24)
    _pending[cid] = {"token": session["access_token"], "factor_id": factors[0]["id"], "exp": time.time() + TTL, "attempts": 0}
    return {"success": True, "requires_totp": True, "challenge_id": cid}


@router.post("/email-login/verify")
async def email_login_verify(payload: CodePayload):
    _gc(_pending)
    p = _pending.get(payload.challenge_id)
    if not p:
        raise HTTPException(401, "Sessão expirada. Faça login novamente.")
    p["attempts"] += 1
    if p["attempts"] > 5:
        _pending.pop(payload.challenge_id, None)
        raise HTTPException(401, "Muitas tentativas. Faça login novamente.")
    try:
        await sb.challenge_and_verify(p["token"], p["factor_id"], payload.code)
    except ValueError as e:
        raise HTTPException(401, str(e))
    _pending.pop(payload.challenge_id, None)
    return {"success": True, "access_token": create_token(), "token_type": "bearer"}


@router.get("/supabase/status")
async def status(user=Depends(require_admin)):
    return {"configured": sb.configured(), "email": await _admin_email(),
            "totp_enabled": (await get_setting("supabase_totp_enabled") or "false") == "true",
            "password_login": await legacy_enabled()}


@router.post("/supabase/account")
async def link_account(payload: EmailLogin, user=Depends(require_admin)):
    _need_config()
    email = payload.email.strip().lower()
    if "@" not in email or len(payload.password) < 8:
        raise HTTPException(400, "Informe um e-mail válido e senha com pelo menos 8 caracteres")
    try:
        await sb.create_user(email, payload.password)
    except ValueError as e:
        if "already" not in str(e).lower() and "exists" not in str(e).lower():
            raise HTTPException(400, f"Supabase: {e}")
    try:
        session = await sb.sign_in(email, payload.password)
    except ValueError:
        raise HTTPException(400, "Esse e-mail já existe no Supabase com outra senha")
    await set_setting("supabase_admin_email", email)
    await set_setting("supabase_totp_enabled", "true" if sb.verified_totp(session) else "false")
    return {"ok": True, "email": email}


@router.post("/supabase/totp/start")
async def totp_start(payload: PasswordPayload, user=Depends(require_admin)):
    _need_config()
    session = await _session_for_admin(payload.password)
    if sb.verified_totp(session):
        raise HTTPException(400, "O autenticador já está ativo")
    try:
        f = await sb.enroll_totp(session)
    except ValueError as e:
        raise HTTPException(400, f"Supabase: {e}")
    _gc(_enrolls)
    eid = secrets.token_urlsafe(24)
    _enrolls[eid] = {"token": session["access_token"], "factor_id": f["id"], "exp": time.time() + 600}
    qr = f["totp"]["qr_code"]
    if not qr.startswith("data:"):
        qr = "data:image/svg+xml;utf-8," + quote(qr)
    return {"enroll_id": eid, "qr_code": qr, "secret": f["totp"]["secret"]}


@router.post("/supabase/totp/confirm")
async def totp_confirm(payload: EnrollConfirm, user=Depends(require_admin)):
    _gc(_enrolls)
    e = _enrolls.get(payload.enroll_id)
    if not e:
        raise HTTPException(400, "Cadastro expirado. Comece de novo.")
    try:
        await sb.challenge_and_verify(e["token"], e["factor_id"], payload.code)
    except ValueError as err:
        raise HTTPException(400, str(err))
    _enrolls.pop(payload.enroll_id, None)
    await set_setting("supabase_totp_enabled", "true")
    return {"ok": True}


@router.post("/supabase/totp/disable")
async def totp_disable(payload: DisablePayload, user=Depends(require_admin)):
    _need_config()
    session = await _session_for_admin(payload.password)
    factors = sb.verified_totp(session)
    if factors:
        try:
            s2 = await sb.challenge_and_verify(session["access_token"], factors[0]["id"], payload.code)
            await sb.unenroll(s2["access_token"], factors[0]["id"])
        except ValueError as e:
            raise HTTPException(400, str(e))
    await set_setting("supabase_totp_enabled", "false")
    return {"ok": True}


mirror_router = APIRouter(prefix="/api/supabase", tags=["supabase-mirror"])


@mirror_router.get("/mirror")
async def mirror_status():
    from services import supabase_mirror
    return {"configured": supabase_mirror.configured(), **supabase_mirror.state}


@mirror_router.post("/mirror/run")
async def mirror_run():
    from services import supabase_mirror
    if not supabase_mirror.configured():
        raise HTTPException(503, "Conexão com o banco do Supabase não configurada")
    try:
        counts = await supabase_mirror.sync_once()
    except Exception as e:
        supabase_mirror.state["last_error"] = str(e)[:300]
        raise HTTPException(502, f"Falha ao copiar para o Supabase: {str(e)[:200]}")
    return {"ok": True, "counts": counts, **supabase_mirror.state}


@router.put("/supabase/legacy")
async def set_legacy(payload: LegacyPayload, user=Depends(require_admin)):
    if not payload.enabled and (await get_setting("supabase_totp_enabled") or "false") != "true":
        raise HTTPException(400, "Ative o app autenticador antes de desativar o login só com senha")
    await set_setting("legacy_password_login", "true" if payload.enabled else "false")
    return {"ok": True, "password_login": payload.enabled}
