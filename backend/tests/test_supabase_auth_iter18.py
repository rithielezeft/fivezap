# Iteration 18: Supabase email login + TOTP 2FA, legacy toggle, Supabase mirror, finance raffle summary,
# command templates mirrored to Atlas. Uses a throwaway Supabase user and restores all settings at the end.
import asyncio
import os
import sys
import time

import pyotp
import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_PW = "Rithi0518@"
TS = int(time.time())
QA_EMAIL = f"wf-qa-{TS}@example.com"
QA_PW = "QaTest!2345"
STATE = {}


_LOOP = asyncio.new_event_loop()


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _gotrue(method, path, **kw):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1" + path
    key = os.environ["SUPABASE_SECRET_KEY"]
    return requests.request(method, url, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=20, **kw)


def _fresh_code(secret):
    t = pyotp.TOTP(secret)
    # avoid using a code right at the window boundary / reused code
    if 30 - (time.time() % 30) < 4:
        time.sleep(5)
    return t.now()


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PW}, timeout=30)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s


@pytest.fixture(scope="module", autouse=True)
def cleanup(admin):
    yield
    # disable TOTP if enabled
    try:
        if STATE.get("secret"):
            time.sleep(1)
            r = admin.post(f"{BASE_URL}/api/auth/supabase/totp/disable",
                           json={"password": QA_PW, "code": _fresh_code(STATE["secret"])}, timeout=30)
            print("cleanup totp disable", r.status_code, r.text[:150])
    except Exception as e:
        print("cleanup totp err", e)
    r = admin.put(f"{BASE_URL}/api/auth/supabase/legacy", json={"enabled": True}, timeout=30)
    print("cleanup legacy", r.status_code, r.text)
    from database import set_setting

    async def _reset():
        await set_setting("supabase_admin_email", "")
        await set_setting("supabase_totp_enabled", "false")
    _run(_reset())
    # delete throwaway Supabase user
    try:
        r = _gotrue("POST", "/token?grant_type=password", json={"email": QA_EMAIL, "password": QA_PW})
        uid = r.json().get("user", {}).get("id") if r.status_code == 200 else None
        if uid:
            d = _gotrue("DELETE", f"/admin/users/{uid}")
            print("cleanup supabase user delete", d.status_code)
        else:
            print("cleanup: qa user not found", r.status_code)
    except Exception as e:
        print("cleanup user err", e)
    # delete template if left over
    if STATE.get("tpl_id"):
        admin.delete(f"{BASE_URL}/api/templates/{STATE['tpl_id']}", timeout=30)


class TestSupabaseFlow:
    def test_01_methods_public_default(self):
        r = requests.get(f"{BASE_URL}/api/auth/methods", timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d == {"email_login": False, "password_login": True}, d

    def test_02_link_account_validation(self, admin):
        r = admin.post(f"{BASE_URL}/api/auth/supabase/account", json={"email": QA_EMAIL, "password": "short"}, timeout=30)
        assert r.status_code == 400

    def test_03_link_account_unauth(self):
        r = requests.post(f"{BASE_URL}/api/auth/supabase/account", json={"email": QA_EMAIL, "password": QA_PW}, timeout=30)
        assert r.status_code == 401

    def test_04_link_account(self, admin):
        r = admin.post(f"{BASE_URL}/api/auth/supabase/account", json={"email": QA_EMAIL, "password": QA_PW}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["email"] == QA_EMAIL
        st = admin.get(f"{BASE_URL}/api/auth/supabase/status", timeout=20).json()
        assert st["email"] == QA_EMAIL and st["totp_enabled"] is False and st["configured"] is True
        m = requests.get(f"{BASE_URL}/api/auth/methods", timeout=20).json()
        assert m == {"email_login": True, "password_login": True}

    def test_05_relink_same_account_idempotent(self, admin):
        r = admin.post(f"{BASE_URL}/api/auth/supabase/account", json={"email": QA_EMAIL, "password": QA_PW}, timeout=30)
        assert r.status_code == 200, r.text

    def test_06_email_login_no_totp(self):
        r = requests.post(f"{BASE_URL}/api/auth/email-login", json={"email": QA_EMAIL.upper(), "password": QA_PW}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("access_token") and d.get("totp_missing") is True

    def test_07_email_login_wrong_password(self):
        r = requests.post(f"{BASE_URL}/api/auth/email-login", json={"email": QA_EMAIL, "password": "WrongPass!1"}, timeout=30)
        assert r.status_code == 401
        r = requests.post(f"{BASE_URL}/api/auth/email-login", json={"email": "other@example.com", "password": QA_PW}, timeout=30)
        assert r.status_code == 401

    def test_08_totp_start_wrong_password(self, admin):
        r = admin.post(f"{BASE_URL}/api/auth/supabase/totp/start", json={"password": "WrongPass!1"}, timeout=30)
        assert r.status_code == 400

    def test_09_totp_start_and_confirm(self, admin):
        r = admin.post(f"{BASE_URL}/api/auth/supabase/totp/start", json={"password": QA_PW}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["enroll_id"] and d["secret"] and d["qr_code"]
        STATE["qr_code"] = d["qr_code"]
        bad = admin.post(f"{BASE_URL}/api/auth/supabase/totp/confirm", json={"enroll_id": d["enroll_id"], "code": "000000"}, timeout=30)
        assert bad.status_code == 400
        r = admin.post(f"{BASE_URL}/api/auth/supabase/totp/confirm",
                       json={"enroll_id": d["enroll_id"], "code": _fresh_code(d["secret"])}, timeout=30)
        assert r.status_code == 200, r.text
        STATE["secret"] = d["secret"]
        st = admin.get(f"{BASE_URL}/api/auth/supabase/status", timeout=20).json()
        assert st["totp_enabled"] is True

    def test_09b_qr_code_is_data_uri(self):
        # frontend renders <img src={qr_code}>, so it must be a data URI (GoTrue returns raw SVG XML)
        assert STATE.get("qr_code", "").startswith("data:image"), STATE.get("qr_code", "")[:60]

    def test_10_email_login_requires_totp(self):
        assert STATE.get("secret")
        r = requests.post(f"{BASE_URL}/api/auth/email-login", json={"email": QA_EMAIL, "password": QA_PW}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("requires_totp") is True and d.get("challenge_id") and "access_token" not in d
        bad = requests.post(f"{BASE_URL}/api/auth/email-login/verify", json={"challenge_id": d["challenge_id"], "code": "000000"}, timeout=30)
        assert bad.status_code == 401
        time.sleep(1)
        ok = requests.post(f"{BASE_URL}/api/auth/email-login/verify",
                           json={"challenge_id": d["challenge_id"], "code": _fresh_code(STATE["secret"])}, timeout=30)
        assert ok.status_code == 200, ok.text
        tok = ok.json()["access_token"]
        me = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=20)
        assert me.status_code == 200
        # challenge consumed
        again = requests.post(f"{BASE_URL}/api/auth/email-login/verify",
                              json={"challenge_id": d["challenge_id"], "code": _fresh_code(STATE["secret"])}, timeout=30)
        assert again.status_code == 401

    def test_11_totp_start_when_active_rejected(self, admin):
        r = admin.post(f"{BASE_URL}/api/auth/supabase/totp/start", json={"password": QA_PW}, timeout=30)
        assert r.status_code == 400

    def test_12_legacy_toggle(self, admin):
        r = admin.put(f"{BASE_URL}/api/auth/supabase/legacy", json={"enabled": False}, timeout=30)
        assert r.status_code == 200 and r.json()["password_login"] is False
        l = requests.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PW}, timeout=30)
        assert l.status_code == 403, l.text
        m = requests.get(f"{BASE_URL}/api/auth/methods", timeout=20).json()
        assert m["password_login"] is False
        # existing token still works
        assert admin.get(f"{BASE_URL}/api/auth/supabase/status", timeout=20).status_code == 200
        r = admin.put(f"{BASE_URL}/api/auth/supabase/legacy", json={"enabled": True}, timeout=30)
        assert r.status_code == 200
        l = requests.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PW}, timeout=30)
        assert l.status_code == 200

    def test_13_totp_disable_wrong_code(self, admin):
        r = admin.post(f"{BASE_URL}/api/auth/supabase/totp/disable", json={"password": QA_PW, "code": "000000"}, timeout=30)
        assert r.status_code == 400
        st = admin.get(f"{BASE_URL}/api/auth/supabase/status", timeout=20).json()
        assert st["totp_enabled"] is True

    def test_14_totp_disable(self, admin):
        time.sleep(1)
        r = admin.post(f"{BASE_URL}/api/auth/supabase/totp/disable",
                       json={"password": QA_PW, "code": _fresh_code(STATE["secret"])}, timeout=30)
        assert r.status_code == 200, r.text
        STATE["secret"] = None
        st = admin.get(f"{BASE_URL}/api/auth/supabase/status", timeout=20).json()
        assert st["totp_enabled"] is False
        r = requests.post(f"{BASE_URL}/api/auth/email-login", json={"email": QA_EMAIL, "password": QA_PW}, timeout=30)
        assert r.status_code == 200 and r.json().get("access_token")


class TestMirrorFinanceTemplates:
    def test_mirror_requires_auth(self):
        assert requests.get(f"{BASE_URL}/api/supabase/mirror", timeout=20).status_code == 401

    def test_mirror_run(self, admin):
        r = admin.post(f"{BASE_URL}/api/supabase/mirror/run", timeout=120)
        assert r.status_code == 200, r.text
        c = r.json()["counts"]
        print("mirror counts", c)
        assert c["customers"] > 500 and c["trials"] > 50 and c["painel_users"] > 0
        st = admin.get(f"{BASE_URL}/api/supabase/mirror", timeout=20).json()
        assert st["configured"] is True and st["last_error"] is None and st["last_run"]

    def test_finance_raffle_october(self, admin):
        r = admin.get(f"{BASE_URL}/api/finance/summary?month=2026-10", timeout=60)
        assert r.status_code == 200
        rf = r.json()["raffle"]
        print("raffle", rf)
        for k in ("clovers", "clover_cents", "revenue_cents", "draws", "cost_credits", "cost_cents", "profit_cents"):
            assert k in rf
        assert len(rf["draws"]) == 1 and rf["draws"][0]["winner"] == "carmoviz23new"
        assert rf["cost_credits"] == 1
        assert rf["revenue_cents"] == rf["clovers"] * rf["clover_cents"]
        assert rf["profit_cents"] == rf["revenue_cents"] - rf["cost_cents"]

    def test_finance_raffle_empty_month(self, admin):
        rf = admin.get(f"{BASE_URL}/api/finance/summary?month=2025-01", timeout=60).json()["raffle"]
        assert rf["draws"] == [] and rf["cost_credits"] == 0

    def test_template_atlas_mirror(self, admin):
        from services.mongo_store import _get_db

        async def _find(i):
            return await _get_db().command_templates.find_one({"_id": str(i)})
        trig = f"/qa_test_{TS}"
        r = admin.post(f"{BASE_URL}/api/templates", json={"name": f"TEST_qa {TS}", "trigger_command": trig,
                                                         "system_type": "iptv", "enabled": False, "trigger_source": "admin"}, timeout=30)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        STATE["tpl_id"] = tid
        doc = _run(_find(tid))
        assert doc and doc["trigger_command"] == trig
        r = admin.put(f"{BASE_URL}/api/templates/{tid}", json={"name": f"TEST_qa upd {TS}"}, timeout=30)
        assert r.status_code == 200
        doc = _run(_find(tid))
        assert doc["name"] == f"TEST_qa upd {TS}"
        r = admin.delete(f"{BASE_URL}/api/templates/{tid}", timeout=30)
        assert r.status_code in (200, 204)
        STATE["tpl_id"] = None
        assert _run(_find(tid)) is None
