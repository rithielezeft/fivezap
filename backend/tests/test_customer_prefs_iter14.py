# Iteration 14: per-customer prefs (custom price, fixed plan, discount block, reminder selection) + admin alert text
import os
import sys
import json
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
    """Fresh loop + fresh motor client + empty prefs cache for each in-process call."""
    from services import mongo_store, customer_prefs
    mongo_store._db = None
    mongo_store._client = None
    customer_prefs._cache.clear()
    return asyncio.run(coro_fn())


def put(token, pid, body):
    r = requests.put(f"{BASE_URL}/api/customer-prefs/{pid}", headers=H(token), json=body, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def info(pid):
    r = requests.get(f"{BASE_URL}/api/payments/customer/{pid}", timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Auth + CRUD ----------
class TestPrefsApi:
    def test_requires_auth(self):
        assert requests.get(f"{BASE_URL}/api/customer-prefs/{J2}", timeout=30).status_code == 401
        assert requests.put(f"{BASE_URL}/api/customer-prefs/{J2}", json={}, timeout=30).status_code == 401

    def test_get_default(self, token):
        r = requests.get(f"{BASE_URL}/api/customer-prefs/{J3}", headers=H(token), timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["fixed_plan"] is None and d["no_discount"] is False and d["notify_events"] is None
        assert set(d["default_prices"].keys()) == {"1", "3", "6", "12"}
        assert len(d["events"]) == 7

    def test_put_and_persist(self, token):
        doc = put(token, J2, {"prices": {"1": "25,00", "3": ""}, "fixed_plan": None, "no_discount": False,
                              "notify_events": ["expiration_0d", "bogus"]})
        assert doc["prices"] == {"1": 2500} and doc["notify_events"] == ["expiration_0d"]
        d = requests.get(f"{BASE_URL}/api/customer-prefs/{J2}", headers=H(token), timeout=30).json()
        assert d["prices"] == {"1": 2500} and d["notify_events"] == ["expiration_0d"]

    def test_invalid_value_400(self, token):
        r = requests.put(f"{BASE_URL}/api/customer-prefs/{J3}", headers=H(token), json={"prices": {"1": "abc"}}, timeout=30)
        assert r.status_code == 400
        r = requests.put(f"{BASE_URL}/api/customer-prefs/{J3}", headers=H(token), json=[1], timeout=30)
        assert r.status_code == 400

    def test_dot_decimal_price(self, token):
        # Users may type "25.50" — expected 2550 cents
        doc = put(token, J3, {"prices": {"1": "25.50"}})
        put(token, J3, {})  # reset
        assert doc["prices"]["1"] == 2550, f"'25.50' parsed as {doc['prices']['1']} cents"


# ---------- Custom price on pay info + linked accounts ----------
class TestCustomPrice:
    def test_pay_info_price(self, token):
        put(token, J2, {"prices": {"1": "25,00"}})
        d = info(J2)
        assert d["prices_cents"]["1"] == 2500
        assert d["discounts_blocked"] is False

    def test_linked_accounts_price(self):
        d = info(MAIN)
        acc = next(a for a in d["linked_accounts"] if a["id"] == J2)
        assert acc["prices"]["1"] == 2500
        main_price = d["prices_cents"]["1"]
        print("main mensal", main_price)


# ---------- Fixed plan + create_payment (mocked InfinitePay) ----------
def _mock(monkeypatch):
    from services import payment_accounts as pa, infinitepay, mongo_store

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


class TestFixedPlan:
    def test_fixed_plan_info(self, token):
        put(token, J2, {"prices": {"1": "25,00"}, "fixed_plan": 3})
        d = info(J2)
        assert list(d["prices_cents"].keys()) == ["3"]

    def test_create_payment_wrong_plan_400(self, token, monkeypatch):
        from fastapi import HTTPException
        from routers import payments
        from routers.payments import PaymentCreate
        _mock(monkeypatch)
        with pytest.raises(HTTPException) as e:
            run(lambda: payments.create_payment(PaymentCreate(customer_id=J2, plan_months=1)))
        assert e.value.status_code == 400 and "Plano indisponível" in e.value.detail

    def test_create_payment_fixed_plan_ok(self, token, monkeypatch):
        from routers import payments
        from routers.payments import PaymentCreate
        _mock(monkeypatch)
        res = run(lambda: payments.create_payment(PaymentCreate(customer_id=J2, plan_months=3)))
        CREATED.append(res["payment_id"])
        assert res["amount_cents"] > 0

    def test_create_payment_multi_custom_price(self, token, monkeypatch):
        put(token, J2, {"prices": {"1": "25,00"}})
        from routers import payments
        from routers.payments import PaymentCreate
        _mock(monkeypatch)
        main_price = info(MAIN)["prices_cents"]["1"]
        res = run(lambda: payments.create_payment(PaymentCreate(customer_id=MAIN, plan_months=1, extra_customer_ids=[J2])))
        CREATED.append(res["payment_id"])
        assert res["amount_cents"] == main_price + 2500, (main_price, res["amount_cents"])


# ---------- No discount ----------
class TestNoDiscount:
    def test_blocked(self, token):
        put(token, J2, {"no_discount": True})
        assert info(J2)["discounts_blocked"] is True

    def test_coupon_and_auto_blocked(self, token):
        from services.coupon import validate_coupon
        from services.discount import get_active_discount

        async def go():
            return await validate_coupon("ANYCODE", J2), await get_active_discount(J2)
        v, d = run(go)
        assert v["valid"] is False and v["reason"] == "Descontos não disponíveis para este cliente"
        assert d is None

    def test_coupon_validate_endpoint(self):
        r = requests.post(f"{BASE_URL}/api/coupons/validate", json={"code": "ANYCODE", "customer_id": J2}, timeout=30)
        print("coupon validate", r.status_code, r.text[:200])
        if r.status_code == 200:
            assert r.json().get("valid") is False


# ---------- Reminder selection ----------
class TestReminders:
    def test_wants_event(self, token):
        put(token, J2, {"notify_events": ["expiration_0d"]})
        from services.customer_prefs import wants_event

        async def go():
            return await wants_event(J2, "expiration_3d"), await wants_event(J2, "expiration_0d"), await wants_event(J3, "expiration_3d")
        a, b, c = run(go)
        assert a is False and b is True and c is True


# ---------- Admin alert text ----------
class TestAdminAlert:
    def test_alert_lines_in_code(self):
        src = open(f"{BACKEND_DIR}/routers/payments.py", encoding="utf-8").read()
        for s in ("💳 Pagamento:", "🍀 Trevo da Sorte:", "Logins no pagamento", "🏷️ Desconto:", "Mercado Pago (Pix)", "InfinitePay"):
            assert s in src, s


# ---------- Cleanup ----------
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
