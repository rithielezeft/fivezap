"""WhatsFlow backend API tests (iteration 1)."""
import os
import time
import pytest
import requests
from pathlib import Path

# Load REACT_APP_BACKEND_URL from frontend/.env
_env_file = Path("/app/frontend/.env")
BASE_URL = None
for line in _env_file.read_text().splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL missing"

API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---- Root ----
def test_root(client):
    r = client.get(f"{API}/")
    assert r.status_code == 200
    data = r.json()
    assert data == {"service": "WhatsFlow", "status": "ok"}


# ---- Dashboard ----
def test_dashboard_stats(client):
    r = client.get(f"{API}/dashboard/stats")
    assert r.status_code == 200
    d = r.json()
    for k in ("trials_today", "total_customers", "active_customers",
              "expiring_soon", "revenue_week_cents", "by_system_type", "trials_by_day"):
        assert k in d, f"missing {k}"
    assert isinstance(d["by_system_type"], dict)
    assert isinstance(d["trials_by_day"], list)


def test_dashboard_activity(client):
    r = client.get(f"{API}/dashboard/activity")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---- Customers CRUD ----
_created_ids = {}


def test_customer_create(client):
    payload = {
        "name": "TEST_Cliente1",
        "whatsapp": "5511988887777",
        "system_type": "iptv",
        "mac": "AA:BB:CC:DD:EE:FF",
    }
    r = client.post(f"{API}/customers", json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == payload["name"]
    assert d["system_type"] == "iptv"
    assert d["mac"] == "AA:BB:CC:DD:EE:FF"
    assert "id" in d
    _created_ids["c1"] = d["id"]


def test_customer_list(client):
    r = client.get(f"{API}/customers")
    assert r.status_code == 200
    lst = r.json()
    assert isinstance(lst, list)
    assert any(c["id"] == _created_ids["c1"] for c in lst)


def test_customer_get_by_id(client):
    cid = _created_ids["c1"]
    r = client.get(f"{API}/customers/{cid}")
    assert r.status_code == 200
    assert r.json()["id"] == cid


def test_customer_update(client):
    cid = _created_ids["c1"]
    r = client.put(f"{API}/customers/{cid}", json={"status": "active", "notes": "TEST notes updated"})
    assert r.status_code == 200
    d = r.json()
    assert d["notes"] == "TEST notes updated"
    assert d["status"] == "active"
    # verify persistence
    r2 = client.get(f"{API}/customers/{cid}")
    assert r2.json()["notes"] == "TEST notes updated"


def test_customer_filter_by_system_type(client):
    r = client.get(f"{API}/customers", params={"system_type": "iptv"})
    assert r.status_code == 200
    lst = r.json()
    assert all(c["system_type"] == "iptv" for c in lst)
    assert any(c["id"] == _created_ids["c1"] for c in lst)


def test_customer_delete(client):
    # create disposable
    r = client.post(f"{API}/customers", json={
        "name": "TEST_ToDelete",
        "whatsapp": "5511988880000",
        "system_type": "p2p",
    })
    assert r.status_code == 200
    cid = r.json()["id"]
    r = client.delete(f"{API}/customers/{cid}")
    assert r.status_code == 200
    assert r.json().get("success") is True
    # verify removed
    r2 = client.get(f"{API}/customers/{cid}")
    assert r2.status_code == 404


# ---- Templates ----
def test_template_create(client):
    payload = {
        "name": "TEST_Teste P2P",
        "trigger_command": "/teste p2p TEST",
        "system_type": "p2p",
        "requires_mac": False,
        "package_id": 61,
        "response_template": "✅ Teste {system_type}",
    }
    r = client.post(f"{API}/templates", json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["trigger_command"] == "/teste p2p TEST"
    assert d["package_id"] == 61
    assert d["enabled"] is True
    _created_ids["t1"] = d["id"]


def test_template_duplicate_conflict(client):
    payload = {
        "name": "TEST_dup",
        "trigger_command": "/teste p2p TEST",
        "system_type": "p2p",
    }
    r = client.post(f"{API}/templates", json=payload)
    assert r.status_code == 409, r.text


def test_template_list(client):
    r = client.get(f"{API}/templates")
    assert r.status_code == 200
    lst = r.json()
    assert any(t["id"] == _created_ids["t1"] for t in lst)


def test_template_update_enabled(client):
    tid = _created_ids["t1"]
    r = client.put(f"{API}/templates/{tid}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_template_delete(client):
    tid = _created_ids["t1"]
    r = client.delete(f"{API}/templates/{tid}")
    assert r.status_code == 200
    assert r.json().get("success") is True


# ---- WhatsApp ----
def test_whatsapp_status(client):
    r = client.get(f"{API}/whatsapp/status")
    assert r.status_code == 200
    d = r.json()
    # Expected keys per problem statement
    for k in ("ready", "state", "has_qr"):
        assert k in d, f"missing {k} in {d}"


def test_whatsapp_qr(client):
    r = client.get(f"{API}/whatsapp/qr")
    assert r.status_code == 200
    d = r.json()
    assert "qr" in d


# ---- Settings ----
def test_settings_get(client):
    r = client.get(f"{API}/settings")
    assert r.status_code == 200
    d = r.json()
    assert d.get("painel_username") == "Rithiele2026", f"got {d.get('painel_username')}"
    assert d.get("twocaptcha_key"), "twocaptcha_key empty"
    assert d.get("trial_package_id") == "61"


def test_settings_update(client):
    handle_value = "test-handle-TEST"
    r = client.put(f"{API}/settings", json={"infinitepay_handle": handle_value})
    assert r.status_code == 200
    assert r.json().get("success") is True
    # Confirm with GET
    r2 = client.get(f"{API}/settings")
    assert r2.json().get("infinitepay_handle") == handle_value


# ---- Trials list ----
def test_trials_list(client):
    r = client.get(f"{API}/trials")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---- Payments list ----
def test_payments_list(client):
    r = client.get(f"{API}/payments")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---- Messages ----
def test_messages_conversations(client):
    r = client.get(f"{API}/messages/conversations")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_whatsapp_incoming_and_message_persist(client):
    phone = "5511999999999"
    r = client.post(f"{API}/whatsapp/incoming",
                    json={"phone": phone, "message": "oi TEST", "from_me": False})
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True
    # incoming is processed async — poll briefly
    found = False
    for _ in range(10):
        time.sleep(0.5)
        r2 = client.get(f"{API}/messages", params={"phone": phone})
        assert r2.status_code == 200
        msgs = r2.json()
        if any(m.get("message") == "oi TEST" for m in msgs):
            found = True
            break
    assert found, "incoming message not persisted"


# ---- Payments customer info ----
def test_payments_customer_info(client):
    cid = _created_ids["c1"]
    r = client.get(f"{API}/payments/customer/{cid}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert "customer" in d and "prices_cents" in d
    assert d["customer"]["id"] == cid
    prices = d["prices_cents"]
    # JSON keys become strings — accept both
    keys = {str(k) for k in prices.keys()}
    assert {"1", "3", "6", "12"}.issubset(keys), f"got keys {keys}"


# ---- Cleanup at module end ----
def test_zz_cleanup(client):
    if "c1" in _created_ids:
        client.delete(f"{API}/customers/{_created_ids['c1']}")
