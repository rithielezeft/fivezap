"""Browser-based fallback for painel.fun operations that the HTTP API blocks.

Painel.fun has a `sessao_nao_renderizada` middleware that blocks POST /renew
even when we replicate the exact request sequence the SPA makes. The check
is fingerprint-based (TLS/JA3 or something curl_cffi can't fully emulate).

This module provides a Playwright-based fallback: it launches a real Chromium
process, logs in via the actual SPA flow (with 2Captcha for Turnstile), and
performs the renewal by calling the API from inside the rendered page context.
Painel treats this as a legitimate browser session because it IS one.

Usage:
    from services.painel_browser import renew_user_via_browser
    result = await renew_user_via_browser(user_id="228206603", months=1)
"""
import asyncio
import logging
import os
from typing import Optional

from database import get_setting

logger = logging.getLogger(__name__)

# Titles used by painel.fun to identify plan duration.
# Same mapping used in painel.py — keep in sync.
_PLAN_TITLE_TO_MONTHS = {
    "mensal": 1,
    "bimestral": 2,
    "trimestral": 3,
    "semestral": 6,
    "anual": 12,
}


def _find_chromium_path() -> Optional[str]:
    """Locate an installed Chromium binary on the Pi. Order:
    1. PAINEL_CHROMIUM_PATH env var (explicit override)
    2. /usr/lib/chromium/chromium  (Debian ARM64 package)
    3. /usr/bin/chromium           (Debian standard)
    4. /usr/bin/chromium-browser   (Ubuntu naming)
    5. Fallback to Playwright-bundled (only works if `playwright install` was run)
    """
    candidates = [
        os.environ.get("PAINEL_CHROMIUM_PATH"),
        "/usr/lib/chromium/chromium",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


async def _solve_turnstile_2captcha() -> str:
    """Solve painel.fun's Turnstile via 2Captcha (sync API in thread)."""
    from twocaptcha import TwoCaptcha
    api_key = await get_setting("twocaptcha_key")
    sitekey = await get_setting("turnstile_sitekey") or "0x4AAAAAACFhU7XJduqvbHH2"
    if not api_key:
        raise RuntimeError("2Captcha key not configured (settings.twocaptcha_key)")
    logger.info("Browser fallback: solving Turnstile via 2Captcha (sitekey=%s)", sitekey)
    solver = TwoCaptcha(api_key)
    result = await asyncio.to_thread(
        lambda: solver.turnstile(sitekey=sitekey, url="https://painel.fun/login")
    )
    return result["code"]


async def _pick_plan_id(plans: list, months: int) -> Optional[dict]:
    """Return the plan dict whose Portuguese title matches N months."""
    for p in (plans or []):
        title = (p.get("title") or "").strip().lower()
        if _PLAN_TITLE_TO_MONTHS.get(title) == months:
            return p
    return None


async def renew_user_via_browser(user_id: str, months: int = 1) -> dict:
    """Renew a painel.fun user by driving a real headless Chromium session.

    This is invoked as a fallback when the pure-HTTP path (painel.renew_user)
    fails with `sessao_nao_renderizada`. The browser instance is short-lived
    (spawned per call, closed on completion) to keep RAM usage predictable.

    Args:
        user_id: painel.fun user_id (string of digits)
        months: 1 / 3 / 6 / 12 (used to pick the correct plan title)

    Returns:
        The JSON response from POST /api/users/{user_id}/renew — same shape
        as `painel.renew_user`, so callers can treat it identically.

    Raises:
        RuntimeError: if login, Turnstile, or the actual renew all fail.
    """
    try:
        from playwright.async_api import async_playwright  # noqa
    except ImportError as exc:
        raise RuntimeError(
            "Playwright not installed. Run: pip install playwright && "
            "PLAYWRIGHT_BROWSERS_PATH=/pw-browsers playwright install chromium"
        ) from exc

    username = await get_setting("painel_username")
    password = await get_setting("painel_password")
    if not username or not password:
        raise RuntimeError("painel_username / painel_password not configured")

    chromium_path = _find_chromium_path()
    ts_token = await _solve_turnstile_2captcha()

    logger.info(
        "Browser fallback: launching chromium=%s for user=%s months=%s",
        chromium_path or "playwright-bundled", user_id, months,
    )

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        launch_kwargs = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        }
        if chromium_path:
            launch_kwargs["executable_path"] = chromium_path

        browser = await pw.chromium.launch(**launch_kwargs)
        try:
            ctx = await browser.new_context(
                locale="pt-BR",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            # Basic stealth
            await ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = await ctx.new_page()

            # 1. Navigate to login page
            logger.info("Browser: loading /login")
            await page.goto(
                "https://painel.fun/login",
                wait_until="domcontentloaded",
                timeout=45000,
            )
            await page.wait_for_timeout(1500)

            # 2. Log in via the SPA's own POST — this puts us in a rendered
            #    session state with all the browser characteristics painel
            #    checks (JA3 fingerprint, HTTP/2 stream ordering, etc.).
            logger.info("Browser: submitting login")
            login_result = await page.evaluate(
                """async ({user, pwd, ts}) => {
                    const r = await fetch('https://api.controle.fit/api/auth/sign-in', {
                        method: 'POST',
                        credentials: 'include',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({username: user, password: pwd, 'cf-turnstile-response': ts})
                    });
                    const txt = await r.text();
                    let data = {};
                    try { data = JSON.parse(txt); } catch(e){}
                    if (data.token) {
                        localStorage.setItem('token', data.token);
                        localStorage.setItem('auth-storage', JSON.stringify({
                            state: {token: data.token, data: data.user, status: 'authenticated'},
                            version: 0
                        }));
                    }
                    return {status: r.status, body: txt, token: data.token || null};
                }""",
                {"user": username, "pwd": password, "ts": ts_token},
            )
            if not login_result.get("token"):
                raise RuntimeError(
                    f"Browser login failed: HTTP {login_result.get('status')} — "
                    f"{(login_result.get('body') or '')[:250]}"
                )
            token = login_result["token"]
            logger.info("Browser: login OK, got token")

            # 3. Navigate to dashboard so the SPA fully initializes state.
            #    This is what makes the painel treat the session as "rendered".
            try:
                await page.goto(
                    "https://painel.fun/",
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                await page.wait_for_timeout(2500)
            except Exception as e:
                logger.warning("Browser: dashboard load timed out: %s (continuing)", e)

            # 4. Fetch price-overrides + prime endpoints (from inside the page).
            logger.info("Browser: priming session + fetching price-overrides")
            prep = await page.evaluate(
                """async ({uid, tok}) => {
                    const hdrs = {
                        'Authorization': 'Bearer ' + tok,
                        'Accept': 'application/json, text/plain, */*',
                    };
                    // These three GETs are what the SPA fires before opening the renew modal.
                    const [r1, r2, r3] = await Promise.all([
                        fetch('https://api.controle.fit/api/payments/plans?audience=client', {credentials:'include', headers: hdrs}),
                        fetch(`https://api.controle.fit/api/payments/price-overrides/client/${uid}`, {credentials:'include', headers: hdrs}),
                        fetch('https://api.controle.fit/api/reseller/check-message', {credentials:'include', headers: hdrs}),
                    ]);
                    const price = await r2.json();
                    return {
                        plans_status: r1.status,
                        price_status: r2.status,
                        checkmsg_status: r3.status,
                        price_data: price
                    };
                }""",
                {"uid": user_id, "tok": token},
            )
            logger.info(
                "Browser prime: plans=%s price=%s checkmsg=%s",
                prep.get("plans_status"), prep.get("price_status"), prep.get("checkmsg_status"),
            )

            price_data = ((prep.get("price_data") or {}).get("data") or {})
            plans = price_data.get("plans") or []
            matched = await _pick_plan_id(plans, months)
            if not matched:
                raise RuntimeError(
                    f"No plan matching {months} months for user {user_id}. "
                    f"Available: {[p.get('title') for p in plans]}"
                )
            plan_id = matched.get("plan_id")
            amount = matched.get("amount") if matched.get("amount") is not None else matched.get("default_amount")
            logger.info(
                "Browser: plan matched → plan_id=%s amount=%s (title=%s)",
                plan_id, amount, matched.get("title"),
            )

            # 5. Fire the actual renew POST from inside the same rendered page.
            #    The SPA also sends {package_id, plan_id, amount} together.
            renew_result = await page.evaluate(
                """async ({uid, pkg, plid, amt, tok}) => {
                    const r = await fetch(`https://api.controle.fit/api/users/${uid}/renew`, {
                        method: 'POST',
                        credentials: 'include',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + tok,
                        },
                        body: JSON.stringify({package_id: pkg, plan_id: plid, amount: amt})
                    });
                    const txt = await r.text();
                    let data = {};
                    try { data = JSON.parse(txt); } catch(e){}
                    return {status: r.status, body: txt, data: data};
                }""",
                {
                    "uid": user_id,
                    "pkg": 17,   # legacy package_id kept for compat — value only checked when plan_id missing
                    "plid": plan_id,
                    "amt": amount,
                    "tok": token,
                },
            )
            status = renew_result.get("status")
            body = renew_result.get("body") or ""
            if status >= 400:
                logger.error(
                    "Browser renew FAILED: HTTP %s — body=%s",
                    status, body[:400],
                )
                raise RuntimeError(f"Browser renew failed: HTTP {status} — {body[:250]}")

            logger.info("✅ Browser renew SUCCESS for user=%s", user_id)
            return renew_result.get("data") or {"status": status, "text": body[:200]}
        finally:
            await browser.close()
