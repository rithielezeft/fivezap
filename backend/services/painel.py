"""Integration with painel.fun (api.controle.fit) via direct API + 2Captcha Turnstile."""
import asyncio
import logging
from typing import Optional

import httpx
from twocaptcha import TwoCaptcha

from database import get_setting

logger = logging.getLogger(__name__)

# In-memory token cache
_token_cache: dict = {"token": None, "expires_at": 0}


async def solve_turnstile() -> str:
    """Solve Cloudflare Turnstile via 2Captcha (sync API in thread)."""
    api_key = await get_setting("twocaptcha_key")
    sitekey = await get_setting("turnstile_sitekey")
    pageurl = await get_setting("turnstile_pageurl")
    if not api_key:
        raise RuntimeError("2Captcha key not configured")

    def _solve():
        solver = TwoCaptcha(api_key)
        result = solver.turnstile(sitekey=sitekey, url=pageurl)
        return result.get("code")

    logger.info("Solving Turnstile via 2Captcha (sitekey=%s)", sitekey)
    token = await asyncio.to_thread(_solve)
    logger.info("Turnstile solved.")
    return token


async def login(force: bool = False) -> str:
    """Login to painel.fun and return JWT bearer token."""
    import time

    if not force and _token_cache["token"] and _token_cache["expires_at"] > time.time():
        return _token_cache["token"]

    username = await get_setting("painel_username")
    password = await get_setting("painel_password")
    base = await get_setting("painel_base_url")

    if not username or not password:
        raise RuntimeError("Painel credentials not configured")

    turnstile_token = await solve_turnstile()

    payload = {
        "username": username,
        "password": password,
        "cf-turnstile-response": turnstile_token,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{base}/api/auth/sign-in",
            json=payload,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Origin": "https://painel.fun",
                "Referer": "https://painel.fun/login",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
            },
        )
        if resp.status_code >= 400:
            logger.error("Login failed %s: %s", resp.status_code, resp.text[:400])
            raise RuntimeError(f"Painel login failed: HTTP {resp.status_code} — {resp.text[:200]}")
        data = resp.json()
        token = data.get("token") or (data.get("user") or {}).get("token") or data.get("access_token") or data.get("data", {}).get("token")
        if not token:
            raise RuntimeError(f"Painel login: no token in response: {list(data.keys())}")

    _token_cache["token"] = token
    _token_cache["expires_at"] = time.time() + 20 * 60  # 20 min cache
    return token


async def create_trial(
    system_type: str,
    mac: Optional[str] = None,
    name: Optional[str] = None,
    whatsapp: Optional[str] = None,
) -> dict:
    """Create a trial user via POST /api/trial_users."""
    token = await login()
    base = await get_setting("painel_base_url")
    package_id = int(await get_setting("trial_package_id") or "61")

    payload: dict = {
        "package_id": package_id,
        "is_trial": True,
        "adult_channels": True,
    }
    if name:
        payload["name"] = name
    if whatsapp:
        payload["whatsapp"] = whatsapp
    if mac and system_type in ("iptv", "hybrid"):
        payload["mac"] = mac
    if system_type:
        payload["system_type"] = system_type

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{base}/api/trial_users",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 401:
            # Token invalid, force re-login and retry once
            token = await login(force=True)
            resp = await client.post(
                f"{base}/api/trial_users",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code >= 400:
            logger.error("Create trial failed %s: %s", resp.status_code, resp.text[:400])
            raise RuntimeError(f"Create trial failed: {resp.status_code} — {resp.text[:200]}")
        return resp.json()


async def list_users(limit: int = 500, search: str = None) -> list:
    """List users from painel.fun. Tries common endpoints and logs details."""
    token = await login()
    base = await get_setting("painel_base_url")
    headers = {"Authorization": f"Bearer {token}"}

    attempts = []
    async with httpx.AsyncClient(timeout=90) as client:
        # Try common endpoints. painel.fun uses /api/trial_users so users likely under similar path
        for path in ("/api/users", "/api/customers", "/api/clients", "/api/subscribers", "/api/panel_users"):
            try:
                params = {"limit": limit, "per_page": limit}
                if search:
                    params["search"] = search
                resp = await client.get(f"{base}{path}", headers=headers, params=params)
                if resp.status_code == 401:
                    fresh_token = await login(force=True)
                    resp = await client.get(f"{base}{path}", headers={"Authorization": f"Bearer {fresh_token}"}, params=params)
                attempts.append(f"{path} → {resp.status_code}")
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        logger.info("list_users success via %s (%d items)", path, len(data))
                        return data
                    if isinstance(data, dict):
                        items = data.get("data") or data.get("users") or data.get("items") or data.get("results")
                        if isinstance(items, list):
                            logger.info("list_users success via %s (%d items, nested)", path, len(items))
                            return items
            except Exception as e:
                attempts.append(f"{path} → EXC:{e}")
                logger.warning("list_users %s error: %s", path, e)
                continue
    raise RuntimeError("Nenhum endpoint de listagem funcionou. Tentativas: " + " | ".join(attempts))


async def renew_user(user_id: str, package_id: int) -> dict:
    """Renew existing user via painel API."""
    token = await login()
    base = await get_setting("painel_base_url")

    payload = {"package_id": package_id, "user_id": user_id}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{base}/api/renewal",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 401:
            token = await login(force=True)
            resp = await client.post(
                f"{base}/api/renewal",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code >= 400:
            logger.error("Renew failed %s: %s", resp.status_code, resp.text[:400])
            raise RuntimeError(f"Renew failed: {resp.status_code}")
        return resp.json()


# Package IDs mapping (from problem statement)
PACKAGE_IDS = {
    "iptv": {1: 17, 3: 43, 6: 56, 12: 58},
    "p2p": {1: 17, 3: 42, 6: 55, 12: 57},
    "hybrid": {1: 17, 3: 42, 6: 55, 12: 57},
}


def get_package_id(system_type: str, months: int) -> int:
    return PACKAGE_IDS.get(system_type, {}).get(months, 17)
