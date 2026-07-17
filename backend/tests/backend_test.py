"""WhatsFlow backend API tests (iteration 4).

Adds:
- Admin JWT auth on all /api/* endpoints except public ones
- /api/uploads (POST multipart, GET public)
- 9 notification templates (expiration_7d + expired_1d/3d/7d)
- Painel users cache endpoints (/api/painel/users, /api/painel/users/refresh)
- pay_link exposed per user

Preserves iteration 2/3 regression tests, but now all admin calls carry Bearer token.
"""
import io
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
ADMIN_PASSWORD = "Rithi0518@"


# ---- Fixtures ----
@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={"password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("token_type") == "bearer"
    assert data.get("access_token")
    return data["access_token"]


@pytest.fixture(scope="module")
def client(token):
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    })
    return s


@pytest.fixture(scope="module")
def anon_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


_ids = {}


# ========== AUTH ==========
def test_auth_login_success(anon_client):
    r = anon_client.post(f"{API}/auth/login", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200
    d = r.json()
    assert d["token_type"] == "bearer"
    assert isinstance(d["access_token"], str) and len(d["access_token"]) > 10


def test_auth_login_wrong_password(anon_client):
    r = anon_client.post(f"{API}/auth/login", json={"password": "wrong-xyz-000"})
    assert r.status_code == 401


def test_auth_me_without_token(anon_client):
    r = anon_client.get(f"{API}/auth/me")
    assert r.status_code == 401


def test_auth_me_with_token(client):
    r = client.get(f"{API}/auth/me")
    assert r.status_code == 200
    d = r.json()
    assert d["authenticated"] is True
    assert d["sub"] == "admin"


def test_dashboard_stats_requires_auth(anon_client):
    r = anon_client.get(f"{API}/dashboard/stats")
    assert r.status_code == 401


def test_dashboard_stats_with_auth(client):
    r = client.get(f"{API}/dashboard/stats")
    assert r.status_code == 200
    d = r.json()
    for k in ("trials_today", "total_customers", "active_customers",
              "expiring_soon", "revenue_week_cents", "by_system_type", "trials_by_day"):
        assert k in d


def test_public_endpoints_no_auth(anon_client):
    # health
    r = anon_client.get(f"{API}/health")
    assert r.status_code == 200
    # root
    r = anon_client.get(f"{API}/")
    assert r.status_code == 200
    # pay customer (fake id -> 404 acceptable)
    r = anon_client.get(f"{API}/pay/customer/does-not-exist")
    assert r.status_code in (404, 200), f"got {r.status_code}"
    # whatsapp incoming (should not require auth)
    r = anon_client.post(f"{API}/whatsapp/incoming",
                         json={"phone": "5511900000000", "message": "public-test", "from_me": False})
    assert r.status_code == 200, f"got {r.status_code} {r.text[:200]}"


def test_public_trial_endpoint(anon_client):
    # Will 502 (painel unreachable) but must NOT be 401
    r = anon_client.post(f"{API}/public/trial",
                         json={"name": "TEST_pub", "whatsapp": "5511900000000",
                               "system_type": "iptv", "mac": "AA:BB:CC:DD:EE:FF"},
                         timeout=180)
    assert r.status_code != 401, f"public trial should not require auth, got 401"
    # 4xx or 5xx acceptable — but not 401
    assert r.status_code in (200, 400, 422, 502, 504), f"unexpected {r.status_code}: {r.text[:200]}"


def test_auth_change_password_and_restore(anon_client, client):
    new_pw = "TempTest123!"
    r = client.post(f"{API}/auth/change-password",
                    json={"current_password": ADMIN_PASSWORD, "new_password": new_pw})
    assert r.status_code == 200, r.text
    # Verify new password works
    r2 = anon_client.post(f"{API}/auth/login", json={"password": new_pw})
    assert r2.status_code == 200
    # Restore
    tmp_token = r2.json()["access_token"]
    r3 = requests.post(f"{API}/auth/change-password",
                       headers={"Authorization": f"Bearer {tmp_token}",
                                "Content-Type": "application/json"},
                       json={"current_password": new_pw, "new_password": ADMIN_PASSWORD})
    assert r3.status_code == 200
    # Confirm original works again
    r4 = anon_client.post(f"{API}/auth/login", json={"password": ADMIN_PASSWORD})
    assert r4.status_code == 200


# ========== UPLOADS ==========
_PNG_1x1 = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def test_upload_requires_auth(anon_client):
    files = {"file": ("t.png", io.BytesIO(_PNG_1x1), "image/png")}
    r = requests.post(f"{API}/uploads", files=files)
    assert r.status_code == 401


def test_upload_png_success(token):
    files = {"file": ("t.png", io.BytesIO(_PNG_1x1), "image/png")}
    r = requests.post(f"{API}/uploads", files=files,
                      headers={"Authorization": f"Bearer {token}"}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("url", "path", "filename", "size"):
        assert k in d
    assert d["size"] == len(_PNG_1x1)
    assert d["filename"].endswith(".png")
    _ids["uploaded_filename"] = d["filename"]
    _ids["uploaded_path"] = d["path"]


def test_upload_bad_extension(token):
    files = {"file": ("t.txt", io.BytesIO(b"hi"), "text/plain")}
    r = requests.post(f"{API}/uploads", files=files,
                      headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400, r.text


def test_upload_get_public(anon_client):
    fname = _ids.get("uploaded_filename")
    if not fname:
        pytest.skip("no uploaded file")
    # No auth
    r = requests.get(f"{API}/uploads/{fname}")
    assert r.status_code == 200
    assert r.content == _PNG_1x1


# ========== NOTIFICATIONS (9 templates now) ==========
EXPECTED_EVENTS_9 = {
    "expiration_7d", "expiration_3d", "expiration_1d", "expiration_0d",
    "expired_1d", "expired_3d", "expired_7d",
    "renewal_success", "trial_ready",
}


def test_notifications_list_has_9(client):
    r = client.get(f"{API}/notifications")
    assert r.status_code == 200, r.text
    lst = r.json()
    keys = {t["event_key"] for t in lst}
    missing = EXPECTED_EVENTS_9 - keys
    assert not missing, f"missing events: {missing}. got: {keys}"


def test_notifications_requires_auth(anon_client):
    r = anon_client.get(f"{API}/notifications")
    assert r.status_code == 401


def test_notification_get_single(client):
    r = client.get(f"{API}/notifications/expiration_7d")
    assert r.status_code == 200
    assert r.json()["event_key"] == "expiration_7d"


def test_notification_update_and_restore(client):
    orig = client.get(f"{API}/notifications/expired_1d").json()
    r = client.put(f"{API}/notifications/expired_1d",
                   json={"body": "TEST expired 1d body {name}"})
    assert r.status_code == 200
    assert r.json()["body"] == "TEST expired 1d body {name}"
    # restore
    client.put(f"{API}/notifications/expired_1d",
               json={"body": orig["body"], "title": orig["title"],
                     "image_url": orig.get("image_url") or "",
                     "enabled": orig["enabled"]})


def test_notification_update_invalid_404(client):
    r = client.put(f"{API}/notifications/invalid_key_xyz", json={"body": "x"})
    assert r.status_code == 404


def test_notification_update_empty_400(client):
    r = client.put(f"{API}/notifications/expiration_3d", json={})
    assert r.status_code == 400


# ========== PAINEL USERS (cached endpoints) ==========
def test_painel_users_cached_response(client):
    r = client.get(f"{API}/painel/users", timeout=30)
    assert r.status_code == 200, f"expected 200 (cached), got {r.status_code}: {r.text[:200]}"
    d = r.json()
    for k in ("users", "count", "cache_updated_at", "refreshing", "last_error"):
        assert k in d, f"missing key {k}"
    assert isinstance(d["users"], list)
    assert isinstance(d["count"], int)


def test_painel_users_refresh_expected_failure(client):
    """Cloudflare 403 expected in datacenter. Response must have success:false + error string."""
    r = client.post(f"{API}/painel/users/refresh", timeout=180)
    assert r.status_code == 200, f"got {r.status_code}: {r.text[:200]}"
    d = r.json()
    assert "success" in d
    # Likely failure — verify shape
    if d["success"] is False:
        assert d.get("error"), "error field should be populated on failure"


def test_painel_package_ids(client):
    r = client.get(f"{API}/painel/package-ids")
    assert r.status_code == 200, r.text
    d = r.json()
    for st in ("iptv", "p2p", "hybrid"):
        assert st in d
        keys = {str(k) for k in d[st].keys()}
        assert {"1", "3", "6", "12"}.issubset(keys)


def test_painel_renew_502_on_failure(client):
    r = client.post(f"{API}/painel/renew",
                    json={"user_id": "fake", "system_type": "p2p", "plan_months": 3},
                    timeout=180)
    assert r.status_code == 502, f"expected 502, got {r.status_code}: {r.text[:200]}"


def test_painel_module_has_renew_user():
    import sys
    sys.path.insert(0, "/app/backend")
    from services import painel
    assert hasattr(painel, "renew_user")
    assert callable(painel.renew_user)


# ========== REGRESSION: Dashboard / Customers / Templates ==========
def test_root(anon_client):
    r = anon_client.get(f"{API}/")
    assert r.status_code == 200
    assert r.json()["service"] == "WhatsFlow"


def test_dashboard_activity(client):
    r = client.get(f"{API}/dashboard/activity")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_customer_create(client):
    r = client.post(f"{API}/customers", json={
        "name": "TEST_ClienteIt4",
        "whatsapp": "5511977776600",
        "system_type": "iptv",
        "mac": "AA:BB:CC:DD:EE:44",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "TEST_ClienteIt4"
    _ids["c1"] = d["id"]


def test_customer_get(client):
    r = client.get(f"{API}/customers/{_ids['c1']}")
    assert r.status_code == 200
    assert r.json()["id"] == _ids["c1"]


def test_customer_update(client):
    r = client.put(f"{API}/customers/{_ids['c1']}", json={"notes": "TEST it4 notes"})
    assert r.status_code == 200
    assert r.json()["notes"] == "TEST it4 notes"


def test_template_create_admin(client):
    r = client.post(f"{API}/templates", json={
        "name": "TEST_admin tpl it4",
        "trigger_command": "/teste admincmd TEST_IT4",
        "system_type": "p2p",
        "requires_mac": False,
        "package_id": 61,
        "response_template": "✅ admin trigger",
        "trigger_source": "admin",
    })
    assert r.status_code == 200, r.text
    assert r.json()["trigger_source"] == "admin"
    _ids["t_admin"] = r.json()["id"]


def test_template_list_has_trigger_source(client):
    r = client.get(f"{API}/templates")
    assert r.status_code == 200
    for t in r.json():
        assert t.get("trigger_source") in ("client", "admin", "both")


def test_settings_prices_as_string(client):
    r = client.get(f"{API}/settings")
    assert r.status_code == 200
    d = r.json()
    for k in ("plan_price_1m", "plan_price_3m", "plan_price_6m", "plan_price_12m"):
        assert k in d
        assert isinstance(d[k], str)


def test_settings_update_price_comma(client):
    r = client.put(f"{API}/settings", json={"plan_price_1m": "39,90"})
    assert r.status_code == 200
    r2 = client.get(f"{API}/settings")
    assert r2.json()["plan_price_1m"] == "39,90"


def test_payments_customer_prices_cents(client):
    client.put(f"{API}/settings", json={
        "plan_price_1m": "35,00", "plan_price_3m": "99.50",
        "plan_price_6m": "160,00", "plan_price_12m": "280,00",
    })
    r = client.get(f"{API}/payments/customer/{_ids['c1']}")
    assert r.status_code == 200, r.text
    prices = r.json()["prices_cents"]
    def _get(k): return prices.get(k) if k in prices else prices.get(str(k))
    assert _get(1) == 3500
    assert _get(3) == 9950


def test_whatsapp_incoming_public(anon_client):
    phone = "5511922221177"
    body = f"/hello_public {int(time.time())}"
    r = anon_client.post(f"{API}/whatsapp/incoming",
                         json={"phone": phone, "message": body, "from_me": False})
    assert r.status_code == 200


def test_whatsapp_status(client):
    r = client.get(f"{API}/whatsapp/status")
    assert r.status_code == 200


def test_messages_conversations(client):
    r = client.get(f"{API}/messages/conversations")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_trials_list(client):
    r = client.get(f"{API}/trials")
    assert r.status_code == 200


def test_payments_list(client):
    r = client.get(f"{API}/payments")
    assert r.status_code == 200


# ========== Cleanup ==========
def test_zz_cleanup(client):
    for k in ("t_admin",):
        if k in _ids:
            client.delete(f"{API}/templates/{_ids[k]}")
    if "c1" in _ids:
        client.delete(f"{API}/customers/{_ids['c1']}")


# ========== AUTH RATE LIMIT (LAST — sends 8+ bad logins) ==========
def test_zzz_auth_rate_limit(anon_client):
    """Send many wrong passwords — at least one must return 429.
    Note: backend may run multiple workers/replicas; each has its own
    in-memory rate-limit counter, so we make more attempts to ensure hit."""
    got_429 = False
    for i in range(30):
        r = anon_client.post(f"{API}/auth/login", json={"password": f"badpw-{i}"})
        if r.status_code == 429:
            got_429 = True
            break
        assert r.status_code == 401, f"unexpected {r.status_code}"
    assert got_429, "expected 429 after multiple failed attempts"
