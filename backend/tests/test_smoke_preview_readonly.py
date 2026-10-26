# Read-only smoke tests for WhatsFlow preview (auth, health, protected GETs, whatsapp status)
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_PASSWORD = "Rithi0518@"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PASSWORD}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"login failed {r.status_code} {r.text}")
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# Health
def test_health():
    r = requests.get(f"{BASE_URL}/api/health", timeout=20)
    assert r.status_code == 200, r.text
    print(r.json())


def test_root():
    r = requests.get(f"{BASE_URL}/api/", timeout=20)
    assert r.status_code == 200


# Auth
def test_login_success():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PASSWORD}, timeout=20)
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True and isinstance(d["access_token"], str) and d["token_type"] == "bearer"


def test_login_wrong_password():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "TEST_wrong"}, timeout=20)
    assert r.status_code == 401


def test_me(auth):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth, timeout=20)
    assert r.status_code == 200 and r.json()["authenticated"] is True


PROTECTED = [
    "/api/auth/me", "/api/customers", "/api/trials", "/api/whatsapp/status",
    "/api/settings", "/api/payments", "/api/coupons", "/api/dashboard/stats",
]


@pytest.mark.parametrize("path", PROTECTED)
def test_protected_rejects_without_token(path):
    r = requests.get(f"{BASE_URL}{path}", timeout=20)
    assert r.status_code in (401, 403), f"{path} -> {r.status_code}"


def test_invalid_token_rejected():
    r = requests.get(f"{BASE_URL}/api/customers", headers={"Authorization": "Bearer abc"}, timeout=20)
    assert r.status_code in (401, 403)


# WhatsApp
def test_whatsapp_status(auth):
    r = requests.get(f"{BASE_URL}/api/whatsapp/status", headers=auth, timeout=20)
    assert r.status_code == 200, r.text
    print(r.json())


def test_whatsapp_qr(auth):
    r = requests.get(f"{BASE_URL}/api/whatsapp/qr", headers=auth, timeout=20)
    assert r.status_code == 200, r.text
    print(str(r.json())[:200])


# Read-only GETs used by sidebar pages
READ_ENDPOINTS = [
    "/api/customers", "/api/trials", "/api/templates", "/api/messages",
    "/api/messages/conversations", "/api/payments", "/api/notifications",
    "/api/notifications/deliveries", "/api/coupons", "/api/settings",
    "/api/dashboard/stats", "/api/dashboard/activity", "/api/analytics/geography",
    "/api/reminders",
]


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_read_endpoints(auth, path):
    r = requests.get(f"{BASE_URL}{path}", headers=auth, timeout=30)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
