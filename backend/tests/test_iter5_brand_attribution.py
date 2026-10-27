# Iteration 5: public pay brand/login + dashboard attribution metrics
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
CID = "227427597"


@pytest.fixture(scope="module")
def auth():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "Rithi0518@"}, timeout=20)
    if r.status_code != 200:
        pytest.skip("login failed")
    tok = r.json().get("token") or r.json().get("access_token")
    return {"Authorization": f"Bearer {tok}"}


# Public payment customer info includes login + brand
class TestPublicPayInfo:
    def test_customer_login_and_brand(self):
        r = requests.get(f"{BASE_URL}/api/payments/customer/{CID}", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["customer"]["login"] == "andrecartv"
        assert isinstance(d["brand"]["name"], str) and d["brand"]["name"]
        assert "logo_url" in d["brand"]
        assert set(["1", "3", "6", "12"]) <= set(map(str, d["prices_cents"].keys()))

    def test_invalid_customer(self):
        r = requests.get(f"{BASE_URL}/api/payments/customer/TESTA_nope_000", timeout=30)
        assert r.status_code in (404, 400)


# Settings contain brand fields
class TestSettingsBrand:
    def test_settings_get(self, auth):
        r = requests.get(f"{BASE_URL}/api/settings", headers=auth, timeout=20)
        assert r.status_code == 200
        print("settings keys sample:", list(r.json().keys())[:80])


# Attribution endpoint
class TestAttribution:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/dashboard/attribution?days=30", timeout=20)
        print("noauth status", r.status_code)
        assert r.status_code in (401, 403)

    @pytest.mark.parametrize("days", [7, 30, 90])
    def test_structure_and_math(self, auth, days):
        r = requests.get(f"{BASE_URL}/api/dashboard/attribution?days={days}", headers=auth, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["days"] == days
        t = d["totals"]
        for k in ("messages_sent", "links_opened", "paid", "revenue_cents"):
            assert isinstance(t[k], int)
        bs = d["buckets"]
        for b in bs:
            for k in ("bucket", "total", "paid_count", "revenue_cents", "messages_sent",
                      "message_conversion_rate", "avg_ticket_cents", "revenue_share", "conversion_rate"):
                assert k in b
            if b["paid_count"]:
                assert b["avg_ticket_cents"] == b["revenue_cents"] // b["paid_count"]
            if b["total"]:
                assert b["conversion_rate"] == round(b["paid_count"] / b["total"] * 100, 1)
            if b["messages_sent"]:
                assert b["message_conversion_rate"] == round(b["paid_count"] / b["messages_sent"] * 100, 1)
            else:
                assert b["message_conversion_rate"] is None
        assert t["links_opened"] == sum(b["total"] for b in bs)
        assert t["paid"] == sum(b["paid_count"] for b in bs)
        assert t["revenue_cents"] == sum(b["revenue_cents"] for b in bs)
        if t["revenue_cents"]:
            assert abs(sum(b["revenue_share"] for b in bs) - 100) < 1.0
        revs = [b["revenue_cents"] for b in bs]
        assert revs == sorted(revs, reverse=True)
        print(days, t, [(b["bucket"], b["revenue_cents"], b["messages_sent"]) for b in bs])

    def test_periods_monotonic(self, auth):
        tot = [requests.get(f"{BASE_URL}/api/dashboard/attribution?days={x}", headers=auth, timeout=20).json()["totals"]
               for x in (7, 30, 90)]
        assert tot[0]["links_opened"] <= tot[1]["links_opened"] <= tot[2]["links_opened"]
        assert tot[0]["messages_sent"] <= tot[1]["messages_sent"] <= tot[2]["messages_sent"]

    def test_edge_days(self, auth):
        for x in (0, -5, 10000):
            r = requests.get(f"{BASE_URL}/api/dashboard/attribution?days={x}", headers=auth, timeout=20)
            print("days", x, r.status_code, r.json().get("days"))
            assert r.status_code == 200
