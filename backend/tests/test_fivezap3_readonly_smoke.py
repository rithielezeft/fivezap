# fivezap3 import: READ-ONLY smoke of auth + every GET endpoint used by sidebar/public pages
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_PASSWORD = "Rithi0518@"  # from /app/memory/test_credentials.md


@pytest.fixture(scope="module")
def auth():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PASSWORD}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# Health / public
def test_health():
    r = requests.get(f"{BASE_URL}/api/health", timeout=20)
    assert r.status_code == 200 and r.json()["status"] == "healthy"


def test_poller_health():
    r = requests.get(f"{BASE_URL}/api/health/poller", timeout=20)
    assert r.status_code == 200
    assert r.json()["running"] is True


# Auth
def test_login_ok():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert isinstance(d["access_token"], str) and len(d["access_token"]) > 10


def test_login_wrong():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "TEST_wrong"}, timeout=30)
    assert r.status_code == 401


def test_protected_requires_token():
    r = requests.get(f"{BASE_URL}/api/customers", timeout=20)
    assert r.status_code == 401


PROTECTED_GETS = [
    "/api/auth/me", "/api/auth/2fa/status",
    "/api/dashboard/stats", "/api/dashboard/activity", "/api/dashboard/attribution?days=30",
    "/api/dashboard/revenue-by-day?days=14", "/api/dashboard/balances",
    "/api/customers", "/api/trials", "/api/templates",
    "/api/whatsapp/status", "/api/whatsapp/qr",
    "/api/messages", "/api/messages/conversations",
    "/api/payments", "/api/payments/diagnostics", "/api/payment-accounts",
    "/api/raffle", "/api/settings", "/api/settings/discounts",
    "/api/analytics/geography", "/api/analytics/geography/customers",
    "/api/system/update-status", "/api/coupons", "/api/coupons/usages/recent",
    "/api/notifications", "/api/notifications/deliveries", "/api/notifications/dedup-log",
    "/api/finance/summary", "/api/queue",
    "/api/painel/users", "/api/painel/status", "/api/painel/package-ids",
    "/api/painel/expiring", "/api/painel/expired", "/api/reminders",
    "/api/openapi.json",
]


@pytest.mark.parametrize("path", PROTECTED_GETS)
def test_protected_get(auth, path):
    r = requests.get(f"{BASE_URL}{path}", headers=auth, timeout=90)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:300]}"
    r.json()


def test_public_raffle():
    r = requests.get(f"{BASE_URL}/api/public/raffle", timeout=30)
    assert r.status_code == 200, r.text[:300]


def test_public_pay_lookup_unknown():
    r = requests.get(f"{BASE_URL}/api/payments/customer/999999999", timeout=60)
    assert r.status_code in (200, 404), r.text[:300]
    print(r.status_code, r.text[:300])
