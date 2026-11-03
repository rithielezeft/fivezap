# Iteration 6: Financeiro receipts/credits/PDF/send, cron monthly-report auth, geography customers (READ-ONLY prod)
import os
import pytest
import requests
from dotenv import dotenv_values

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
CRON_SECRET = dotenv_values("/app/backend/.env").get("WEBHOOK_CRON_SECRET")
CUSTOMER = "227427597"
MONTH = None


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": "Rithi0518@"})
    if r.status_code != 200:
        pytest.skip("login failed")
    tok = r.json().get("token") or r.json().get("access_token")
    s.headers["Authorization"] = f"Bearer {tok}"
    return s


@pytest.fixture(scope="module")
def summary(client):
    r = client.get(f"{BASE_URL}/api/finance/summary", timeout=60)
    assert r.status_code == 200
    return r.json()


# --- Receipts per customer
class TestReceipts:
    def test_customer_payments(self, client):
        r = client.get(f"{BASE_URL}/api/finance/customer/{CUSTOMER}/payments", timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["customer_id"] == CUSTOMER
        assert isinstance(d["payments"], list) and len(d["payments"]) >= 4
        assert all(p["customer_id"] == CUSTOMER for p in d["payments"])
        assert not any(k.startswith("_") for p in d["payments"] for k in p)
        assert d["total_paid_cents"] == sum(p["amount_cents"] for p in d["payments"] if p["status"] == "paid")
        assert any(p["id"].startswith("TESTR_") for p in d["payments"])
        print("login:", d["login"], "count:", len(d["payments"]),
              "receipts:", sum(1 for p in d["payments"] if p.get("receipt_url")))

    def test_customer_payments_unknown(self, client):
        r = client.get(f"{BASE_URL}/api/finance/customer/NOPE_xyz/payments")
        assert r.status_code == 200
        assert r.json()["payments"] == [] and r.json()["total_paid_cents"] == 0

    def test_customer_payments_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/finance/customer/{CUSTOMER}/payments")
        assert r.status_code == 401


# --- Credits in summary
class TestCredits:
    def test_credits_shape(self, summary):
        c = summary["credits"]
        for k in ("used", "per_plan", "unit_cost_cents", "cost_cents", "profit_cents"):
            assert k in c
        print("credits:", c, "by_period:", summary["by_period"])

    def test_credits_math(self, summary):
        c = summary["credits"]
        per = {int(k): v for k, v in c["per_plan"].items()}
        expected = sum(per.get(int(m), float(m)) * n for m, n in summary["by_period"].items())
        assert abs(c["used"] - expected) < 0.01
        assert c["cost_cents"] == round(c["used"] * c["unit_cost_cents"])  or abs(c["cost_cents"] - c["used"] * c["unit_cost_cents"]) <= 1
        if c["unit_cost_cents"]:
            assert c["profit_cents"] == summary["received"]["amount_cents"] - c["cost_cents"]
        else:
            assert c["profit_cents"] is None

    def test_bad_month_summary(self, client):
        assert client.get(f"{BASE_URL}/api/finance/summary?month=2026-13").status_code == 400


# --- PDF report + send
class TestReport:
    def test_pdf(self, client, summary):
        r = client.get(f"{BASE_URL}/api/finance/report.pdf?month={summary['month']}", timeout=90)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF" and len(r.content) > 1000
        assert "financeiro-" in r.headers.get("content-disposition", "")

    @pytest.mark.parametrize("m", ["abc", "2026-00", "2026-13", "1999-01"])
    def test_pdf_bad_month(self, client, m):
        assert client.get(f"{BASE_URL}/api/finance/report.pdf?month={m}").status_code == 400

    def test_pdf_requires_auth(self, summary):
        assert requests.get(f"{BASE_URL}/api/finance/report.pdf?month={summary['month']}").status_code == 401

    def test_send_not_configured(self, client, summary):
        r = client.post(f"{BASE_URL}/api/finance/report/send?month={summary['month']}", timeout=90)
        assert r.status_code == 200
        d = r.json()
        assert d["sent"] is False
        assert "WhatsApp do admin não configurado" in d["reason"]

    def test_send_requires_auth(self, summary):
        assert requests.post(f"{BASE_URL}/api/finance/report/send?month={summary['month']}").status_code == 401


# --- Cron (no X-Webhook-Id so nothing is written to settings/Mongo)
class TestCron:
    def test_no_token(self):
        assert requests.post(f"{BASE_URL}/api/cron/monthly-report", json={}).status_code == 401

    def test_wrong_token(self):
        r = requests.post(f"{BASE_URL}/api/cron/monthly-report", json={}, headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401

    def test_admin_token_not_accepted(self, client):
        r = requests.post(f"{BASE_URL}/api/cron/monthly-report", json={},
                          headers={"Authorization": client.headers["Authorization"]})
        assert r.status_code == 401

    def test_valid_token(self):
        assert CRON_SECRET
        r = requests.post(f"{BASE_URL}/api/cron/monthly-report", json={},
                          headers={"Authorization": f"Bearer {CRON_SECRET}"})
        assert r.status_code == 200
        assert r.json() == {"accepted": True}


# --- Geography customers
class TestGeoCustomers:
    def test_shape_and_totals(self, client):
        r = client.get(f"{BASE_URL}/api/analytics/geography/customers", timeout=90)
        assert r.status_code == 200
        d = r.json()
        assert {"regions", "customers", "totals"} <= set(d)
        assert all(c["status"] in ("active", "expired", "cancelled") for c in d["customers"])
        for s in ("active", "expired", "cancelled"):
            assert d["totals"][s] == sum(1 for c in d["customers"] if c["status"] == s)
            assert d["totals"][s] == sum(r[s] for r in d["regions"])
        for reg in d["regions"]:
            assert {"key", "label", "active", "expired", "cancelled"} <= set(reg)
        ids = [c["id"] for c in d["customers"]]
        assert len(ids) == len(set(ids)), "duplicate customer ids"
        print("totals:", d["totals"], "regions:", len(d["regions"]), "top:", d["regions"][:3])

    def test_requires_auth(self):
        assert requests.get(f"{BASE_URL}/api/analytics/geography/customers").status_code == 401
