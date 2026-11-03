# Iteration 12: raffle jokers (Coringa N), public raffle endpoint masking + replay, clover template vars,
# raffle settings persistence, admin payments clovers field. PRODUCTION: side effects mocked, temp rows cleaned.
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_PASSWORD = "Rithi0518@"
PAINEL_ID = "227470206"  # joaonew (p2p)


@pytest.fixture(autouse=True)
def _reset_motor():
    import services.mongo_store as ms
    ms._client, ms._db = None, None
    yield
    ms._client, ms._db = None, None


def _admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200
    tok = r.json().get("token") or r.json().get("access_token")
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    return s


async def _insert_payment(pid, cust, clovers):
    import aiosqlite
    from database import DB_PATH
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO payments (id, customer_id, plan_months, amount_cents, package_id, status, created_at, paid_at, clovers) "
                         "VALUES (?,?,?,?,?,?,?,?,?)", (pid, cust, 1, 3400, 17, "paid", now, now, clovers))
        await db.commit()


async def _cleanup(pids, month=None):
    import aiosqlite
    from database import DB_PATH, set_setting
    from services.mongo_store import _get_db
    async with aiosqlite.connect(DB_PATH) as db:
        for pid in pids:
            await db.execute("DELETE FROM payments WHERE id=?", (pid,))
        await db.commit()
    for pid in pids:
        await _get_db().payments.delete_many({"id": pid})
    if month:
        await _get_db().raffle_draws.delete_one({"_id": month})
    for k, v in (("raffle_joker_login", ""), ("raffle_joker_count", "0"), ("raffle_joker_phone", ""),
                 ("raffle_prize_months", "1"), ("raffle_enabled", "false")):
        await set_setting(k, v)


def _mock(calls):
    from services import painel, notifier
    orig = (painel.renew_user, notifier.send_admin_alert, notifier.send_hardcoded)

    async def fake_renew(**kw):
        calls["renew"].append(kw)
        return {"ok": True}

    async def fake_admin(msg, *a, **k):
        calls["admin"].append(msg)

    async def fake_hard(phone, msg, *a, **k):
        calls["hard"].append((phone, msg, k.get("event_key")))

    painel.renew_user, notifier.send_admin_alert, notifier.send_hardcoded = fake_renew, fake_admin, fake_hard
    return orig


def _restore(orig):
    from services import painel, notifier
    painel.renew_user, notifier.send_admin_alert, notifier.send_hardcoded = orig


# mask_name unit
def test_mask_name():
    from services.raffle import mask_name
    assert mask_name("joaonew") == "joa***"
    assert mask_name("Coringa 2") == "Coringa 2"
    assert mask_name("ab") == "a***"
    assert mask_name("") == "***"


# entries() with joker_count=3: 3 Coringa entries, excluded from counts
def test_entries_with_jokers_and_counts():
    from services import raffle
    from database import set_setting
    pid = "TEST_" + uuid.uuid4().hex[:8]

    async def run():
        try:
            base = await raffle.entries()
            await set_setting("raffle_joker_count", "3")
            await _insert_payment(pid, PAINEL_ID, 2)
            ent = await raffle.entries()
            return base, ent
        finally:
            await _cleanup([pid])

    base, ent = asyncio.run(run())
    jokers = [p for p in ent["pool"] if p.get("joker")]
    assert [j["name"] for j in jokers] == ["Coringa 1", "Coringa 2", "Coringa 3"]
    assert len({j["coupon"] for j in jokers}) == 3
    assert ent["clovers"] == base["clovers"] + 2
    assert ent["participants"] >= 1 and ent["participants"] == len({p["customer_id"] for p in ent["pool"] if not p.get("joker")})
    assert len(ent["pool"]) == ent["clovers"] + 3


# Joker wins with empty joker_login -> no renewal, joker_phone notified
def test_joker_win_no_login_notifies_joker_phone():
    from services import raffle
    from database import set_setting
    calls = {"renew": [], "admin": [], "hard": []}
    pid = "TEST_" + uuid.uuid4().hex[:8]

    async def run():
        month, _, _ = await raffle.month_bounds()
        orig = _mock(calls)
        orig_choice = raffle.secrets.SystemRandom.choice
        try:
            await set_setting("raffle_joker_count", "3")
            await set_setting("raffle_joker_phone", "5511999990000")
            await set_setting("raffle_joker_login", "")
            await _insert_payment(pid, PAINEL_ID, 1)
            # Force a joker to win
            raffle.secrets.SystemRandom.choice = lambda self, seq: [p for p in seq if p.get("joker")][1]
            res = await raffle.perform_draw()
            pub = requests.get(f"{BASE_URL}/api/public/raffle").json()
            return res, pub
        finally:
            raffle.secrets.SystemRandom.choice = orig_choice
            _restore(orig)
            await _cleanup([pid], month)

    res, pub = asyncio.run(run())
    assert res["winner"]["name"] == "Coringa 2" and res["winner"].get("joker")
    assert res["renewed"] is False and "coringa" in res["renew_error"].lower()
    assert calls["renew"] == []
    assert any(h[0] == "5511999990000" and h[2] == "raffle_winner_joker" for h in calls["hard"]), calls["hard"]
    assert calls["admin"] and "CORINGA" in calls["admin"][0]
    assert res["sequence"][res["win_index"]]["name"] == "Coringa 2"
    # public endpoint during draw doc existence: history has masked replay
    assert pub["history"], pub
    h = pub["history"][0]
    assert h["winner"]["name"] == "Coringa 2"
    assert len(h["sequence"]) == 60 and h["win_index"] == 52
    assert all(x["name"].endswith("***") or x["name"].startswith("Coringa ") for x in h["sequence"])


# Public raffle endpoint without auth + masking with a temp payment
def test_public_raffle_no_auth_masking():
    from database import set_setting
    pid = "TEST_" + uuid.uuid4().hex[:8]

    async def run():
        try:
            await set_setting("raffle_joker_count", "2")
            await _insert_payment(pid, PAINEL_ID, 1)
            return requests.get(f"{BASE_URL}/api/public/raffle")
        finally:
            await _cleanup([pid])

    r = asyncio.run(run())
    assert r.status_code == 200
    d = r.json()
    for k in ("enabled", "participants", "draw_at", "month", "entries", "history", "clovers"):
        assert k in d
    names = [e["name"] for e in d["entries"]]
    assert "joa***" in names
    assert "joaonew" not in names
    assert [e["name"] for e in d["entries"] if e["joker"]] == ["Coringa 1", "Coringa 2"]


# Raffle settings persist via API (joker_count clamp, phone digits)
def test_raffle_settings_persist():
    s = _admin()
    try:
        r = s.put(f"{BASE_URL}/api/raffle/settings", json={"joker_count": 99, "joker_phone": "+55 (11) 98888-7777"})
        assert r.status_code == 200
        assert r.json()["joker_count"] == 50
        assert r.json()["joker_phone"] == "5511988887777"
        g = s.get(f"{BASE_URL}/api/raffle").json()["config"]
        assert g["joker_count"] == 50 and g["joker_phone"] == "5511988887777"
    finally:
        r = s.put(f"{BASE_URL}/api/raffle/settings", json={"joker_count": 0, "joker_phone": "", "joker_login": "", "enabled": False})
        assert r.json()["joker_count"] == 0 and r.json()["joker_phone"] == "" and r.json()["enabled"] is False


# _clover_vars returns quantity + coupon numbers
def test_clover_vars():
    from routers.payments import _clover_vars
    from services import raffle
    pid = "TEST_" + uuid.uuid4().hex[:8]

    async def run():
        try:
            await _insert_payment(pid, PAINEL_ID, 2)
            ent = await raffle.entries()
            exp = [p["coupon"] for p in ent["pool"] if p.get("payment_id") == pid]
            return await _clover_vars({"id": pid, "clovers": 2}), exp, await _clover_vars({"id": "x", "clovers": 0})
        finally:
            await _cleanup([pid])

    v, exp, zero = asyncio.run(run())
    assert v["clovers"] == 2
    assert v["clover_coupons"] == ", ".join(f"#{c}" for c in exp) and len(exp) == 2
    print("clover_vars:", v, "zero:", zero)
    assert zero["clovers"] == 0


# Admin payments list exposes clovers
def test_admin_payments_have_clovers_field():
    s = _admin()
    r = s.get(f"{BASE_URL}/api/payments")
    assert r.status_code == 200
    d = r.json()
    rows = d if isinstance(d, list) else (d.get("payments") or d.get("items") or [])
    if rows:
        assert "clovers" in rows[0], rows[0].keys()
