"""Simple admin authentication (password-only) using bcrypt + JWT."""
import os
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt
from fastapi import HTTPException, Request

from database import get_setting, set_setting

JWT_ALGORITHM = "HS256"


def _secret() -> str:
    return os.environ.get("JWT_SECRET", "insecure-default-please-change")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_token(subject: str = "admin", days: int = 30) -> str:
    payload = {
        "sub": subject,
        "exp": datetime.now(timezone.utc) + timedelta(days=days),
        "type": "access",
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


async def seed_admin_password():
    """Ensure the admin password from ADMIN_PASSWORD env is set. Runs on startup."""
    env_pw = os.environ.get("ADMIN_PASSWORD")
    if not env_pw:
        return
    current_hash = await get_setting("admin_password_hash", "")
    if not current_hash or not verify_password(env_pw, current_hash):
        await set_setting("admin_password_hash", hash_password(env_pw))


async def verify_admin_password(plain: str) -> bool:
    stored = await get_setting("admin_password_hash", "")
    if not stored:
        return False
    return verify_password(plain, stored)


PUBLIC_PATH_PREFIXES = (
    "/api/auth/",
    "/api/public/",
    "/api/pay/customer/",
    "/api/whatsapp/incoming",
    "/api/health",
    "/api/uploads/",
    "/api/",  # exact root
)

# Endpoints that require Authorization Bearer (all admin endpoints)
def is_public(path: str, method: str = "GET") -> bool:
    if path == "/api/" or path == "/api/health":
        return True
    if path.startswith("/api/auth/"):
        return True
    if path.startswith("/api/public/"):
        return True
    # Public pay lookup — customers open /pay/{painel_id} from any browser.
    # This is the endpoint the /pay/{id} React page queries to render.
    if path.startswith("/api/payments/customer/"):
        return True
    if path.startswith("/api/pay/customer/"):  # legacy alias
        return True
    # Public payment creation from /pay/{id} page — customer clicks "Pagar"
    # (POST only — GET /api/payments must stay admin to protect payment history)
    if path == "/api/payments" and method.upper() == "POST":
        return True
    if path == "/api/whatsapp/incoming":
        return True
    if path.startswith("/api/uploads/"):
        return True
    # InfinitePay webhook must be public
    if path == "/api/payments/webhook":
        return True
    return False


async def require_admin(request: Request):
    """FastAPI dependency: raises 401 if not authenticated."""
    token = None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(401, "Não autenticado")
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(401, "Token inválido")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Sessão expirada")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Token inválido")
