# Iteration 17: LIVE (preview) raffle API checks - read-only + manual entry add/delete (cleaned) + settings toggle (restored).
# NEVER calls /api/raffle/draw.
import os

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


@pytest.fixture(scope="module")
def s():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": "Rithi0518@"})
    assert r.status_code == 200
    tok = r.json().get("token") or r.json().get("access_token")
    s.headers["Authorization"] = f"Bearer {tok}"
    return s


# overview shape
def test_overview(s):
    d = s.get(f"{BASE_URL}/api/raffle").json()
    for k in ("round_id", "open", "start", "draw_at", "entries", "config", "history"):
        assert k in d
    assert d["open"] is True
    assert "auto_restart" in d["config"] and "auto_renew" in d["config"]
    assert all("manual_entries" in e for e in d["entries"])
    print(d["round_id"], d["start"], d["draw_at"], d["participants"], d["clovers"], d["config"])


# public endpoint + history label
def test_public():
    r = requests.get(f"{BASE_URL}/api/public/raffle")
    assert r.status_code == 200
    d = r.json()
    assert d["open"] is True and "entries" in d
    print([h["round_id"] for h in d["history"]])


# new-round while open -> 400
def test_new_round_open_400(s):
    r = s.post(f"{BASE_URL}/api/raffle/new-round")
    assert r.status_code == 400 and r.json()["detail"] == "Já existe um sorteio em andamento"


# unknown customer -> 400; empty -> 400
def test_add_unknown(s):
    r = s.post(f"{BASE_URL}/api/raffle/entries", json={"customer": "zz_nobody_xyz", "clovers": 1})
    assert r.status_code == 400 and r.json()["detail"] == "Cliente não encontrado no painel"
    r = s.post(f"{BASE_URL}/api/raffle/entries", json={"customer": "", "clovers": 1})
    assert r.status_code == 400


# add andrecartv -> appears in admin + public -> delete -> gone
def test_add_and_remove_manual(s):
    before = s.get(f"{BASE_URL}/api/raffle").json()
    pub_before = requests.get(f"{BASE_URL}/api/public/raffle").json()
    r = s.post(f"{BASE_URL}/api/raffle/entries", json={"customer": "andrecartv", "clovers": 2})
    assert r.status_code == 200, r.text
    eid = r.json()["entry"]["_id"]
    try:
        assert r.json()["entry"]["clovers"] == 2 and r.json()["entry"]["round_id"] == before["round_id"]
        after = s.get(f"{BASE_URL}/api/raffle").json()
        assert after["clovers"] == before["clovers"] + 2
        ents = [e for e in after["entries"] if any(m["id"] == eid for m in e["manual_entries"])]
        assert len(ents) == 1 and [m for m in ents[0]["manual_entries"] if m["id"] == eid][0]["clovers"] == 2
        pub = requests.get(f"{BASE_URL}/api/public/raffle").json()
        assert len(pub["entries"]) == len(pub_before["entries"]) + 2
    finally:
        d = s.delete(f"{BASE_URL}/api/raffle/entries/{eid}")
        assert d.status_code == 200
    assert s.get(f"{BASE_URL}/api/raffle").json()["clovers"] == before["clovers"]
    assert s.delete(f"{BASE_URL}/api/raffle/entries/{eid}").status_code == 404


# settings toggles persist then restore
def test_settings_toggle(s):
    orig = s.get(f"{BASE_URL}/api/raffle").json()["config"]
    try:
        r = s.put(f"{BASE_URL}/api/raffle/settings", json={"auto_restart": False, "auto_renew": False})
        assert r.status_code == 200 and r.json()["auto_restart"] is False and r.json()["auto_renew"] is False
        g = s.get(f"{BASE_URL}/api/raffle").json()["config"]
        assert g["auto_restart"] is False and g["auto_renew"] is False
    finally:
        r = s.put(f"{BASE_URL}/api/raffle/settings", json={"enabled": orig["enabled"], "auto_restart": True, "auto_renew": True})
        assert r.json()["auto_restart"] is True and r.json()["auto_renew"] is True
