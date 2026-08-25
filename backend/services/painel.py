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


def _sanitize_for_painel(s: Optional[str], max_len: int = 60) -> str:
    """Strip characters that painel.fun's MySQL DB (utf8, not utf8mb4) rejects.

    Reported error: `Incorrect string value: '\\xF0\\x9F\\xA4\\x8D'` — that's
    the 4-byte UTF-8 encoding of an emoji (in this case 🤍). MySQL columns
    declared as `utf8` (not `utf8mb4`) refuse any 4-byte codepoint.

    We drop:
      - all characters above U+FFFF (all emojis and rarely-used scripts)
      - ASCII control chars (except newline/tab)
      - trailing whitespace
    We keep accented Latin characters (é, ç, ã, ü) — those are safe in utf8.
    """
    if not s:
        return ""
    out = []
    for ch in str(s):
        cp = ord(ch)
        # Drop 4-byte UTF-8 (emojis, ancient scripts) — MySQL utf8 refuses these
        if cp > 0xFFFF:
            continue
        # Drop C0 controls except common whitespace
        if cp < 0x20 and ch not in ("\t", "\n"):
            continue
        # Drop DEL and C1 controls
        if 0x7F <= cp <= 0x9F:
            continue
        out.append(ch)
    return "".join(out).strip()[:max_len]


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
    """Create a trial user via POST /api/trial_users.

    Username format: `{firstname}{last_2_digits_of_phone}new` (e.g., guilherme44new).
    Falls back to `test{phone_tail}{rand}` if name is missing.
    Password: 8 random chars.
    """
    import secrets
    import string
    import re
    import unicodedata

    token = await login()
    base = await get_setting("painel_base_url")
    package_id = int(await get_setting("trial_package_id") or "61")

    def _rand(n=6):
        return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(n))

    def _slugify_first_name(s: str) -> str:
        """Extract first alphabetic word, remove accents, keep only [a-z], max 15 chars.

        Skips leading words that have no ASCII letters (emojis, punctuation).
        """
        if not s:
            return ""
        for word in s.strip().split():
            # Remove accents (é→e, ã→a, ç→c)
            normalized = unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode("ascii")
            # Keep only letters
            cleaned = re.sub(r"[^a-zA-Z]", "", normalized).lower()
            if cleaned:
                return cleaned[:15]
        return ""

    # Sanitize name/whatsapp for painel.fun's MySQL (utf8 not utf8mb4).
    # Emojis in WhatsApp push names (🤍, 😊, etc.) cause 400 error:
    # "Incorrect string value: '\\xF0\\x9F...' for column".
    name = _sanitize_for_painel(name)
    whatsapp = _sanitize_for_painel(whatsapp, max_len=30)

    # Build username: {firstname}{last_2_digits}new
    digits_only = "".join(c for c in (whatsapp or "") if c.isdigit())
    last2 = digits_only[-2:] if len(digits_only) >= 2 else ""
    first_name = _slugify_first_name(name or "")

    if first_name and last2:
        username = f"{first_name}{last2}new"
    elif first_name:
        username = f"{first_name}{_rand(2)}new"
    else:
        # Fallback: no name available — use phone tail + random
        phone_tail = digits_only[-6:] or _rand(6)
        username = f"test{phone_tail}{_rand(3)}"

    password = _rand(8)

    # painel.fun expects `type` as integer: 1=IPTV, 2=P2P, 3=Hybrid.
    # The Hybrid trial payload also requires `isHybrid: true` and empty
    # username/password strings (painel generates them server-side after
    # change_system).
    type_int_map = {"iptv": 1, "p2p": 2, "hybrid": 3}
    type_int = type_int_map.get((system_type or "").lower(), 1)
    is_hybrid = (system_type or "").lower() == "hybrid"

    if is_hybrid:
        # Hybrid: no local credentials — painel creates them after change_system
        payload_username = ""
        payload_password = ""
    else:
        payload_username = username
        payload_password = password

    payload: dict = {
        "package_id": package_id,
        "username": payload_username,
        "password": payload_password,
        "max_connections": 1,
        "type": type_int,
        "isHybrid": is_hybrid,
        "as_number": whatsapp or "",
        "full_name": name or "",
    }
    # keep legacy fields for backward compat with older painel deployments
    if not is_hybrid:
        payload["is_trial"] = True
        payload["adult_channels"] = True
    payload["system"] = type_int
    if system_type:
        payload["system_type"] = system_type
    if name:
        payload["name"] = name
    if whatsapp:
        payload["whatsapp"] = whatsapp
        # Persist the client's WhatsApp in the painel `reseller_notes` free-text
        # field so the admin can easily lookup who the trial belongs to.
        # Notes = ONLY the phone number (raw digits, no name) so the notify-expired
        # regex extracts it cleanly. The client name stays in the `name` field.
        payload["reseller_notes"] = f"+{whatsapp}"
        payload["notes"] = f"+{whatsapp}"  # some panel versions use `notes`
    # MAC goes in the initial payload for IPTV+MAC and for Hybrid
    if mac and system_type in ("iptv", "hybrid"):
        payload["mac"] = mac
        payload["macaddr"] = mac

    logger.info(
        "create_trial payload username=%s type=%s isHybrid=%s mac=%s",
        payload_username or "(empty)", type_int, is_hybrid, mac,
    )

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

    # If username already exists on painel.fun, retry once with a short random suffix.
    # Skip for Hybrid — its username is empty by design (painel generates server-side).
    if not is_hybrid and resp.status_code >= 400 and any(
        keyword in resp.text.lower()
        for keyword in ("já existe", "already exist", "already taken", "duplicate", "username")
    ):
        logger.warning("Username '%s' rejected (%s), retrying with suffix", username, resp.text[:100])
        username_retry = f"{username[:12]}{_rand(2)}"
        payload["username"] = username_retry
        resp = await asyncio.to_thread(_post_trial, token)
        if resp.status_code < 400:
            username = username_retry  # store the new one for response

    # If painel rejects the password format ("O campo password format is
    # invalid."), auto-retry up to 3 times with a fresh random password.
    # This is 100% transient — the auto-generated password sometimes has
    # a character sequence painel's validator doesn't like.
    if not is_hybrid and resp.status_code >= 400 and "password" in resp.text.lower() and ("invalid" in resp.text.lower() or "format" in resp.text.lower()):
        for attempt in range(3):
            new_password = _rand(10)  # longer + fresh charset
            payload["password"] = new_password
            logger.warning(
                "Trial password rejected (attempt %d) — retrying with fresh password",
                attempt + 1,
            )
            resp = await asyncio.to_thread(_post_trial, token)
            if resp.status_code < 400:
                password = new_password  # store the accepted one
                break

    if resp.status_code >= 400:
        logger.error("Create trial failed %s: %s", resp.status_code, resp.text[:400])
        raise RuntimeError(f"Create trial failed: {resp.status_code} — {resp.text[:200]}")

    result = resp.json() if resp.text else {}
    if isinstance(result, dict):
        # For Hybrid, painel returns null username/password — don't force ours in
        if not is_hybrid:
            result.setdefault("username", username)
            result.setdefault("password", password)

    trial_id = result.get("id") or result.get("user_id")

    # ---- STEP 2: change_system for P2P (2) and Hybrid (3) ----
    # painel.fun creates every trial as IPTV (system=1) by default. To convert
    # to P2P or Hybrid we must call `change_system` right after creation.
    if trial_id and system_type in ("p2p", "hybrid"):
        target_int = type_int_map[system_type]
        try:
            await change_system(str(trial_id), target_int)
            result["system"] = target_int
            logger.info("change_system OK: user=%s → system_id=%s", trial_id, target_int)
        except Exception as e:
            logger.error("change_system FAILED for %s → %s: %s", trial_id, target_int, e)
            raise RuntimeError(f"Trial criado mas falha ao mudar sistema para {system_type.upper()}: {e}")

    # ---- STEP 3: DreamTV playlist for IPTV trials with MAC ----
    # Apenas IPTV (DreamTV) precisa validar o MAC em dreamtv.life e criar a
    # playlist. Hybrid NÃO faz esse passo — o macaddr já vai no trial_users e
    # o change_system=3 basta.
    if trial_id and mac and system_type == "iptv":
        try:
            valid = await validate_mac_dreamtv(mac)
            if not valid:
                raise RuntimeError(f"MAC {mac} inválido no DreamTV. Use um MAC de MAG (00:1A:79:...) ou Formuler.")
            await create_dreamtv_playlist(str(trial_id), mac)
            logger.info("dreamtv/playlist OK: user=%s mac=%s", trial_id, mac)
        except Exception as e:
            logger.error("DreamTV playlist FAILED for %s (mac=%s): %s", trial_id, mac, e)
            raise RuntimeError(f"Trial criado mas falha ao ativar DreamTV: {e}")

    # ---- STEP 4: Resync (P2P/Hybrid only) ----
    # For P2P and Hybrid systems, painel.fun requires a resync after trial creation
    # so the newly-created bouquet/playlist becomes active on the streaming server.
    # Without this, the client sees "invalid credentials" or empty channel list.
    if system_type in ("p2p", "hybrid"):
        try:
            rid = trial_id or username
            await resync_user(str(rid), system_type=system_type)
            logger.info("Resync OK for %s user id=%s", system_type, rid)
        except Exception as e:
            logger.warning("Resync failed for %s (non-fatal): %s", username, e)

    return result


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


async def change_system(user_id: str, system_id: int) -> dict:
    """Convert a freshly-created painel.fun trial to a target system.

    painel.fun creates every trial as IPTV (system=1) by default. To convert
    to P2P or Hybrid we must call this endpoint immediately after creation.

    Args:
        user_id: painel.fun trial user id (integer as string)
        system_id: 1=IPTV, 2=P2P, 3=Hybrid
    """
    token = await login()
    base = await get_setting("painel_base_url")

    def _post(tok):
        return cffi_requests.post(
            f"{base}/api/users/{user_id}/change_system",
            json={"system_id": system_id},
            headers={
                "Authorization": f"Bearer {tok}",
                "Origin": "https://painel.fun",
                "Referer": "https://painel.fun/",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
            },
            impersonate="chrome124",
            timeout=60,
        )

    resp = await asyncio.to_thread(_post, token)
    if resp.status_code == 401:
        token = await login(force=True)
        resp = await asyncio.to_thread(_post, token)

    if resp.status_code >= 400:
        raise RuntimeError(f"change_system HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "text": resp.text[:200]}


async def validate_mac_dreamtv(mac: str) -> bool:
    """Validate a MAC address against DreamTV.

    Endpoint: GET https://api.dreamtv.life/api/validate_mac?mac=XX:XX:XX:XX:XX:XX
    Returns True if the MAC is accepted, False otherwise.
    Uses curl_cffi to bypass Cloudflare fingerprinting if needed.
    """
    if not mac:
        return False

    def _get():
        return cffi_requests.get(
            "https://api.dreamtv.life/api/validate_mac",
            params={"mac": mac},
            impersonate="chrome124",
            timeout=30,
        )

    try:
        resp = await asyncio.to_thread(_get)
    except Exception as e:
        logger.warning("validate_mac_dreamtv exception: %s", e)
        return False

    if resp.status_code >= 400:
        logger.warning("validate_mac_dreamtv HTTP %s: %s", resp.status_code, resp.text[:200])
        return False

    try:
        data = resp.json()
    except Exception:
        # Some validators return plain text 'ok'/'true'
        return "ok" in resp.text.lower() or "true" in resp.text.lower() or "valid" in resp.text.lower()

    # Heuristic: accept common truthy shapes
    if isinstance(data, dict):
        # If any "valid"/"success"/"ok" key is explicitly set, respect it
        for key in ("valid", "success", "ok"):
            if key in data:
                return bool(data[key])
        if "status" in data:
            return data["status"] in ("ok", "success", "valid", 200, True)
        # Some panels return {"error": null} on success
        if "error" in data:
            return not data["error"]
        # If dict but no truthy key found, treat 200 response as valid
        return resp.status_code == 200
    if isinstance(data, bool):
        return data
    return resp.status_code == 200


async def create_dreamtv_playlist(user_id: str, mac: str) -> dict:
    """Create/associate a DreamTV playlist for a trial user with the given MAC.

    Endpoint: POST /api/users/{id}/dreamtv/playlist  with {"macaddr": mac}
    Called after MAC validation via api.dreamtv.life.
    """
    token = await login()
    base = await get_setting("painel_base_url")

    def _post(tok):
        return cffi_requests.post(
            f"{base}/api/users/{user_id}/dreamtv/playlist",
            json={"macaddr": mac, "mac": mac},
            headers={
                "Authorization": f"Bearer {tok}",
                "Origin": "https://painel.fun",
                "Referer": "https://painel.fun/",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
            },
            impersonate="chrome124",
            timeout=60,
        )

    resp = await asyncio.to_thread(_post, token)
    if resp.status_code == 401:
        token = await login(force=True)
        resp = await asyncio.to_thread(_post, token)

    if resp.status_code >= 400:
        raise RuntimeError(f"dreamtv/playlist HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "text": resp.text[:200]}


async def resync_user(user_id: str, system_type: Optional[str] = None) -> dict:
    """Trigger a resync on painel.fun for a newly-created P2P/Hybrid user.

    Uses the exact endpoints provided by painel.fun:
      - P2P:    POST /api/users/{id}/resync_p2p
      - Hybrid: POST /api/users/{id}/resync_hybrid

    Without this call, P2P/Hybrid trials show "invalid credentials" or an
    empty channel list because the bouquet/playlist isn't loaded on the
    streaming server yet.
    """
    token = await login()
    base = await get_setting("painel_base_url")
    hdrs = {
        "Origin": "https://painel.fun",
        "Referer": "https://painel.fun/",
        "Accept": "application/json, text/plain, */*",
    }

    def _post(path, tok):
        return cffi_requests.post(
            f"{base}{path}",
            headers={**hdrs, "Authorization": f"Bearer {tok}"},
            impersonate="chrome124",
            timeout=60,
        )

    # Map system_type → exact resync endpoint. Default to p2p for backward compat.
    endpoint_map = {
        "p2p": f"/api/users/{user_id}/resync_p2p",
        "hybrid": f"/api/users/{user_id}/resync_hybrid",
    }
    key = (system_type or "p2p").lower()
    path = endpoint_map.get(key, endpoint_map["p2p"])

    try:
        resp = await asyncio.to_thread(_post, path, token)
        if resp.status_code == 401:
            new_token = await login(force=True)
            resp = await asyncio.to_thread(_post, path, new_token)
        if resp.status_code < 400:
            logger.info("Resync OK via %s (HTTP %s)", path, resp.status_code)
            return {"endpoint": path, "status": resp.status_code, "response": resp.text[:300]}
        logger.error("Resync failed %s HTTP %s: %s", path, resp.status_code, resp.text[:300])
        raise RuntimeError(f"Resync failed {path}: HTTP {resp.status_code} — {resp.text[:200]}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Resync exception on {path}: {e}")



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
    # `/api/profile` is the actual endpoint used by painel.fun frontend
    # (baseURL=https://api.controle.fit/api, then GET /profile). It returns
    # `{id, username, credits, credits_double, bonus_credits, ...}` — this is
    # the ONLY endpoint with real reseller balance. The others are legacy
    # probes kept as fallback.
    for path in ("/api/profile", "/api/user/me", "/api/me", "/api/account", "/api/user", "/api/credits", "/api/dashboard"):
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


async def get_reseller_balance() -> dict:
    """Return a normalized {balance, currency, raw} from painel.fun.

    The `/api/profile` endpoint returns the reseller `credits` (main balance)
    and `bonus_credits` (extra). We surface both so the dashboard shows the
    real, current wallet state.
    """
    info = await get_account_info()
    data = info.get("data") or {}
    # Some painel builds nest under 'user' or 'data'
    d = data.get("user") or data.get("data") or data
    if not isinstance(d, dict):
        return {"balance": None, "currency": "BRL", "raw": str(d)[:200],
                "source_endpoint": info.get("path"),
                "note": "resposta inesperada do painel"}

    # Main credits balance
    balance = None
    raw_field = None
    for key in ("credits", "balance", "saldo", "available_balance", "wallet"):
        v = d.get(key)
        if v is not None:
            try:
                balance = float(v)
                raw_field = key
                break
            except (TypeError, ValueError):
                pass

    if balance is None:
        return {"balance": None, "currency": "BRL",
                "raw": {k: d.get(k) for k in list(d.keys())[:20]},
                "source_endpoint": info.get("path"),
                "note": "campo de saldo não encontrado na resposta"}

    result = {
        "balance": balance,
        "currency": "BRL",
        "raw_field": raw_field,
        "source_endpoint": info.get("path"),
        "username": d.get("username"),
    }
    # Extras — bonus credits (given by upline) and last recharge info
    bonus = d.get("bonus_credits")
    if bonus is not None:
        try:
            result["bonus_credits"] = float(bonus)
        except (TypeError, ValueError):
            pass
    last_recharge = d.get("credits_last_recharge")
    if last_recharge is not None:
        try:
            result["last_recharge_credits"] = float(last_recharge)
        except (TypeError, ValueError):
            pass
    if d.get("date_last_recharge"):
        result["last_recharge_at"] = d.get("date_last_recharge")
    return result


async def _prime_renewal_session(user_id: str, token: str, base: str) -> None:
    """Make the exact pre-`/renew` request sequence the SPA makes.
    Painel's `sessao_nao_renderizada` middleware requires ALL of these calls
    (in this order) before it will accept POST /api/users/{id}/renew.

    Confirmed via DevTools Network capture (2026-08-25):
      1. GET /api/payments/plans?audience=client
      2. GET /api/payments/price-overrides/client/{user_id}
      3. GET /api/reseller/check-message
      4. POST /api/users/{user_id}/renew   ← the actual renewal (caller does this)

    Errors are swallowed (best-effort) — the whole point is to touch these
    endpoints, not to consume their results. If any single call 500s the
    session may still be primed.
    """
    hdrs = {
        "Authorization": f"Bearer {token}",
        "Origin": "https://painel.fun",
        "Referer": "https://painel.fun/",
        "Accept": "application/json, text/plain, */*",
    }
    endpoints = [
        f"{base}/api/payments/plans?audience=client",
        f"{base}/api/payments/price-overrides/client/{user_id}",
        f"{base}/api/reseller/check-message",
    ]
    for url in endpoints:
        try:
            r = await asyncio.to_thread(
                cffi_requests.get, url,
                headers=hdrs, impersonate="chrome124", timeout=30,
            )
            logger.info("prime session step: GET %s → HTTP %s", url.rsplit("/", 2)[-1], r.status_code)
        except Exception as e:
            logger.warning("prime session step failed for %s: %s", url, e)


async def get_price_overrides(user_id: str) -> dict:
    """Fetch the price/plan overrides for a specific user.

    Endpoint: GET /api/payments/price-overrides/client/{user_id}

    Response shape (2026-08 update):
        {"success": true, "data": {
            "plans": [
                {"plan_id": 41, "title": "Mensal", "default_amount": 30, "amount": 30, "overridden": false},
                {"plan_id": 42, "title": "Trimestral", "default_amount": 90, "amount": 90, "overridden": false},
                {"plan_id": 43, "title": "Semestral", "default_amount": 162.9, "amount": 162.9, "overridden": false},
                {"plan_id": 44, "title": "Anual", "default_amount": 300, "amount": 300, "overridden": false},
            ],
            "assigned_plan_id": null
        }}
    """
    token = await login()
    base = await get_setting("painel_base_url")

    def _get(tok):
        return cffi_requests.get(
            f"{base}/api/payments/price-overrides/client/{user_id}",
            headers={
                "Authorization": f"Bearer {tok}",
                "Origin": "https://painel.fun",
                "Referer": "https://painel.fun/",
                "Accept": "application/json, text/plain, */*",
            },
            impersonate="chrome124",
            timeout=60,
        )

    resp = await asyncio.to_thread(_get, token)
    if resp.status_code == 401:
        token = await login(force=True)
        resp = await asyncio.to_thread(_get, token)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"get_price_overrides failed: HTTP {resp.status_code} — {resp.text[:200]}"
        )
    data = resp.json()
    return data.get("data") if isinstance(data, dict) and "data" in data else data


# Maps plan title (as returned by /price-overrides) to number of months.
# Painel returns Portuguese titles.
_PLAN_TITLE_TO_MONTHS = {
    "mensal": 1,
    "bimestral": 2,
    "trimestral": 3,
    "semestral": 6,
    "anual": 12,
}


def _pick_plan_by_months(plans: list, months: int) -> dict | None:
    """Given the plans list from /price-overrides, pick the one that matches N months."""
    if not plans:
        return None
    for p in plans:
        title = (p.get("title") or "").strip().lower()
        if _PLAN_TITLE_TO_MONTHS.get(title) == months:
            return p
    return None


async def renew_user(user_id: str, package_id: int, months: int | None = None) -> dict:
    """Renew existing user via painel API.

    2026-08 UPDATE — Painel added `sessao_nao_renderizada` middleware on POST /renew.
    New required flow:
      1. GET /api/payments/price-overrides/client/{user_id}  ← primes session
      2. POST /api/users/{user_id}/renew  with  {plan_id, amount}   ← new body shape

    Legacy behavior (kept as fallback if new flow fails):
      POST /api/users/{user_id}/renew  with  {package_id: <int>}

    Args:
        user_id: painel.fun user id (integer as string)
        package_id: legacy package id — used to derive months if `months` not given
        months: subscription period in months (1/3/6/12). If missing, we try to infer
                from package_id via reverse PACKAGE_IDS lookup.
    """
    token = await login()
    base = await get_setting("painel_base_url")

    # Derive months from package_id if not provided
    if months is None:
        for _sys, mapping in PACKAGE_IDS.items():
            for m, pkg in mapping.items():
                if pkg == package_id:
                    months = m
                    break
            if months is not None:
                break
    if months is None:
        months = 1  # safest default

    # STEP 1: Fetch price-overrides + prime session
    # (DevTools capture confirmed the SPA also hits /payments/plans and
    # /reseller/check-message BEFORE /renew — the middleware requires this exact sequence.)
    price_data = None
    plan_id = None
    amount = None
    try:
        # First fetch the plan pricing (also primes part of the session).
        price_data = await get_price_overrides(user_id)
        plans = (price_data or {}).get("plans") or []
        matched = _pick_plan_by_months(plans, months)
        if matched:
            plan_id = matched.get("plan_id")
            amount = matched.get("amount") if matched.get("amount") is not None else matched.get("default_amount")
            logger.info(
                "price-overrides matched for user=%s months=%s → plan_id=%s amount=%s",
                user_id, months, plan_id, amount,
            )
        else:
            logger.warning(
                "price-overrides had no plan matching %s months for user %s (plans=%s)",
                months, user_id, [p.get("title") for p in plans],
            )
    except Exception as e:
        logger.warning("get_price_overrides failed for user %s: %s (will fallback)", user_id, e)

    # Now fire the OTHER two priming calls (plans + check-message) — these are
    # required for painel's `sessao_nao_renderizada` middleware to accept /renew.
    try:
        await _prime_renewal_session(user_id, token, base)
    except Exception as e:
        logger.warning("_prime_renewal_session failed: %s (will still try /renew)", e)

    # STEP 2: Call /renew.  Prefer new body shape; fall back to legacy on 4xx.
    def _post_renew(tok, body):
        return cffi_requests.post(
            f"{base}/api/users/{user_id}/renew",
            json=body,
            headers={
                "Authorization": f"Bearer {tok}",
                "Origin": "https://painel.fun",
                "Referer": "https://painel.fun/",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
            },
            impersonate="chrome124",
            timeout=90,
        )

    # Build the body — painel.fun (2026-08) requires ALL THREE fields together:
    #   {package_id, plan_id, amount}
    # (Confirmed via DevTools capture of the real SPA request.)
    # Fallback to legacy {package_id} only if we couldn't resolve plan_id from
    # price-overrides.
    bodies_to_try = []
    if plan_id is not None:
        bodies_to_try.append({"package_id": package_id, "plan_id": plan_id, "amount": amount})
    bodies_to_try.append({"package_id": package_id})

    last_resp = None
    last_body_used = None
    attempts_log = []
    for body in bodies_to_try:
        resp = await asyncio.to_thread(_post_renew, token, body)
        if resp.status_code == 401:
            token = await login(force=True)
            resp = await asyncio.to_thread(_post_renew, token, body)
        last_resp = resp
        last_body_used = body
        # Log every attempt so we can see BOTH body shapes if both fail
        attempts_log.append(f"body={body} → HTTP {resp.status_code}: {(resp.text or '')[:200]}")
        # Stop if success OR if this is a real 4xx that isn't sessao_nao_renderizada
        if resp.status_code < 400:
            break
        body_lower = (resp.text or "").lower()
        if "sessao_nao_renderizada" not in body_lower:
            # Genuine error, no point trying the other body shape
            break

    resp = last_resp
    if resp.status_code >= 400:
        logger.error(
            "❌ RENEW FAILED — all attempts:\n  %s",
            "\n  ".join(attempts_log),
        )
        raise RuntimeError(f"Renew failed: HTTP {resp.status_code} — {resp.text[:200]}")
    try:
        data = resp.json()
    except Exception:
        return {"status": resp.status_code, "text": resp.text[:200]}

    # SOFT-FAILURE DETECTION: painel.fun sometimes returns HTTP 200 with an
    # error body like {"message": "You do not have access to renew this user"}
    # instead of a proper 4xx. If we don't catch this here, the payment gets
    # marked "renewed" and the client receives "Renovação confirmada" even
    # though the panel never actually renewed the subscription.
    if isinstance(data, dict):
        error_msg = None
        # Painel.fun sometimes wraps the real body in `original` (Rails-style).
        # Also inspect that nested payload if present.
        candidates = [data]
        nested = data.get("original")
        if isinstance(nested, dict):
            candidates.append(nested)
        # Positive success indicator anywhere?
        has_success = any(
            (c.get("expires_at") or c.get("exp_date") or c.get("expiration"))
            for c in candidates
        )
        if not has_success:
            for c in candidates:
                for key in ("message", "error", "detail"):
                    v = c.get(key)
                    if v and isinstance(v, str):
                        lowered = v.lower()
                        if any(bad in lowered for bad in (
                            "not have access", "no permission", "denied",
                            "not found", "does not exist", "invalid",
                            "error", "erro", "falha", "failed",
                        )):
                            error_msg = v
                            break
                if error_msg:
                    break
        if error_msg:
            logger.error("Renew soft-failed for user %s: %s", user_id, error_msg)
            raise RuntimeError(f"Renew rejected by painel: {error_msg}")

    return data


# Package IDs mapping (from problem statement)
PACKAGE_IDS = {
    "iptv": {1: 17, 3: 43, 6: 56, 12: 58},
    "p2p": {1: 17, 3: 42, 6: 55, 12: 57},
    "hybrid": {1: 17, 3: 42, 6: 55, 12: 57},
}


def get_package_id(system_type: str, months: int) -> int:
    return PACKAGE_IDS.get(system_type, {}).get(months, 17)
