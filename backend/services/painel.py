"""Integration with painel.fun (api.controle.fit) via direct API + 2Captcha Turnstile."""
import asyncio
import logging
from typing import Optional

from curl_cffi import requests as cffi_requests
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
        # Pass userAgent + action for accurate Turnstile validation
        result = solver.turnstile(
            sitekey=sitekey,
            url=pageurl,
            useragent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
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

    headers = {
        "Origin": "https://painel.fun",
        "Referer": "https://painel.fun/login",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
    }

    def _post_login():
        return cffi_requests.post(
            f"{base}/api/auth/sign-in",
            json=payload,
            headers=headers,
            impersonate="chrome124",
            timeout=120,
        )

    logger.info("POST %s/api/auth/sign-in (curl_cffi impersonate=chrome124)", base)
    resp = await asyncio.to_thread(_post_login)

    if resp.status_code >= 400:
        # Rich diagnostic: dump response headers so we know if Cloudflare blocked us
        srv = resp.headers.get("server", "?")
        cf_ray = resp.headers.get("cf-ray", "?")
        cf_mit = resp.headers.get("cf-mitigated", "?")
        logger.error(
            "Login failed HTTP %s | server=%s cf-ray=%s cf-mitigated=%s | body=%s",
            resp.status_code, srv, cf_ray, cf_mit, resp.text[:500],
        )
        raise RuntimeError(
            f"Painel login failed: HTTP {resp.status_code} (server={srv}, cf-ray={cf_ray}) — {resp.text[:200]}"
        )

    try:
        data = resp.json()
    except Exception as e:
        logger.error("Login response not JSON: %s | body=%s", e, resp.text[:400])
        raise RuntimeError(f"Painel login: response is not JSON — {resp.text[:200]}")

    token = (
        data.get("token")
        or (data.get("user") or {}).get("token")
        or data.get("access_token")
        or data.get("data", {}).get("token")
    )
    if not token:
        raise RuntimeError(f"Painel login: no token in response. Keys={list(data.keys())} Body={str(data)[:300]}")

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

    def _post_trial(tok):
        return cffi_requests.post(
            f"{base}/api/trial_users",
            json=payload,
            headers={
                "Authorization": f"Bearer {tok}",
                "Origin": "https://painel.fun",
                "Referer": "https://painel.fun/",
                "Accept": "application/json, text/plain, */*",
            },
            impersonate="chrome124",
            timeout=90,
        )

    resp = await asyncio.to_thread(_post_trial, token)
    if resp.status_code == 401:
        token = await login(force=True)
        resp = await asyncio.to_thread(_post_trial, token)
    if resp.status_code >= 400:
        logger.error("Create trial failed %s: %s", resp.status_code, resp.text[:400])
        raise RuntimeError(f"Create trial failed: {resp.status_code} — {resp.text[:200]}")
    return resp.json()


async def list_users(limit: int = 10000, search: str = None) -> list:
    """List ALL users from painel.fun (api.controle.fit).

    Uses actual painel.fun API contract:
      - Params: `page`, `per` (NOT per_page), `reseller`, `order_by`
      - Response: `{ data: [...], meta: {page, per, pages, count, total} }`
      - Filters by the logged-in reseller (painel_username).
    """
    token = await login()
    base = await get_setting("painel_base_url")
    reseller = await get_setting("painel_username")

    def _get(path, params, tok):
        return cffi_requests.get(
            f"{base}{path}",
            headers={
                "Authorization": f"Bearer {tok}",
                "Origin": "https://painel.fun",
                "Referer": "https://painel.fun/",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            },
            params=params,
            impersonate="chrome124",
            timeout=90,
        )

    per_page = 200  # panel supports up to a few hundred per page
    all_items: list = []

    base_params: dict = {
        "page": 1,
        "per": per_page,
        "order_by": "exp_date,asc",  # oldest expiration first (most urgent)
    }
    if reseller:
        base_params["reseller"] = reseller
    if search:
        base_params["search"] = search

    try:
        resp = await asyncio.to_thread(_get, "/api/users", dict(base_params), token)
        if resp.status_code == 401:
            token = await login(force=True)
            resp = await asyncio.to_thread(_get, "/api/users", dict(base_params), token)

        if resp.status_code != 200:
            raise RuntimeError(
                f"list_users GET /api/users HTTP {resp.status_code} — {resp.text[:200]}"
            )

        payload = resp.json()
        items = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(items, list):
            all_items.extend(items)

        meta = payload.get("meta") if isinstance(payload, dict) else None
        pages = None
        total = None
        if isinstance(meta, dict):
            pages = meta.get("pages")
            total = meta.get("total")

        logger.info(
            "list_users page 1: %d items (total=%s, pages=%s, reseller=%s)",
            len(items or []), total, pages, reseller,
        )

        # Fetch remaining pages
        if pages and pages > 1:
            pages_to_fetch = min(int(pages), 200)  # safety cap
            for p in range(2, pages_to_fetch + 1):
                page_params = dict(base_params)
                page_params["page"] = p
                r = await asyncio.to_thread(_get, "/api/users", page_params, token)
                if r.status_code == 401:
                    token = await login(force=True)
                    r = await asyncio.to_thread(_get, "/api/users", page_params, token)
                if r.status_code != 200:
                    logger.warning("Pagination stopped at page %d: HTTP %d", p, r.status_code)
                    break
                pd = r.json()
                more = pd.get("data") if isinstance(pd, dict) else pd
                if not more:
                    break
                all_items.extend(more)
                if total and len(all_items) >= total:
                    break

        if limit and len(all_items) > limit:
            all_items = all_items[:limit]

        logger.info("list_users complete: %d total items", len(all_items))
        return all_items
    except Exception as e:
        logger.exception("list_users failed")
        raise RuntimeError(f"Falha ao listar usuários: {e}")


async def get_account_info() -> dict:
    """Fetch account info + credits from painel.fun."""
    token = await login()
    base = await get_setting("painel_base_url")

    def _get(path, tok):
        return cffi_requests.get(
            f"{base}{path}",
            headers={
                "Authorization": f"Bearer {tok}",
                "Origin": "https://painel.fun",
                "Referer": "https://painel.fun/",
                "Accept": "application/json, text/plain, */*",
            },
            impersonate="chrome124",
            timeout=60,
        )

    attempts = []
    for path in ("/api/user/me", "/api/me", "/api/account", "/api/user", "/api/credits", "/api/dashboard"):
        try:
            resp = await asyncio.to_thread(_get, path, token)
            attempts.append(f"{path}={resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                return {"path": path, "data": data, "attempts": attempts}
        except Exception as e:
            attempts.append(f"{path}=EXC")
            logger.warning("account info %s failed: %s", path, e)
    raise RuntimeError("Nenhum endpoint de conta encontrado. Tentativas: " + " | ".join(attempts))


async def renew_user(user_id: str, package_id: int) -> dict:
    """Renew existing user via painel API."""
    token = await login()
    base = await get_setting("painel_base_url")

    payload = {"package_id": package_id, "user_id": user_id}

    def _post_renew(tok):
        return cffi_requests.post(
            f"{base}/api/renewal",
            json=payload,
            headers={
                "Authorization": f"Bearer {tok}",
                "Origin": "https://painel.fun",
                "Referer": "https://painel.fun/",
                "Accept": "application/json, text/plain, */*",
            },
            impersonate="chrome124",
            timeout=90,
        )

    resp = await asyncio.to_thread(_post_renew, token)
    if resp.status_code == 401:
        token = await login(force=True)
        resp = await asyncio.to_thread(_post_renew, token)
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
