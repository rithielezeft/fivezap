"""WhatsFlow backend API tests (iteration 2).

Regression + new tests for:
- Templates trigger_source (client|admin|both)
- Settings plan_price_Nm (R$ string with comma or dot)
- New /api/painel/{users,renew,package-ids}
- Bot filtering by trigger_source vs direction
"""
import os
import time
import pytest
import requests
from pathlib import Path

# ---- Load REACT_APP_BACKEND_URL from frontend/.env ----
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


_ids = {}


# ========== Root / Health ==========
def test_root(client):
    r = client.get(f"{API}/")
    assert r.status_code == 200
    assert r.json() == {"service": "WhatsFlow", "status": "ok"}


# ========== Dashboard (regression) ==========
def test_dashboard_stats(client):
    r = client.get(f"{API}/dashboard/stats")
    assert r.status_code == 200
    d = r.json()
    for k in ("trials_today", "total_customers", "active_customers",
              "expiring_soon", "revenue_week_cents", "by_system_type", "trials_by_day"):
        assert k in d


def test_dashboard_activity(client):
    r = client.get(f"{API}/dashboard/activity")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ========== Customers CRUD (regression) ==========
def test_customer_create(client):
    r = client.post(f"{API}/customers", json={
        "name": "TEST_ClienteIt2",
        "whatsapp": "5511977776666",
        "system_type": "iptv",
        "mac": "AA:BB:CC:DD:EE:22",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "TEST_ClienteIt2"
    _ids["c1"] = d["id"]


def test_customer_get(client):
    r = client.get(f"{API}/customers/{_ids['c1']}")
    assert r.status_code == 200
    assert r.json()["id"] == _ids["c1"]


def test_customer_update(client):
    r = client.put(f"{API}/customers/{_ids['c1']}", json={"notes": "TEST it2 notes"})
    assert r.status_code == 200
    assert r.json()["notes"] == "TEST it2 notes"


# ========== Templates: trigger_source ==========
def test_template_create_admin(client):
    r = client.post(f"{API}/templates", json={
        "name": "TEST_admin tpl",
        "trigger_command": "/teste admincmd TEST_IT2",
        "system_type": "p2p",
        "requires_mac": False,
        "package_id": 61,
        "response_template": "✅ admin trigger",
        "trigger_source": "admin",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["trigger_source"] == "admin"
    _ids["t_admin"] = d["id"]


def test_template_create_client(client):
    r = client.post(f"{API}/templates", json={
        "name": "TEST_client tpl",
        "trigger_command": "/teste clientcmd TEST_IT2",
        "system_type": "p2p",
        "trigger_source": "client",
    })
    assert r.status_code == 200, r.text
    assert r.json()["trigger_source"] == "client"
    _ids["t_client"] = r.json()["id"]


def test_template_create_both_default(client):
    r = client.post(f"{API}/templates", json={
        "name": "TEST_both tpl",
        "trigger_command": "/teste bothcmd TEST_IT2",
        "system_type": "p2p",
    })
    assert r.status_code == 200, r.text
    assert r.json()["trigger_source"] == "both"
    _ids["t_both"] = r.json()["id"]


def test_template_list_has_trigger_source(client):
    r = client.get(f"{API}/templates")
    assert r.status_code == 200
    lst = r.json()
    assert lst, "template list empty"
    for t in lst:
        assert "trigger_source" in t
        assert t["trigger_source"] in ("client", "admin", "both")


def test_template_update_trigger_source(client):
    r = client.put(f"{API}/templates/{_ids['t_admin']}",
                   json={"trigger_source": "both"})
    assert r.status_code == 200
    assert r.json()["trigger_source"] == "both"
    # verify persistence via GET
    r2 = client.get(f"{API}/templates")
    updated = next(t for t in r2.json() if t["id"] == _ids["t_admin"])
    assert updated["trigger_source"] == "both"
    # revert back
    client.put(f"{API}/templates/{_ids['t_admin']}", json={"trigger_source": "admin"})


# ========== Settings: R$ string prices ==========
def test_settings_get_prices_as_string(client):
    r = client.get(f"{API}/settings")
    assert r.status_code == 200
    d = r.json()
    for k in ("plan_price_1m", "plan_price_3m", "plan_price_6m", "plan_price_12m"):
        assert k in d, f"missing {k}"
        assert isinstance(d[k], str)
    # no legacy *_cents keys
    for k in ("plan_price_1m_cents", "plan_price_3m_cents",
              "plan_price_6m_cents", "plan_price_12m_cents"):
        assert k not in d, f"legacy key {k} still present"


def test_settings_update_price_comma(client):
    r = client.put(f"{API}/settings", json={"plan_price_1m": "39,90"})
    assert r.status_code == 200
    r2 = client.get(f"{API}/settings")
    assert r2.json()["plan_price_1m"] == "39,90"


def test_settings_update_price_dot(client):
    r = client.put(f"{API}/settings", json={"plan_price_3m": "99.50"})
    assert r.status_code == 200
    r2 = client.get(f"{API}/settings")
    assert r2.json()["plan_price_3m"] == "99.50"


# ========== Payments customer info: prices_cents converted ==========
def test_payments_customer_info_cents_conversion(client):
    # Ensure known values
    client.put(f"{API}/settings", json={
        "plan_price_1m": "35,00",
        "plan_price_3m": "99.50",
        "plan_price_6m": "160,00",
        "plan_price_12m": "280,00",
    })
    cid = _ids["c1"]
    r = client.get(f"{API}/payments/customer/{cid}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["customer"]["id"] == cid
    prices = d["prices_cents"]
    # keys may be int or str (JSON stringifies int dict keys)
    def _get(k):
        return prices.get(k) if k in prices else prices.get(str(k))
    assert _get(1) == 3500, f"expected 3500 got {_get(1)}"
    assert _get(3) == 9950, f"expected 9950 got {_get(3)}"
    assert _get(6) == 16000, f"expected 16000 got {_get(6)}"
    assert _get(12) == 28000, f"expected 28000 got {_get(12)}"


# ========== Bot: trigger_source filtering ==========
def _poll_messages(client, phone, expected, direction, tries=12, delay=0.5):
    for _ in range(tries):
        time.sleep(delay)
        r = client.get(f"{API}/messages", params={"phone": phone})
        if r.status_code != 200:
            continue
        for m in r.json():
            if m.get("message") == expected and m.get("direction") == direction:
                return True
    return False


def test_incoming_from_me_saved_as_out(client):
    # admin-triggered scenario — msg with from_me=true
    phone = "5511922221111"
    body = f"/teste admincmd TEST_IT2 xxx {int(time.time())}"
    r = client.post(f"{API}/whatsapp/incoming",
                    json={"phone": phone, "message": body, "from_me": True})
    assert r.status_code == 200
    assert _poll_messages(client, phone, body, "out"), "admin (from_me) msg not saved as direction='out'"


def test_incoming_client_saved_as_in(client):
    phone = "5511922223333"
    body = f"/teste clientcmd TEST_IT2 yyy {int(time.time())}"
    r = client.post(f"{API}/whatsapp/incoming",
                    json={"phone": phone, "message": body, "from_me": False})
    assert r.status_code == 200
    assert _poll_messages(client, phone, body, "in"), "client msg not saved as direction='in'"


# ========== New /api/painel/* ==========
def test_painel_package_ids(client):
    r = client.get(f"{API}/painel/package-ids")
    assert r.status_code == 200, r.text
    d = r.json()
    for st in ("iptv", "p2p", "hybrid"):
        assert st in d, f"missing {st}"
        sub = d[st]
        # keys may be int or str
        keys = {str(k) for k in sub.keys()}
        assert {"1", "3", "6", "12"}.issubset(keys), f"{st}: got {keys}"


def test_painel_users_502_on_failure(client):
    """External call will fail (2Captcha / painel unreachable) — must return 502 gracefully."""
    r = client.get(f"{API}/painel/users", params={"limit": 5}, timeout=180)
    # Ingress may translate to plain 502 HTML if upstream slow; either way must be a gateway error
    assert r.status_code in (502, 504), f"expected 502/504, got {r.status_code}: {r.text[:200]}"


def test_painel_renew_502_on_failure(client):
    r = client.post(f"{API}/painel/renew",
                    json={"user_id": "fake", "system_type": "p2p", "plan_months": 3},
                    timeout=180)
    assert r.status_code == 502, f"expected 502, got {r.status_code}: {r.text[:200]}"


# ========== WhatsApp / Messages regression ==========
def test_whatsapp_status(client):
    r = client.get(f"{API}/whatsapp/status")
    assert r.status_code == 200
    for k in ("ready", "state", "has_qr"):
        assert k in r.json()


def test_messages_conversations(client):
    r = client.get(f"{API}/messages/conversations")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_trials_list(client):
    r = client.get(f"{API}/trials")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_payments_list(client):
    r = client.get(f"{API}/payments")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ========== Iteration 3: renew_user regression fix ==========
def test_painel_module_has_renew_user():
    from services import painel
    assert hasattr(painel, "renew_user"), "painel.renew_user missing"
    assert callable(painel.renew_user)


# ========== Iteration 3: Notifications ==========
EXPECTED_EVENTS = {"expiration_3d", "expiration_1d", "expiration_0d", "renewal_success", "trial_ready"}


def test_notifications_list(client):
    r = client.get(f"{API}/notifications")
    assert r.status_code == 200, r.text
    lst = r.json()
    assert isinstance(lst, list)
    keys = {t["event_key"] for t in lst}
    assert EXPECTED_EVENTS.issubset(keys), f"missing events: {EXPECTED_EVENTS - keys}"
    for t in lst:
        for k in ("id", "event_key", "title", "body", "image_url", "enabled", "updated_at"):
            assert k in t, f"missing field {k} in {t}"


def test_notification_get_single(client):
    r = client.get(f"{API}/notifications/expiration_3d")
    assert r.status_code == 200
    assert r.json()["event_key"] == "expiration_3d"


def test_notification_get_invalid_404(client):
    r = client.get(f"{API}/notifications/invalid_key_xyz")
    assert r.status_code == 404


def test_notification_update_body_and_image(client):
    original = client.get(f"{API}/notifications/expiration_3d").json()
    _ids["notif_original"] = original
    r = client.put(f"{API}/notifications/expiration_3d",
                   json={"body": "Test {name}", "image_url": "https://example.com/img.jpg"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["body"] == "Test {name}"
    assert d["image_url"] == "https://example.com/img.jpg"
    r2 = client.get(f"{API}/notifications/expiration_3d")
    assert r2.json()["body"] == "Test {name}"
    assert r2.json()["image_url"] == "https://example.com/img.jpg"


def test_notification_update_disable(client):
    r = client.put(f"{API}/notifications/expiration_3d", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    r2 = client.put(f"{API}/notifications/expiration_3d", json={"enabled": True})
    assert r2.json()["enabled"] is True


def test_notification_update_invalid_404(client):
    r = client.put(f"{API}/notifications/invalid_key_xyz", json={"body": "x"})
    assert r.status_code == 404


def test_notification_update_empty_400(client):
    r = client.put(f"{API}/notifications/expiration_3d", json={})
    assert r.status_code == 400
    assert "No fields to update" in r.text


# ========== Iteration 3: WhatsApp send with image_url ==========
def test_whatsapp_send_message_only(client):
    r = client.post(f"{API}/whatsapp/send",
                    json={"phone": "5511900000001", "message": "hello"})
    assert r.status_code == 502, f"expected 502 got {r.status_code}: {r.text[:200]}"


def test_whatsapp_send_image_only(client):
    r = client.post(f"{API}/whatsapp/send",
                    json={"phone": "5511900000002", "image_url": "https://x/y.jpg"})
    assert r.status_code == 502, f"expected 502 got {r.status_code}: {r.text[:200]}"


def test_whatsapp_send_both(client):
    r = client.post(f"{API}/whatsapp/send",
                    json={"phone": "5511900000003", "message": "hi", "image_url": "https://x/y.jpg"})
    assert r.status_code == 502, f"expected 502 got {r.status_code}: {r.text[:200]}"


# ========== Cleanup ==========
def test_zz_cleanup(client):
    for k in ("t_admin", "t_client", "t_both"):
        if k in _ids:
            client.delete(f"{API}/templates/{_ids[k]}")
    if "c1" in _ids:
        client.delete(f"{API}/customers/{_ids['c1']}")
    # Restore expiration_3d notification template
    orig = _ids.get("notif_original")
    if orig:
        client.put(f"{API}/notifications/expiration_3d", json={
            "title": orig["title"],
            "body": orig["body"],
            "image_url": orig.get("image_url") or "",
            "enabled": orig["enabled"],
        })
