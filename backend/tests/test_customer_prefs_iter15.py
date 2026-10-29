# Iteration 15: retest of iter14 action items (price parsing, auto_coupon skip, Avisos filter, extras fixed_plan, blocked extras pricing)
import os
import sys
import asyncio
import sqlite3

import pytest
import requests
from dotenv import load_dotenv

BACKEND_DIR = "/app/backend"
sys.path.insert(0, BACKEND_DIR)
load_dotenv("/app/frontend/.env")
load_dotenv(f"{BACKEND_DIR}/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_PW = "Rithi0518@"
MAIN, J2, J3 = "227470206", "227470351", "227470352"
CREATED = []


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PW}, timeout=30)
    if r.status_code != 200:
        pytest.skip("login failed")
    return r.json()["access_token"]


def H(t):
    return {"Authorization": f"Bearer {t}"}


def run(coro_fn):
    from services import mongo_store, customer_prefs
    mongo_store._db = None
    mongo_store._client = None
    customer_prefs._cache.clear()
    return asyncio.run(coro_fn())


def put(token, pid, body, code=200):
    r = requests.put(f"{BASE_URL}/api/customer-prefs/{pid}", headers=H(token), json=body, timeout=30)
    assert r.status_code == code, r.text
    return r.json()


def info(pid):
    r = requests.get(f"{BASE_URL}/api/payments/customer/{pid}", timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Price parsing ----------
class TestParsing:
    def test_parse_formats(self, token):
        doc = put(token, J3, {"prices": {"1": "25,50", "3": "25.50", "6": "R$ 1.025,50", "12": "10.000,00"}})
        assert doc["prices"] == {"1": 2550, "3": 2550, "6": 102550, "12": 1000000}, doc

    def test_parse_unit(self):
        from services.customer_prefs import parse_brl
        assert parse_brl("25,50") == 2550 and parse_brl("25.50") == 2550 and parse_brl("R$ 1.025,50") == 102550
        assert parse_brl("1.000.000") == 100000000

    @pytest.mark.parametrize("val", ["0", "0,00", "10000,01", "R$ 10.000,01", "-5", "abc", 0])
    def test_invalid_400(self, token, val):
        r = requests.put(f"{BASE_URL}/api/customer-prefs/{J3}", headers=H(token), json={"prices": {"1": val}}, timeout=30)
        assert r.status_code == 400, (val, r.status_code, r.text)

    def test_reset(self, token):
        put(token, J3, {})


# ---------- auto_coupon sweep skips no_discount ----------
def test_auto_coupon_skips_blocked(token, monkeypatch):
    put(token, J2, {"no_discount": True})
    put(token, J3, {})
    from services import auto_coupon, notifier
    sent = []

    async def fake_users(limit=10000):
        return [{"id": J2, "username": "joaonew2"}, {"id": J3, "username": "joaonew3"}]

    async def fake_get_setting(key, default=None):
        return None

    async def noop(*a, **k):
        return None

    async def tpl(_k):
        return {"body": "x"}

    async def fake_coupon(uid, p, t, m):
        return {"code": f"VOLTATEST{uid}"}

    async def fake_send(ev, phone, ctx, customer_id=None):
        sent.append(customer_id)
        return True

    async def tru(*a, **k):
        return True
    monkeypatch.setattr(auto_coupon.painel, "list_users", fake_users)
    monkeypatch.setattr(auto_coupon, "get_setting", fake_get_setting)
    monkeypatch.setattr(auto_coupon, "set_setting", noop)
    monkeypatch.setattr(auto_coupon, "_get_bool", tru)
    monkeypatch.setattr(auto_coupon, "_create_personal_coupon", fake_coupon)
    monkeypatch.setattr(auto_coupon, "send_notification", fake_send)
    monkeypatch.setattr(auto_coupon, "compute_expiration_info", lambda u: {"status": "expired", "days_until_expiry": -10})
    monkeypatch.setattr(auto_coupon, "extract_whatsapp", lambda u: "5500000000000")
    monkeypatch.setattr(notifier, "get_template", tpl)
    n = run(auto_coupon.sweep_once)
    assert sent == [J3] and n == 1, sent


# ---------- Avisos preview ----------
class TestUpcoming:
    def test_plan_for_unit(self, token, monkeypatch):
        put(token, J2, {"no_discount": True, "notify_events": ["expiration_0d"]})
        from services import upcoming
        from datetime import date
        plan = [(e, date(2030, 1, 1), 0) for e in ("expiration_7d", "expiration_0d", "expired_3d", "auto_recovery_coupon")]
        monkeypatch.setattr(upcoming, "_expiration_plan", lambda u, cfg: plan)

        async def go():
            return await upcoming._plan_for({"id": J2}, {}), await upcoming._plan_for({"id": J3}, {})
        a, b = run(go)
        assert [p[0] for p in a] == ["expiration_0d"]
        assert len(b) == 4

    def test_api_notifications_filtered(self, token):
        put(token, J2, {"no_discount": True, "notify_events": ["expiration_0d"]})
        r = requests.get(f"{BASE_URL}/api/painel/users/{J2}/notifications", headers=H(token), timeout=60)
        assert r.status_code == 200, r.text
        keys = [x["event_key"] for x in r.json()["upcoming"]]
        assert set(keys) <= {"expiration_0d"}, keys
        r = requests.get(f"{BASE_URL}/api/painel/users/{J3}/notifications", headers=H(token), timeout=60)
        keys3 = [x["event_key"] for x in r.json()["upcoming"]]
        print("J3 events", keys3)
        assert len(keys3) > 1


# ---------- Linked accounts + create_payment ----------
def _mock(monkeypatch, pct=None):
    from services import payment_accounts as pa, infinitepay, mongo_store, discount

    async def ep():
        return ["infinitepay"]

    async def pick(p):
        return {"id": "TEST_ip", "provider": p, "handle": "testh"}

    async def ip_link(**kw):
        return {"url": "https://example.invalid/ip", "amount": kw["amount_cents"]}

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(pa, "enabled_providers", ep)
    monkeypatch.setattr(pa, "pick_account", pick)
    monkeypatch.setattr(infinitepay, "create_payment_link", ip_link)
    monkeypatch.setattr(mongo_store, "upsert_payment", noop)
    if pct:
        async def disc(cid):
            return {"percent": pct}
        monkeypatch.setattr(discount, "get_active_discount", disc)


class TestExtras:
    def test_linked_accounts_fields(self, token):
        put(token, J2, {"fixed_plan": 3, "no_discount": True})
        accs = {a["id"]: a for a in info(MAIN)["linked_accounts"]}
        assert accs[J2]["fixed_plan"] == 3 and accs[J2]["discounts_blocked"] is True
        assert accs[J3]["fixed_plan"] is None and accs[J3]["discounts_blocked"] is False

    def test_extra_fixed_plan_conflict_400(self, token, monkeypatch):
        put(token, J2, {"fixed_plan": 3})
        from fastapi import HTTPException
        from routers import payments
        from routers.payments import PaymentCreate
        _mock(monkeypatch)
        with pytest.raises(HTTPException) as e:
            run(lambda: payments.create_payment(PaymentCreate(customer_id=MAIN, plan_months=1, extra_customer_ids=[J2])))
        assert e.value.status_code == 400 and "só pode renovar em outro plano" in e.value.detail

    def test_extra_fixed_plan_match_ok(self, token, monkeypatch):
        put(token, J2, {"fixed_plan": 3})
        from routers import payments
        from routers.payments import PaymentCreate
        _mock(monkeypatch)
        res = run(lambda: payments.create_payment(PaymentCreate(customer_id=MAIN, plan_months=3, extra_customer_ids=[J2])))
        CREATED.append(res["payment_id"])
        assert res["amount_cents"] == 9000 * 2, res

    def test_blocked_extra_full_price_with_discount(self, token, monkeypatch):
        put(token, J2, {"no_discount": True})
        put(token, J3, {})
        from routers import payments
        from routers.payments import PaymentCreate
        _mock(monkeypatch, pct=10)
        res = run(lambda: payments.create_payment(PaymentCreate(customer_id=MAIN, plan_months=1, extra_customer_ids=[J2, J3])))
        CREATED.append(res["payment_id"])
        # main 3000 -10% = 2700, J2 blocked 3000, J3 2700
        assert res["amount_cents"] == 2700 + 3000 + 2700, res


def test_zz_cleanup():
    con = sqlite3.connect(f"{BACKEND_DIR}/whatsflow.db")
    for pid in CREATED:
        con.execute("DELETE FROM payments WHERE id=?", (pid,))
    con.commit()
    con.close()
    from pymongo import MongoClient
    from services.mongo_store import _clean_url
    url = _clean_url(os.environ.get("WHATSFLOW_MONGO_URL")) or os.environ.get("MONGO_URL")
    dbn = (os.environ.get("WHATSFLOW_DB_NAME") if os.environ.get("WHATSFLOW_MONGO_URL") else None) or os.environ.get("DB_NAME")
    mc = MongoClient(url, serverSelectionTimeoutMS=8000)
    mc[dbn].payments.delete_many({"$or": [{"_id": {"$in": CREATED}}, {"id": {"$in": CREATED}}]})
    mc[dbn].customer_prefs.delete_many({"_id": {"$in": [MAIN, J2, J3]}})
    assert mc[dbn].customer_prefs.count_documents({"_id": {"$in": [MAIN, J2, J3]}}) == 0
