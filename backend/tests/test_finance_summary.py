# Finance summary API (/api/finance/summary) — read-only tests
import calendar
import os
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PASSWORD = "Rithi0518@"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": PASSWORD})
    if r.status_code != 200:
        pytest.skip("login failed")
    tok = r.json().get("token") or r.json().get("access_token")
    s.headers["Authorization"] = f"Bearer {tok}"
    return s


def cur_month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


KEYS = ["month", "received", "previous_month", "today", "week", "pending", "failed", "ticket_cents",
        "conversion_percent", "coupons", "by_period", "daily", "top_clients", "latest"]


def test_unauth_401():
    r = requests.get(f"{BASE_URL}/api/finance/summary")
    assert r.status_code == 401


@pytest.mark.parametrize("bad", ["abc", "2026-13", "2026", "13-2026-01"])
def test_bad_month_400(client, bad):
    r = client.get(f"{BASE_URL}/api/finance/summary", params={"month": bad})
    assert r.status_code == 400, r.text


def test_default_month_structure(client):
    r = client.get(f"{BASE_URL}/api/finance/summary")
    assert r.status_code == 200
    d = r.json()
    for k in KEYS:
        assert k in d
    assert d["month"] == cur_month()
    assert set(d["by_period"].keys()) >= {"1", "3", "6", "12"}


def test_current_month_values_consistent(client):
    m = cur_month()
    d = client.get(f"{BASE_URL}/api/finance/summary", params={"month": m}).json()
    y, mo = map(int, m.split("-"))
    assert len(d["daily"]) == calendar.monthrange(y, mo)[1]
    assert d["daily"][0]["day"].startswith("01/")
    assert sum(x["revenue_cents"] for x in d["daily"]) == d["received"]["amount_cents"]
    assert sum(x["count"] for x in d["daily"]) == d["received"]["count"]
    assert sum(d["by_period"].values()) == d["received"]["count"]
    if d["received"]["count"]:
        assert d["ticket_cents"] == d["received"]["amount_cents"] // d["received"]["count"]
    assert len(d["latest"]) <= 10
    assert len(d["top_clients"]) <= 6
    tc = [t["amount_cents"] for t in d["top_clients"]]
    assert tc == sorted(tc, reverse=True)
    for p in d["latest"]:
        assert p["status"] == "paid"
        assert not any(k.startswith("_") for k in p)
    assert d["week"]["amount_cents"] >= d["today"]["amount_cents"]
    print("current:", d["received"], d["pending"], d["conversion_percent"], d["by_period"])


def test_seeded_testf_counts(client):
    # Compares API with seeded TESTF_ data in sqlite (current month)
    import sqlite3
    c = sqlite3.connect("/app/backend/whatsflow.db")
    m = cur_month()
    paid = c.execute("select count(*), coalesce(sum(amount_cents),0) from payments where status='paid' and substr(coalesce(paid_at,created_at),1,7)=?", (m,)).fetchone()
    pend = c.execute("select count(*) from payments where status='pending' and substr(created_at,1,7)=?", (m,)).fetchone()
    d = client.get(f"{BASE_URL}/api/finance/summary", params={"month": m}).json()
    assert d["received"]["count"] == paid[0]
    assert d["received"]["amount_cents"] == paid[1]
    assert d["pending"]["count"] == pend[0]


def test_previous_month_empty(client):
    y, mo = map(int, cur_month().split("-"))
    prev = f"{y - (mo == 1)}-{12 if mo == 1 else mo - 1:02d}"
    d = client.get(f"{BASE_URL}/api/finance/summary", params={"month": "2020-01"}).json()
    assert d["received"]["count"] == 0
    assert d["ticket_cents"] == 0
    assert d["conversion_percent"] is None
    assert d["latest"] == [] and d["top_clients"] == []
    assert len(d["daily"]) == 31
    r = client.get(f"{BASE_URL}/api/finance/summary", params={"month": prev})
    assert r.status_code == 200


def test_february_and_december(client):
    d = client.get(f"{BASE_URL}/api/finance/summary", params={"month": "2024-02"}).json()
    assert len(d["daily"]) == 29
    d = client.get(f"{BASE_URL}/api/finance/summary", params={"month": "2025-12"}).json()
    assert len(d["daily"]) == 31
