"""Supabase Auth (GoTrue REST) — email/password sign-in + TOTP factors, proxied by the backend."""
import os

import httpx


def configured() -> bool:
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SECRET_KEY"))


def _base() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1"


def _headers(token: str = None) -> dict:
    key = os.environ["SUPABASE_SECRET_KEY"]
    return {"apikey": key, "Authorization": f"Bearer {token or key}", "Content-Type": "application/json"}


def _msg(r: httpx.Response) -> str:
    try:
        d = r.json()
        return d.get("msg") or d.get("error_description") or d.get("message") or d.get("error") or r.text[:200]
    except Exception:
        return r.text[:200]


async def _call(method: str, path: str, token: str = None, **kw) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.request(method, _base() + path, headers=_headers(token), **kw)
    if r.status_code >= 400:
        raise ValueError(_msg(r))
    return r.json() if r.content else {}


async def sign_in(email: str, password: str) -> dict:
    try:
        return await _call("POST", "/token?grant_type=password", json={"email": email, "password": password})
    except ValueError as e:
        if "invalid" in str(e).lower():
            raise ValueError("E-mail ou senha incorretos") from e
        raise


async def create_user(email: str, password: str) -> dict:
    return await _call("POST", "/admin/users", json={"email": email, "password": password, "email_confirm": True})


def verified_totp(session: dict) -> list:
    return [f for f in (session.get("user") or {}).get("factors") or []
            if f.get("factor_type") == "totp" and f.get("status") == "verified"]


async def enroll_totp(session: dict) -> dict:
    token = session["access_token"]
    for f in (session.get("user") or {}).get("factors") or []:
        if f.get("factor_type") == "totp" and f.get("status") != "verified":
            await _call("DELETE", f"/factors/{f['id']}", token)
    return await _call("POST", "/factors", token, json={"factor_type": "totp", "friendly_name": "WhatsFlow", "issuer": "WhatsFlow"})


async def challenge_and_verify(token: str, factor_id: str, code: str) -> dict:
    ch = await _call("POST", f"/factors/{factor_id}/challenge", token)
    try:
        return await _call("POST", f"/factors/{factor_id}/verify", token, json={"challenge_id": ch["id"], "code": code.strip()})
    except ValueError as e:
        raise ValueError("Código do autenticador incorreto") from e


async def unenroll(token: str, factor_id: str):
    await _call("DELETE", f"/factors/{factor_id}", token)
