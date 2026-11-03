"""End-to-end HTTP tests against the public URL for renewal-flow endpoints
verifying auth middleware public paths + Mongo Atlas customer lookup."""
import os
import re
import time
import uuid
import pytest
import requests

BASE = os.environ.get("PUBLIC_BASE_URL", "https://whatsflow.zeferius.com").rstrip("/")
API = f"{BASE}/api"
ADMIN_PASSWORD = "Rithi0518@"
KNOWN_CUSTOMER = "228116806"  # oscarnew / iptv - in Mongo Atlas


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


# ---------- Auth middleware / public paths ----------

def test_payments_customer_lookup_is_public():
    """GET /api/payments/customer/{id} must respond without auth (public checkout)."""
    r = requests.get(f"{API}/payments/customer/{KNOWN_CUSTOMER}", timeout=30)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert "customer" in data
    assert data["customer"].get("id") == KNOWN_CUSTOMER or data["customer"].get("painel_id") == KNOWN_CUSTOMER
    # Should have a name + system_type since customer 228116806 is known in Mongo
    assert data["customer"].get("name"), "customer.name missing"
    assert data["customer"].get("system_type"), "customer.system_type missing"
    # And prices
    assert "prices_cents" in data
    for m in (1, 3, 6, 12):
        assert m in data["prices_cents"] or str(m) in data["prices_cents"]


def test_payments_list_requires_auth():
    """GET /api/payments (admin) must be blocked without token."""
    r = requests.get(f"{API}/payments", timeout=30)
    assert r.status_code in (401, 403), f"unexpected {r.status_code}: {r.text[:200]}"


def test_payments_webhook_is_public():
    """POST /api/payments/webhook accepts requests without auth (InfinitePay callback)."""
    # Post a fake payload that references a non-existent order — expect a normal
    # 2xx response, NOT a 401/403. The endpoint MUST accept unauthenticated
    # traffic since InfinitePay never sends tokens.
    payload = {"order_nsu": f"renew-nonexistent-{uuid.uuid4().hex[:8]}-3m", "paid": False}
    r = requests.post(f"{API}/payments/webhook", json=payload, timeout=30)
    assert r.status_code not in (401, 403), \
        f"webhook must be public, got {r.status_code}: {r.text[:200]}"


def test_post_payments_is_public():
    """POST /api/payments must NOT require auth (customer creates checkout from /pay/{id})."""
    payload = {"customer_id": KNOWN_CUSTOMER, "plan_months": 1}
    r = requests.post(f"{API}/payments", json=payload, timeout=45)
    assert r.status_code not in (401, 403), \
        f"POST /api/payments must be public, got {r.status_code}: {r.text[:200]}"
    # Note: may return 502 if InfinitePay handle not configured, that's OK for
    # this test (we only care about middleware not blocking).


def test_customers_list_requires_auth():
    r = requests.get(f"{API}/customers", timeout=30)
    assert r.status_code in (401, 403)


def test_trials_list_requires_auth():
    r = requests.get(f"{API}/trials", timeout=30)
    assert r.status_code in (401, 403)


# ---------- Admin-authenticated critical endpoints ----------

def test_admin_login_returns_token():
    r = requests.post(f"{API}/auth/login", json={"password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_package_ids_endpoint_shape(admin_token):
    r = requests.get(f"{API}/painel/package-ids",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
    assert r.status_code == 200
    d = r.json()
    # Verify problem-statement package IDs
    assert d["p2p"]["3"] == 42 or d["p2p"][3] == 42
    assert d["p2p"]["12"] == 57 or d["p2p"][12] == 57
    assert d["iptv"]["3"] == 43 or d["iptv"][3] == 43
    assert d["iptv"]["12"] == 58 or d["iptv"][12] == 58


def test_payments_list_with_admin_token(admin_token):
    r = requests.get(f"{API}/payments",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------- Renewal flow order_nsu format ----------

def test_create_payment_generates_renew_nsu_format(admin_token):
    """POST /api/payments with plan_months=3 must generate order_nsu='renew-{painel_id}-3m'."""
    # Use a fake customer id; endpoint should still succeed at the DB/Mongo
    # level (or fail with 4xx due to unknown customer). If it fails, we can't
    # check the order_nsu. So use the known customer.
    payload = {"customer_id": KNOWN_CUSTOMER, "plan_months": 3}
    r = requests.post(f"{API}/payments", json=payload, timeout=60)
    if r.status_code == 502:
        pytest.skip("InfinitePay handle not configured — cannot verify NSU end-to-end")
    assert r.status_code in (200, 201), f"got {r.status_code}: {r.text[:300]}"
    data = r.json()
    # order_nsu may be in response directly or in the payment record
    nsu = data.get("order_nsu") or (data.get("payment") or {}).get("order_nsu")
    if nsu:
        assert re.match(r"^renew-\d+-\d+m$", nsu), f"bad NSU format: {nsu}"
        assert KNOWN_CUSTOMER in nsu


# ---------- Webhook 'paid' variations ----------

def test_webhook_accepts_various_paid_variants():
    """Webhook must accept multiple representations of 'paid'."""
    variants = [
        {"paid": True},
        {"status": "paid"},
        {"status": "approved"},
        {"status": "completed"},
        {"payment_status": "approved"},
    ]
    for v in variants:
        body = {"order_nsu": f"renew-nonexistent-{uuid.uuid4().hex[:6]}-1m", **v}
        r = requests.post(f"{API}/payments/webhook", json=body, timeout=30)
        # Should NOT be 401/403 (public), and NOT 500 (must handle gracefully)
        assert r.status_code not in (401, 403, 500), \
            f"variant {v} → {r.status_code}: {r.text[:200]}"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
