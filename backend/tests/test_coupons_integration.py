"""Integration tests for Coupons feature — hits the live backend on REACT_APP_BACKEND_URL.

Covers:
- Auth guard on admin endpoints
- CRUD (create/list/update/delete) + code normalization + 50% cap + duplicate 409
- Public /validate endpoint
- 28-day cooldown enforcement
- Coupon applied on POST /api/payments and usage recorded on payment confirmation
"""
import os
import time
import uuid
import pytest
import requests
from datetime import datetime, timezone, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_PASSWORD = "Rithi0518@"


def _tag():
    return f"TEST{uuid.uuid4().hex[:6].upper()}"


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def admin(api, admin_token):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json",
                      "Authorization": f"Bearer {admin_token}"})
    return s


# ------------- AUTH GUARD -------------

def test_list_coupons_requires_auth(api):
    r = requests.get(f"{BASE_URL}/api/coupons", timeout=15)
    assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}: {r.text}"


def test_list_coupons_with_auth(admin):
    r = admin.get(f"{BASE_URL}/api/coupons", timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ------------- CRUD -------------

@pytest.fixture(scope="module")
def coupon_ids():
    return []


def test_create_coupon_normalizes_code_and_caps_at_50(admin, coupon_ids):
    code = _tag().lower()  # lower to prove normalization
    r = admin.post(f"{BASE_URL}/api/coupons",
                   json={"code": code, "discount_percent": 99, "active": True}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == code.upper()
    assert body["discount_percent"] == 50  # capped
    assert body["active"] is True
    assert body["id"]
    coupon_ids.append(body["id"])

    # Verify via GET
    r2 = admin.get(f"{BASE_URL}/api/coupons", timeout=15)
    found = [c for c in r2.json() if c["id"] == body["id"]]
    assert found and found[0]["code"] == code.upper()


def test_create_duplicate_returns_409(admin, coupon_ids):
    code = _tag()
    r = admin.post(f"{BASE_URL}/api/coupons",
                   json={"code": code, "discount_percent": 15, "active": True}, timeout=15)
    assert r.status_code == 200
    coupon_ids.append(r.json()["id"])
    r2 = admin.post(f"{BASE_URL}/api/coupons",
                    json={"code": code, "discount_percent": 20, "active": True}, timeout=15)
    assert r2.status_code == 409


def test_update_coupon(admin, coupon_ids):
    code = _tag()
    r = admin.post(f"{BASE_URL}/api/coupons",
                   json={"code": code, "discount_percent": 10, "active": True}, timeout=15)
    cid = r.json()["id"]
    coupon_ids.append(cid)
    r2 = admin.put(f"{BASE_URL}/api/coupons/{cid}",
                   json={"discount_percent": 25, "active": False}, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["discount_percent"] == 25
    assert r2.json()["active"] is False


def test_delete_coupon(admin):
    code = _tag()
    r = admin.post(f"{BASE_URL}/api/coupons",
                   json={"code": code, "discount_percent": 10, "active": True}, timeout=15)
    cid = r.json()["id"]
    r2 = admin.delete(f"{BASE_URL}/api/coupons/{cid}", timeout=15)
    assert r2.status_code == 200
    # confirm gone
    r3 = admin.get(f"{BASE_URL}/api/coupons", timeout=15)
    assert not any(c["id"] == cid for c in r3.json())


# ------------- PUBLIC /validate -------------

def test_validate_public_no_auth(api, admin, coupon_ids):
    code = _tag()
    r = admin.post(f"{BASE_URL}/api/coupons",
                   json={"code": code, "discount_percent": 20, "active": True}, timeout=15)
    assert r.status_code == 200
    cid = r.json()["id"]
    coupon_ids.append(cid)

    # Public call, no auth header
    cust = f"testcust_{uuid.uuid4().hex[:8]}"
    r2 = requests.post(f"{BASE_URL}/api/coupons/validate",
                       json={"code": code.lower(), "customer_id": cust}, timeout=15)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["valid"] is True
    assert body["discount_percent"] == 20
    assert body["code"] == code.upper()


def test_validate_nonexistent_returns_valid_false(api):
    r = requests.post(f"{BASE_URL}/api/coupons/validate",
                      json={"code": "NEVEREXISTS_XYZ", "customer_id": "someone"}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert "reason" in body


def test_validate_inactive_returns_valid_false(admin, coupon_ids):
    code = _tag()
    r = admin.post(f"{BASE_URL}/api/coupons",
                   json={"code": code, "discount_percent": 10, "active": False}, timeout=15)
    cid = r.json()["id"]
    coupon_ids.append(cid)
    r2 = requests.post(f"{BASE_URL}/api/coupons/validate",
                       json={"code": code, "customer_id": "somecust"}, timeout=15)
    body = r2.json()
    assert body["valid"] is False
    assert "inativo" in body["reason"].lower()


# ------------- 28-day cooldown (via direct DB service) -------------

def test_cooldown_blocks_recent_customer(admin, coupon_ids):
    """Uses record_usage to plant a recent usage; validate must then refuse."""
    # Need to run this against the same DB the API uses — use the service directly.
    import sys, asyncio
    sys.path.insert(0, "/app/backend")
    from services.coupon import record_usage

    code = _tag()
    r = admin.post(f"{BASE_URL}/api/coupons",
                   json={"code": code, "discount_percent": 15, "active": True}, timeout=15)
    cid = r.json()["id"]
    coupon_ids.append(cid)

    cust = f"testcust_cd_{uuid.uuid4().hex[:8]}"

    # First, verify validate says OK
    r_ok = requests.post(f"{BASE_URL}/api/coupons/validate",
                         json={"code": code, "customer_id": cust}, timeout=15).json()
    assert r_ok["valid"] is True

    # Record a usage right now for this customer
    asyncio.run(record_usage(
        coupon_id=cid, coupon_code=code, customer_id=cust,
        payment_id=f"fake_pmt_{uuid.uuid4().hex[:6]}", discount_percent=15,
    ))

    # Same customer trying now: blocked
    r_blocked = requests.post(f"{BASE_URL}/api/coupons/validate",
                              json={"code": code, "customer_id": cust}, timeout=15).json()
    assert r_blocked["valid"] is False
    assert "28" in r_blocked["reason"]

    # Different customer: still ok
    r_other = requests.post(f"{BASE_URL}/api/coupons/validate",
                            json={"code": code,
                                  "customer_id": f"testcust_other_{uuid.uuid4().hex[:8]}"},
                            timeout=15).json()
    assert r_other["valid"] is True


# ------------- Coupon applied on /api/payments + usage recorded on confirmation -------------

def test_create_payment_with_coupon_and_record_usage_on_confirm(admin, api, coupon_ids):
    """End-to-end: seed a coupon, create payment referencing a real painel-cache
    customer_id, then simulate paid via /reprocess/{id} with force_paid=true.
    Verify coupon_usages row is inserted (idempotent on retry)."""
    # Pick a customer_id known to exist in painel cache OR local customers.
    # Try painel_users cache first (public endpoint requires auth, so use admin).
    r = admin.get(f"{BASE_URL}/api/painel/users?force_refresh=false", timeout=30)
    if r.status_code != 200:
        pytest.skip(f"painel cache unavailable ({r.status_code}) — cannot pick a real customer_id")
    users = r.json().get("users") or []
    if not users:
        pytest.skip("no painel users in cache")
    real_cust_id = str(users[0].get("id") or users[0].get("user_id") or users[0].get("username"))

    code = _tag()
    r = admin.post(f"{BASE_URL}/api/coupons",
                   json={"code": code, "discount_percent": 30, "active": True}, timeout=15)
    assert r.status_code == 200
    cid = r.json()["id"]
    coupon_ids.append(cid)

    # POST /api/payments with coupon
    r2 = api.post(f"{BASE_URL}/api/payments",
                  json={"customer_id": real_cust_id, "plan_months": 1,
                        "coupon_code": code}, timeout=30)
    if r2.status_code == 502:
        pytest.skip(f"InfinitePay unavailable: {r2.text[:200]}")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body.get("coupon_code") == code
    assert body.get("discount_percent") == 30
    assert body.get("original_amount_cents") > body.get("amount_cents")
    pid = body["payment_id"]

    # Simulate webhook confirmation via reprocess
    r3 = admin.post(f"{BASE_URL}/api/payments/reprocess/{pid}",
                    json={"force_paid": True}, timeout=60)
    assert r3.status_code == 200, r3.text
    # Renewal may fail (painel WAF) — that's OK. Usage should still be recorded
    # because record_usage happens BEFORE the painel call.

    # Verify usage was recorded
    r4 = admin.get(f"{BASE_URL}/api/coupons/{cid}/usages", timeout=15)
    assert r4.status_code == 200
    usages = r4.json()
    assert len(usages) >= 1
    matched = [u for u in usages if u["payment_id"] == pid]
    assert len(matched) == 1, f"expected exactly 1 usage row, got {len(matched)}: {usages}"
    assert matched[0]["coupon_code"] == code
    assert matched[0]["customer_id"] == real_cust_id

    # Idempotency: reprocess again → still only 1 usage
    r5 = admin.post(f"{BASE_URL}/api/payments/reprocess/{pid}",
                    json={"force_paid": True}, timeout=60)
    assert r5.status_code == 200
    r6 = admin.get(f"{BASE_URL}/api/coupons/{cid}/usages", timeout=15)
    matched2 = [u for u in r6.json() if u["payment_id"] == pid]
    assert len(matched2) == 1, f"expected idempotent 1 usage, got {len(matched2)}"


def test_create_payment_with_invalid_coupon_returns_400(admin, api):
    r = admin.get(f"{BASE_URL}/api/painel/users?force_refresh=false", timeout=30)
    if r.status_code != 200 or not r.json().get("users"):
        pytest.skip("no painel users in cache")
    real_cust_id = str(r.json()["users"][0].get("id") or r.json()["users"][0].get("username"))
    r2 = api.post(f"{BASE_URL}/api/payments",
                  json={"customer_id": real_cust_id, "plan_months": 1,
                        "coupon_code": "NEVEREXISTS_XYZ"}, timeout=30)
    assert r2.status_code == 400


# ------------- Teardown: clean up all test-created coupons -------------

def test_zzz_cleanup(admin, coupon_ids):
    for cid in coupon_ids:
        try:
            admin.delete(f"{BASE_URL}/api/coupons/{cid}", timeout=10)
        except Exception:
            pass
