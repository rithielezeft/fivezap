# Read-only API tests: /api/painel/users _next_notification + /api/painel/users/{id}/notifications
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_PASSWORD = "Rithi0518@"
VALID_STATUS = {"scheduled", "today", "sent", "queued", "missed", "cancelled", "disabled"}


@pytest.fixture(scope="module")
def auth():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PASSWORD}, timeout=20)
    if r.status_code != 200:
        pytest.skip("login failed")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def users(auth):
    r = requests.get(f"{BASE_URL}/api/painel/users", headers=auth, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()["users"]


# list_users enrichment
def test_users_have_next_notification(users):
    assert len(users) > 0
    for u in users:
        assert "_next_notification" in u
        n = u["_next_notification"]
        if n is not None:
            assert set(n.keys()) >= {"event_key", "title", "date", "kind"}
            assert n["kind"] in ("expiration", "trial")
            assert isinstance(n["title"], str) and n["title"]
    print([(u.get("id"), u["_next_notification"]) for u in users])


# per-user notifications endpoint
def test_user_notifications_227427597(auth, users):
    uid = "227427597"
    u = next((x for x in users if str(x.get("id")) == uid), None)
    if not u:
        pytest.skip("user 227427597 not in cache")
    r = requests.get(f"{BASE_URL}/api/painel/users/{uid}/notifications", headers=auth, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("upcoming", "history", "duplicate_sends", "is_trial", "name", "whatsapp", "expires_at"):
        assert k in d
    assert d["user_id"] == uid
    assert isinstance(d["upcoming"], list) and isinstance(d["history"], list)
    assert isinstance(d["duplicate_sends"], int)
    assert d["is_trial"] is False
    assert len(d["upcoming"]) > 0
    login = u.get("username") or ""
    name = (u.get("full_name") or u.get("name") or login).strip()
    rendered = 0
    for it in d["upcoming"]:
        assert set(it.keys()) >= {"event_key", "title", "when", "status", "body", "image_url"}
        assert it["status"] in VALID_STATUS
        if it["body"]:
            rendered += 1
            assert not re.search(r"\{[a-z_]+\}", it["body"]), f"unrendered placeholder: {it['body'][:200]}"
    assert rendered > 0
    assert any((name and name in (it["body"] or "")) or (login and login in (it["body"] or "")) for it in d["upcoming"])
    print(d["upcoming"][0])


def test_all_users_notifications_ok(auth, users):
    for u in users:
        uid = str(u.get("id") or u.get("user_id") or u.get("username"))
        r = requests.get(f"{BASE_URL}/api/painel/users/{uid}/notifications", headers=auth, timeout=30)
        assert r.status_code == 200, (uid, r.text)
        # next_notification should match first non-past upcoming item
        n = u["_next_notification"]
        if n:
            assert any(it["event_key"] == n["event_key"] for it in r.json()["upcoming"])


def test_user_notifications_404(auth):
    r = requests.get(f"{BASE_URL}/api/painel/users/999999999999/notifications", headers=auth, timeout=20)
    assert r.status_code == 404
    assert "detail" in r.json()


def test_user_notifications_401():
    r = requests.get(f"{BASE_URL}/api/painel/users/227427597/notifications", timeout=20)
    assert r.status_code == 401
