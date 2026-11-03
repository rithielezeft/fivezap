# Read-only smoke tests for fivezap4 branch: health, auth, protected GETs (with/without token), public endpoints
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_PASSWORD = "Rithi0518@"


@pytest.fixture(scope="module")
def auth():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PASSWORD}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# Health
def test_health():
    r = requests.get(f"{BASE_URL}/api/health", timeout=20)
    assert r.status_code == 200, r.text


# Auth
def test_login_success():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PASSWORD}, timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    assert isinstance(d.get("access_token"), str) and len(d["access_token"]) > 10


def test_login_wrong_password():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "TEST_wrong_pw"}, timeout=20)
    assert r.status_code == 401, r.text


def test_me(auth):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth, timeout=20)
    assert r.status_code == 200 and r.json().get("authenticated") is True


READ = [
    "/api/customers", "/api/trials", "/api/templates", "/api/messages",
    "/api/messages/conversations", "/api/payments", "/api/notifications",
    "/api/notifications/deliveries", "/api/coupons", "/api/coupons/usages/recent",
    "/api/settings", "/api/settings/discounts", "/api/auth/methods",
    "/api/dashboard/stats", "/api/dashboard/activity", "/api/dashboard/attribution",
    "/api/dashboard/revenue-by-day", "/api/dashboard/balances",
    "/api/analytics/geography", "/api/reminders", "/api/queue", "/api/finance/summary",
    "/api/payment-accounts", "/api/raffle", "/api/whatsapp/status", "/api/whatsapp/qr",
    "/api/auth/2fa/status", "/api/system/update-status", "/api/painel/status",
]


# Authenticated GETs
@pytest.mark.parametrize("path", READ)
def test_read_with_token(auth, path):
    r = requests.get(f"{BASE_URL}{path}", headers=auth, timeout=40)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"


# Unauthenticated -> 401
@pytest.mark.parametrize("path", [x for x in READ if x != "/api/auth/methods"])  # methods is public (login page)
def test_read_without_token(path):
    r = requests.get(f"{BASE_URL}{path}", timeout=20)
    assert r.status_code == 401, f"{path} -> {r.status_code}"


# Public endpoints
def test_public_raffle():
    r = requests.get(f"{BASE_URL}/api/public/raffle", timeout=20)
    assert r.status_code == 200, r.text
