# Raffle participant rename (iter13): PUT /api/raffle/participant-name, admin/public propagation, joker protection
# Requires: python tests/temp_clover_payment.py add (customer 227470206 with 3 clovers) beforehand
import asyncio
import os
import sys

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
CID = "227470206"
NEW = "TEST_Renomeado"


@pytest.fixture(scope="module")
def s():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "Rithi0518@"})
    if r.status_code != 200:
        pytest.skip("login failed")
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {r.json().get('token') or r.json().get('access_token')}"})
    sess.put(f"{BASE_URL}/api/raffle/settings", json={"joker_count": 2})
    yield sess
    sess.put(f"{BASE_URL}/api/raffle/participant-name", json={"customer_id": CID, "name": ""})


def _entry(sess, cid):
    d = sess.get(f"{BASE_URL}/api/raffle").json()
    return next((e for e in d["entries"] if e["customer_id"] == cid), None), d


def test_baseline_entry_present(s):
    e, d = _entry(s, CID)
    assert e is not None and not e["joker"] and len(e["coupons"]) == 3
    jokers = [x for x in d["entries"] if x["joker"]]
    assert [j["name"] for j in jokers] == ["Coringa 1", "Coringa 2"]


def test_rename_updates_admin_and_public(s):
    r = s.put(f"{BASE_URL}/api/raffle/participant-name", json={"customer_id": CID, "name": f"  {NEW}  "})
    assert r.status_code == 200 and r.json()["ok"] is True
    e, _ = _entry(s, CID)
    assert e["name"] == NEW
    pub = requests.get(f"{BASE_URL}/api/public/raffle").json()
    real = [p for p in pub["entries"] if not p["joker"]]
    assert len(real) == 3 and all(p["name"] == NEW[:3] + "***" for p in real)
    assert [p["name"] for p in pub["entries"] if p["joker"]] == ["Coringa 1", "Coringa 2"]


def test_entries_pool_uses_display_name(s):
    sys.path.insert(0, "/app/backend")
    load_dotenv("/app/backend/.env")
    from services import raffle
    pool = asyncio.run(raffle.entries())["pool"]
    assert all(p["name"] == NEW for p in pool if p["customer_id"] == CID)


def test_rename_too_long_truncated(s):
    r = s.put(f"{BASE_URL}/api/raffle/participant-name", json={"customer_id": CID, "name": "X" * 60})
    assert r.status_code == 200
    assert _entry(s, CID)[0]["name"] == "X" * 40


def test_empty_name_resets(s):
    r = s.put(f"{BASE_URL}/api/raffle/participant-name", json={"customer_id": CID, "name": ""})
    assert r.status_code == 200
    e, _ = _entry(s, CID)
    assert e["name"] not in (NEW, "X" * 40) and e["name"]


@pytest.mark.parametrize("cid", ["coringa-1", "coringa-2", "999999999", ""])
def test_rename_invalid_ids_400(s, cid):
    r = s.put(f"{BASE_URL}/api/raffle/participant-name", json={"customer_id": cid, "name": "Hack"})
    assert r.status_code == 400
    assert "renomear" in r.json()["detail"]


def test_rename_requires_auth():
    r = requests.put(f"{BASE_URL}/api/raffle/participant-name", json={"customer_id": CID, "name": "Hack"})
    assert r.status_code == 401
