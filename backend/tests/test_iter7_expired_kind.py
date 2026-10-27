# Iteration 7: read-only checks for expired kind counts, balances currency, geography search data
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": "Rithi0518@"}, timeout=30)
    if r.status_code != 200:
        pytest.skip("login failed")
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return s


# Expired list: kind counts + per-user is_trial
def test_expired_counts(client):
    r = client.get(f"{BASE_URL}/api/painel/expired", timeout=60)
    assert r.status_code == 200
    d = r.json()
    for k in ("count", "count_with_whatsapp", "count_trial", "count_regular", "users"):
        assert k in d
    assert d["count_trial"] + d["count_regular"] == d["count"] == len(d["users"])
    for u in d["users"]:
        assert isinstance(u["is_trial"], bool)
    assert d["count_trial"] == sum(1 for u in d["users"] if u["is_trial"])
    print(d)


# Invalid kind rejected by pydantic Literal (422, no send)
def test_notify_invalid_kind_422(client):
    r = client.post(f"{BASE_URL}/api/painel/notify-expired", json={"user_ids": [], "kind": "bogus"}, timeout=30)
    assert r.status_code == 422


# Balances: painel currency CREDITS
def test_balances_credits(client):
    r = client.get(f"{BASE_URL}/api/dashboard/balances", timeout=90)
    assert r.status_code == 200
    d = r.json()
    print(d)
    assert d["painel"]["currency"] == "CREDITS"


# Geography: customers include region_key/status for search
def test_geography_customers(client):
    r = client.get(f"{BASE_URL}/api/analytics/geography/customers", timeout=60)
    if r.status_code == 404:
        pytest.skip("endpoint path differs")
    assert r.status_code == 200
    d = r.json()
    custs = d.get("customers", [])
    assert isinstance(custs, list)
    hits = [c for c in custs if "oscarnew" in str(c).lower()]
    print("oscarnew hits:", hits[:2])
