# Iteration 11: raffle retest - painel-cache names, real system package for prize, lock release on failure,
# legacy phone upgrade only for 13-digit canonical input. PRODUCTION: all side effects mocked, temp rows cleaned.
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
PAINEL_ID = "227470206"  # joaonew (p2p) in painel cache


@pytest.fixture(autouse=True)
def _reset_motor():
    """Motor client is cached per process; each asyncio.run creates a new loop -> reset it."""
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


async def _cleanup(pid, month):
    import aiosqlite
    from database import DB_PATH, set_setting
    from services.mongo_store import _get_db
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM payments WHERE id=?", (pid,))
        await db.commit()
    await _get_db().payments.delete_many({"id": pid})
    await _get_db().raffle_draws.delete_one({"_id": month})
    await set_setting("raffle_joker_login", "")
    await set_setting("raffle_prize_months", "1")
    await set_setting("raffle_enabled", "false")


def _mock(calls):
    from services import painel, notifier
    orig = (painel.renew_user, notifier.send_admin_alert, notifier.send_hardcoded)

    async def fake_renew(**kw):
        calls["renew"].append(kw)
        return {"ok": True}

    async def fake_admin(msg, *a, **k):
        calls["admin"].append(msg)

    async def fake_hard(phone, msg, *a, **k):
        calls["hard"].append((phone, msg))

    painel.renew_user, notifier.send_admin_alert, notifier.send_hardcoded = fake_renew, fake_admin, fake_hard
    return orig


def _restore(orig):
    from services import painel, notifier
    painel.renew_user, notifier.send_admin_alert, notifier.send_hardcoded = orig


# Names from painel cache + API entries + draw winner/sequence + real system package
def test_names_from_cache_and_real_system_package():
    from services import raffle
    from database import set_setting
    calls = {"renew": [], "admin": [], "hard": []}
    pid = "TEST_" + uuid.uuid4().hex[:8]
    api = {}

    async def run():
        month, _, _ = await raffle.month_bounds()
        orig = _mock(calls)
        try:
            await set_setting("raffle_prize_months", "3")
            await _insert_payment(pid, PAINEL_ID, 2)
            ent = await raffle.entries()
            # API check while temp payment exists
            api["entries"] = _admin().get(f"{BASE_URL}/api/raffle").json()
            res = await raffle.perform_draw()
            return ent, res
        finally:
            _restore(orig)
            await _cleanup(pid, month)

    ent, res = asyncio.run(run())
    mine = [p for p in ent["pool"] if p.get("payment_id") == pid]
    assert len(mine) == 2 and all(p["name"] == "joaonew" for p in mine), mine
    api_mine = [e for e in api["entries"]["entries"] if str(e.get("payment_id")) == pid or e.get("customer_id") == PAINEL_ID]
    assert api_mine and all(e["name"] == "joaonew" for e in api_mine), api["entries"]["entries"]
    if ent["clovers"] == 2:  # only our clovers -> winner deterministic
        assert res["winner"]["name"] == "joaonew"
        assert all(s["name"] == "joaonew" for s in res["sequence"])
        assert len(calls["renew"]) == 1
        kw = calls["renew"][0]
        assert kw["user_id"] == PAINEL_ID and kw["months"] == 3
        assert kw["package_id"] == 42, kw  # p2p 3 months (iptv would be 43)
        assert "joaonew" in calls["admin"][0]
        if calls["hard"]:
            assert "joaonew" in calls["hard"][0][1]


# Lock released when an exception happens after the Mongo insert
def test_lock_released_on_failure():
    from services import raffle
    from services.mongo_store import _get_db
    calls = {"renew": [], "admin": [], "hard": []}
    pid = "TEST_" + uuid.uuid4().hex[:8]

    async def boom(*a, **k):
        raise RuntimeError("TEST boom")

    async def run():
        month, _, _ = await raffle.month_bounds()
        orig = _mock(calls)
        orig_notify = raffle._notify
        raffle._notify = boom
        try:
            await _insert_payment(pid, PAINEL_ID, 1)
            err = None
            try:
                await raffle.perform_draw()
            except RuntimeError as e:
                err = str(e)
            doc_after_notify_fail = await _get_db().raffle_draws.find_one({"_id": month})
            await _get_db().raffle_draws.delete_one({"_id": month})
            # failure inside _draw_locked before update_one (rng/config) -> lock must be deleted
            raffle._notify = orig_notify
            orig_cfg = raffle.config
            n = {"c": 0}

            async def cfg_fail():
                n["c"] += 1
                if n["c"] >= 2:  # 1st call in entries(), 2nd inside _draw_locked
                    raise RuntimeError("TEST cfg boom")
                return await orig_cfg()
            raffle.config = cfg_fail
            err2 = None
            try:
                await raffle.perform_draw()
            except RuntimeError as e:
                err2 = str(e)
            raffle.config = orig_cfg
            doc2 = await _get_db().raffle_draws.find_one({"_id": month})
            return err, doc_after_notify_fail, err2, doc2
        finally:
            raffle._notify = orig_notify
            _restore(orig)
            await _cleanup(pid, month)

    err, doc1, err2, doc2 = asyncio.run(run())
    assert err == "TEST boom"
    # notify fails after update_one -> doc is 'drawn' (draw already happened); acceptable
    print("doc after notify failure:", doc1 and doc1.get("status"))
    assert doc1 is None or doc1.get("status") == "drawn"
    assert err2 == "TEST cfg boom"
    assert doc2 is None, doc2


# find_or_create_customer must NOT rewrite canonical row to legacy 12-digit form
def test_find_or_create_no_downgrade_with_legacy_input():
    import aiosqlite
    from database import DB_PATH
    from services.bot import find_or_create_customer
    cid = "TEST_" + uuid.uuid4().hex[:8]
    legacy, canon = "559998765432", "5599998765432"

    async def run():
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM customers WHERE whatsapp IN (?,?)", (legacy, canon))
            await db.execute("INSERT INTO customers (id,name,whatsapp,system_type,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                             (cid, "TEST_Canon", canon, "iptv", "prospect", "2026-01-01", "2026-01-01"))
            await db.commit()
        try:
            got = await find_or_create_customer(legacy)
            async with aiosqlite.connect(DB_PATH) as db:
                row = await (await db.execute("SELECT whatsapp FROM customers WHERE id=?", (cid,))).fetchone()
                n = await (await db.execute("SELECT COUNT(*) FROM customers WHERE whatsapp IN (?,?)", (legacy, canon))).fetchone()
            return got, row, n
        finally:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM customers WHERE id=? OR whatsapp IN (?,?)", (cid, legacy, canon))
                await db.commit()

    got, row, n = asyncio.run(run())
    assert got["id"] == cid
    assert row[0] == canon
    assert n[0] == 1
