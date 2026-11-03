# Iteration 9: Mercado Pago provider, multi-account routing, multi-points checkout, adult toggle, finance paid_renewal_failed
import os
import sys
import asyncio
import json

import pytest
import requests
from dotenv import load_dotenv

BACKEND_DIR = "/app/backend"
sys.path.insert(0, BACKEND_DIR)
load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_PW = "Rithi0518@"
MAIN_ID = "227470206"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PW}, timeout=30)
    if r.status_code != 200:
        pytest.skip("login failed")
    return r.json()["access_token"]


def H(t):
    return {"Authorization": f"Bearer {t}"}


# ---------- Public API (no auth) ----------
class TestPublicEndpoints:
    def test_customer_info_has_new_fields(self):
        r = requests.get(f"{BASE_URL}/api/payments/customer/{MAIN_ID}", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert isinstance(d["providers"], list) and d["providers"]
        assert d["mp_fee_percent"] == 0.99
        assert isinstance(d["adult_default"], bool)
        ids = {a["id"] for a in d["linked_accounts"]}
        assert {"227470351", "227470352"} <= ids, ids
        assert MAIN_ID not in ids
        logins = {a["login"] for a in d["linked_accounts"]}
        assert {"joaonew2", "joaonew3"} <= logins

    def test_mp_status_unknown_404(self):
        r = requests.get(f"{BASE_URL}/api/payments/mp-status/nonexistent-xyz", timeout=30)
        assert r.status_code == 404

    def test_mp_webhook_unknown(self):
        r = requests.post(f"{BASE_URL}/api/payments/mp-webhook", json={"data": {"id": "999999999999"}}, timeout=30)
        assert r.status_code == 200
        assert r.json().get("received") is True

    def test_mp_webhook_empty(self):
        r = requests.post(f"{BASE_URL}/api/payments/mp-webhook", json={}, timeout=30)
        assert r.status_code == 200 and r.json() == {"received": True}

    def test_payment_accounts_requires_auth(self):
        assert requests.get(f"{BASE_URL}/api/payment-accounts", timeout=30).status_code == 401
        assert requests.put(f"{BASE_URL}/api/payment-accounts", json={"accounts": []}, timeout=30).status_code == 401


# ---------- Admin payment accounts API ----------
class TestPaymentAccountsApi:
    def test_get(self, token):
        r = requests.get(f"{BASE_URL}/api/payment-accounts", headers=H(token), timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "accounts" in d and "providers_enabled" in d and d["mp_fee_percent"] == 0.99

    def test_invalid_provider_400(self, token):
        r = requests.put(f"{BASE_URL}/api/payment-accounts", headers=H(token),
                         json={"accounts": [{"provider": "paypal"}]}, timeout=30)
        assert r.status_code == 400

    def test_finance_summary(self, token):
        r = requests.get(f"{BASE_URL}/api/finance/summary", headers=H(token), timeout=60)
        assert r.status_code == 200, r.text


# ---------- In-process logic (mocked providers) ----------
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


class TestRouting:
    def test_mp_amount(self):
        from services.payment_accounts import mp_amount
        assert mp_amount(3000) == 3030
        assert mp_amount(6000) == 6059  # 6059.4
        assert mp_amount(2550) == 2575  # 2575.245

    def test_pick_account(self, monkeypatch):
        from services import payment_accounts as pa
        accs = [
            {"id": "a1", "provider": "infinitepay", "handle": "h1", "monthly_limit_cents": 1000, "enabled": True},
            {"id": "a2", "provider": "infinitepay", "handle": "h2", "monthly_limit_cents": 1000, "enabled": False},
            {"id": "a3", "provider": "infinitepay", "handle": "h3", "monthly_limit_cents": 2000, "enabled": True},
            {"id": "m1", "provider": "mercadopago", "access_token": "", "enabled": True},
            {"id": "m2", "provider": "mercadopago", "access_token": "APP_USR-x", "enabled": True},
        ]
        totals = {}

        async def la():
            return accs

        async def mt():
            return totals
        monkeypatch.setattr(pa, "load_accounts", la)
        monkeypatch.setattr(pa, "month_totals", mt)
        assert _run(pa.pick_account("infinitepay"))["id"] == "a1"
        totals.update({"a1": 1000})
        assert _run(pa.pick_account("infinitepay"))["id"] == "a3"
        totals.update({"a3": 2500})
        assert _run(pa.pick_account("infinitepay"))["id"] == "a3"  # all full -> last
        assert _run(pa.pick_account("mercadopago"))["id"] == "m2"  # m1 has no token
        assert _run(pa.enabled_providers()) == ["infinitepay", "mercadopago"]

    def test_public_view_masks_token(self):
        from services.payment_accounts import public_view
        v = public_view({"id": "x", "provider": "mercadopago", "access_token": "APP_USR-1234567890abcdef"}, {"x": 500})
        assert "access_token" not in v and v["has_token"] and v["month_received_cents"] == 500
        assert "1234567890ab" not in v["access_token_masked"]


class TestCreatePaymentMocked:
    created = []

    def _create(self, monkeypatch, provider, extra):
        from routers import payments
        from routers.payments import PaymentCreate
        from services import payment_accounts as pa, infinitepay, mercadopago, mongo_store

        async def ep():
            return ["infinitepay", "mercadopago"]

        async def pick(p):
            return {"id": "TEST_ip" if p == "infinitepay" else "TEST_mp", "provider": p, "handle": "testh", "access_token": "TEST_TOKEN"}

        async def ip_link(**kw):
            return {"url": "https://example.invalid/ip", "amount": kw["amount_cents"]}

        async def pix(tok, amount, desc, **kw):
            assert tok == "TEST_TOKEN"
            return {"id": "TESTMP123", "status": "pending", "qr_code": "000201", "qr_code_base64": "AAA", "ticket_url": "https://example.invalid/mp"}

        async def noop(*a, **k):
            return None
        monkeypatch.setattr(pa, "enabled_providers", ep)
        monkeypatch.setattr(pa, "pick_account", pick)
        monkeypatch.setattr(infinitepay, "create_payment_link", ip_link)
        monkeypatch.setattr(mercadopago, "create_pix", pix)
        monkeypatch.setattr(mongo_store, "upsert_payment", noop)
        res = asyncio.run(payments.create_payment(PaymentCreate(
            customer_id=MAIN_ID, plan_months=1, provider=provider,
            extra_customer_ids=extra, adult_channels=False)))
        TestCreatePaymentMocked.created.append(res["payment_id"])
        return res

    def _row(self, pid):
        import sqlite3
        con = sqlite3.connect(f"{BACKEND_DIR}/whatsflow.db")
        con.row_factory = sqlite3.Row
        r = dict(con.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone())
        con.close()
        return r

    def test_ip_multi_points(self, monkeypatch):
        res = self._create(monkeypatch, "infinitepay", ["227470351", "999999", "227470351"])
        assert res["provider"] == "infinitepay" and res["points"] == 2
        row = self._row(res["payment_id"])
        assert json.loads(row["extra_customer_ids"]) == ["227470351"]
        assert row["provider"] == "infinitepay" and row["account_id"] == "TEST_ip"
        assert row["adult_channels"] == 0 and row["mp_payment_id"] is None
        TestCreatePaymentMocked.ip_amount = res["amount_cents"]

    def test_mp_amount_fee(self, monkeypatch):
        res = self._create(monkeypatch, "mercadopago", ["227470351"])
        base = TestCreatePaymentMocked.ip_amount
        assert res["provider"] == "mercadopago"
        assert res["amount_cents"] == int(round(base * 1.0099)), (base, res["amount_cents"])
        assert res["pix_qr_code"] == "000201"
        row = self._row(res["payment_id"])
        assert row["mp_payment_id"] == "TESTMP123" and row["account_id"] == "TEST_mp"
        assert row["order_nsu"].startswith("mp-")

    def test_zz_cleanup(self):
        import sqlite3
        con = sqlite3.connect(f"{BACKEND_DIR}/whatsflow.db")
        for pid in TestCreatePaymentMocked.created:
            con.execute("DELETE FROM payments WHERE id=?", (pid,))
        con.commit()
        con.close()
        from pymongo import MongoClient
        load_dotenv(f"{BACKEND_DIR}/.env")
        from services.mongo_store import _clean_url
        url = _clean_url(os.environ.get("WHATSFLOW_MONGO_URL")) or os.environ.get("MONGO_URL")
        dbn = (os.environ.get("WHATSFLOW_DB_NAME") if os.environ.get("WHATSFLOW_MONGO_URL") else None) or os.environ.get("DB_NAME")
        mc = MongoClient(url, serverSelectionTimeoutMS=8000)
        try:
            mc[dbn].payments.delete_many({"_id": {"$in": TestCreatePaymentMocked.created}})
        except Exception as e:
            print("mongo cleanup", e)
