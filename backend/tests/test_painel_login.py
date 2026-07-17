"""Standalone diagnostic script — run this ON the Raspberry Pi to isolate the 403.

Usage (from repo root on Pi):
    source /path/to/venv/bin/activate   # if you use one
    cd backend
    python tests/test_painel_login.py

It will:
  1. Read painel_username, painel_password, painel_base_url, twocaptcha_key
     from settings table in whatsflow.db.
  2. Solve Turnstile via 2Captcha.
  3. Attempt the login POST with curl_cffi impersonating Chrome 124.
  4. Print the full response headers (server, cf-ray, cf-mitigated) and body
     so we know exactly what Cloudflare is doing.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# Make backend/ importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curl_cffi import requests as cffi_requests  # noqa: E402
from twocaptcha import TwoCaptcha  # noqa: E402
import aiosqlite  # noqa: E402


DB_PATH = os.environ.get("SQLITE_PATH", str(ROOT / "whatsflow.db"))


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default


async def main():
    username = await get_setting("painel_username")
    password = await get_setting("painel_password")
    base = await get_setting("painel_base_url", "https://api.controle.fit")
    sitekey = await get_setting("turnstile_sitekey")
    pageurl = await get_setting("turnstile_pageurl", "https://painel.fun/login")
    api_key = await get_setting("twocaptcha_key")

    print(f"[cfg] base={base}")
    print(f"[cfg] username={username!r}")
    print(f"[cfg] sitekey={sitekey}")
    print(f"[cfg] pageurl={pageurl}")
    print(f"[cfg] 2captcha_key_set={bool(api_key)}")
    print()

    if not all([username, password, sitekey, api_key]):
        print("[FATAL] Missing settings. Configure them via the Settings page first.")
        return

    print("[1/2] Solving Turnstile via 2Captcha ...")
    solver = TwoCaptcha(api_key)
    tok = solver.turnstile(
        sitekey=sitekey,
        url=pageurl,
        useragent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    turnstile_token = tok.get("code")
    print(f"      turnstile_token = {turnstile_token[:40]}...\n")

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

    url = f"{base}/api/auth/sign-in"
    print(f"[2/2] POST {url}")
    print(f"      headers = {headers}")
    print()

    r = cffi_requests.post(
        url, json=payload, headers=headers,
        impersonate="chrome124", timeout=120,
    )

    print(f"===== RESPONSE =====")
    print(f"status  = {r.status_code}")
    print(f"server  = {r.headers.get('server')}")
    print(f"cf-ray  = {r.headers.get('cf-ray')}")
    print(f"cf-mitigated = {r.headers.get('cf-mitigated')}")
    print(f"content-type = {r.headers.get('content-type')}")
    print(f"--- all headers ---")
    for k, v in r.headers.items():
        print(f"  {k}: {v}")
    print(f"--- body (first 1500 chars) ---")
    print(r.text[:1500])
    print(f"====================")


if __name__ == "__main__":
    asyncio.run(main())
