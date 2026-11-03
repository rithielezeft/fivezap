# Iteration 19: per-client-IP login lockout (CF-Connecting-IP / X-Forwarded-For) for /api/auth/login and
# /api/auth/email-login, plus /api/auth/methods default. Uses fake documentation IPs only.
import os
import random

import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_PW = "Rithi0518@"
R = random.randint(1, 250)  # random last octet so reruns don't collide
# Cloudflare in front of the preview rejects client-sent CF-Connecting-IP (error 1000/403), so CF-header
# tests hit the backend directly; XFF tests go through the public URL.
LOCAL = "http://localhost:8001"


def _login(pw, headers):
    base = LOCAL if "CF-Connecting-IP" in headers else BASE_URL
    return requests.post(f"{base}/api/auth/login", json={"password": pw}, headers=headers, timeout=30)


# methods endpoint default (no account linked)
def test_methods_shape():
    r = requests.get(f"{BASE_URL}/api/auth/methods", timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"email_login", "password_login"} and d["password_login"] is True


# /login lockout keyed on CF-Connecting-IP
def test_login_lockout_cf_ip_isolated():
    a = {"CF-Connecting-IP": f"203.0.113.{R}"}
    b = {"CF-Connecting-IP": f"203.0.113.{(R + 1) % 254 + 1}"}
    codes = [_login("wrong-pass", a).status_code for _ in range(8)]
    assert codes == [401] * 8, codes
    r9 = _login("wrong-pass", a)
    assert r9.status_code == 429, r9.text
    # even correct password blocked from locked IP
    assert _login(ADMIN_PW, a).status_code == 429
    ok = _login(ADMIN_PW, b)
    assert ok.status_code == 200, ok.text
    assert ok.json().get("access_token")


# /login lockout keyed on first X-Forwarded-For IP when CF header absent
def test_login_lockout_xff_isolated():
    a = {"X-Forwarded-For": f"198.51.100.{R}, 10.0.0.1"}
    b = {"X-Forwarded-For": f"198.51.100.{(R + 1) % 254 + 1}, 10.0.0.1"}
    codes = [_login("wrong-pass", a).status_code for _ in range(8)]
    assert codes == [401] * 8, codes
    assert _login("wrong-pass", a).status_code == 429
    ok = _login(ADMIN_PW, b)
    assert ok.status_code == 200, ok.text


# successful login resets counter for that IP
def test_login_success_resets_counter():
    h = {"CF-Connecting-IP": f"192.0.2.{R}"}
    for _ in range(7):
        assert _login("wrong-pass", h).status_code == 401
    assert _login(ADMIN_PW, h).status_code == 200
    for _ in range(7):
        assert _login("wrong-pass", h).status_code == 401
    assert _login(ADMIN_PW, h).status_code == 200


# /email-login lockout per forwarded IP
def test_email_login_lockout_isolated():
    a = {"CF-Connecting-IP": f"203.0.113.{(R + 50) % 254 + 1}"}
    b = {"X-Forwarded-For": f"198.51.100.{(R + 50) % 254 + 1}"}
    body = {"email": "qa-nobody@example.com", "password": "x"}
    url = f"{LOCAL}/api/auth/email-login"
    codes = [requests.post(url, json=body, headers=a, timeout=30).status_code for _ in range(8)]
    assert codes == [401] * 8, codes
    assert requests.post(url, json=body, headers=a, timeout=30).status_code == 429
    # other IP not locked (still 401, not 429)
    assert requests.post(f"{BASE_URL}/api/auth/email-login", json=body, headers=b, timeout=30).status_code == 401
    # password login from another IP not affected
    assert _login(ADMIN_PW, {"CF-Connecting-IP": f"192.0.2.{(R + 50) % 254 + 1}"}).status_code == 200


# real tester (no spoofed header) not locked by others
def test_real_client_not_locked():
    assert _login(ADMIN_PW, {}).status_code == 200


# email-login lockout via X-Forwarded-For through public URL
def test_email_login_lockout_xff_public():
    a = {"X-Forwarded-For": f"198.51.100.{(R + 100) % 254 + 1}"}
    body = {"email": "qa-nobody@example.com", "password": "x"}
    url = f"{BASE_URL}/api/auth/email-login"
    codes = [requests.post(url, json=body, headers=a, timeout=30).status_code for _ in range(9)]
    assert codes == [401] * 8 + [429], codes
    assert _login(ADMIN_PW, {}).status_code == 200
