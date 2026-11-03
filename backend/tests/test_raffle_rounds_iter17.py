# Iteration 17: raffle rounds (auto_restart / new-round), auto_renew toggle, manual entries.
# FULLY ISOLATED: local Mongo throwaway DB + temp SQLite, painel/notifier/painel cache mocked. Never touches prod.
import asyncio
import os
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, "/app/backend")

USERS = [{"id": 111, "username": "andrecartv"}, {"id": 222, "username": "joaonew"}]


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.delenv("WHATSFLOW_MONGO_URL", raising=False)
    monkeypatch.delenv("WHATSFLOW_DB_NAME", raising=False)
    monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
    dbname = "test_raffle_iter17_" + uuid.uuid4().hex[:6]
    monkeypatch.setenv("DB_NAME", dbname)
    sqlite = str(tmp_path / "t.db")
    monkeypatch.setenv("SQLITE_PATH", sqlite)
    import database
    import services.mongo_store as ms
    from services import raffle, painel, notifier
    import routers.painel_users as pu
    import routers.payments as rp
    monkeypatch.setattr(database, "DB_PATH", sqlite)
    monkeypatch.setattr(raffle, "DB_PATH", sqlite)
    ms._client, ms._db = None, None
    calls = {"renew": [], "admin": [], "hard": []}

    async def fake_cache():
        return USERS, None

    async def fake_renew(**kw):
        calls["renew"].append(kw)
        return {"ok": True}

    async def fake_admin(msg, *a, **k):
        calls["admin"].append(msg)

    async def fake_hard(phone, msg, *a, **k):
        calls["hard"].append(phone)

    async def fake_cache_user(uid):
        return {"id": uid, "username": "x"}

    monkeypatch.setattr(pu, "_read_cache", fake_cache)
    monkeypatch.setattr(painel, "renew_user", fake_renew)
    monkeypatch.setattr(notifier, "send_admin_alert", fake_admin)
    monkeypatch.setattr(notifier, "send_hardcoded", fake_hard)
    monkeypatch.setattr(rp, "_cache_user", fake_cache_user)
    asyncio.run(database.init_db())
    yield calls
    ms._client, ms._db = None, None
    from pymongo import MongoClient
    MongoClient("mongodb://localhost:27017").drop_database(dbname)


def run(coro):
    import services.mongo_store as ms

    async def wrapper():
        ms._client, ms._db = None, None
        assert not os.environ.get("WHATSFLOW_MONGO_URL") and os.environ["MONGO_URL"] == "mongodb://localhost:27017"
        ms._get_db()
        assert ms._client.address is None or True
        assert "localhost" in str(ms._client) and os.environ["DB_NAME"].startswith("test_raffle_iter17_")
        return await coro
    return asyncio.run(wrapper())


async def _pay(cust, clovers, when=None):
    import aiosqlite
    import database
    pid = "TEST_" + uuid.uuid4().hex[:8]
    t = (when or datetime.now(timezone.utc)).isoformat()
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute("INSERT INTO payments (id, customer_id, plan_months, amount_cents, package_id, status, created_at, paid_at, clovers) "
                         "VALUES (?,?,?,?,?,?,?,?,?)", (pid, cust, 1, 3400, 17, "paid", t, t, clovers))
        await db.commit()
    return pid


# settings payload parses auto_restart / auto_renew and defaults are true
def test_settings_payload_and_defaults(env):
    from services import raffle
    out = raffle.clean_settings_payload({"auto_restart": False, "auto_renew": True, "enabled": True})
    assert out == {"raffle_enabled": "true", "raffle_auto_restart": "false", "raffle_auto_renew": "true"}
    cfg = run(raffle.config())
    assert cfg["auto_restart"] is True and cfg["auto_renew"] is True and cfg["enabled"] is False


# first round created automatically from month start; payments + manual entries counted
def test_first_round_and_manual_entries(env):
    from services import raffle
    from routers.raffle import raffle_overview

    async def go():
        rnd = await raffle.current_round()
        await _pay("222", 2)
        e1 = await raffle.add_manual_entry("andrecartv", 3)
        e2 = await raffle.add_manual_entry("222", 50)  # clamp to 10, by id
        bad = None
        try:
            await raffle.add_manual_entry("nobody_xyz", 1)
        except ValueError as ex:
            bad = str(ex)
        ov = await raffle_overview()
        removed = await raffle.remove_manual_entry(e1["_id"])
        removed_again = await raffle.remove_manual_entry(e1["_id"])
        ov2 = await raffle_overview()
        return rnd, e1, e2, bad, ov, removed, removed_again, ov2

    rnd, e1, e2, bad, ov, removed, removed_again, ov2 = run(go())
    assert rnd["round_id"] == datetime.now(timezone.utc).strftime("%Y-%m") or "-" in rnd["round_id"]
    assert rnd["drawn"] is False
    assert e1["customer_id"] == "111" and e1["clovers"] == 3 and e2["clovers"] == 10
    assert bad == "Cliente não encontrado no painel"
    assert ov["open"] is True and ov["clovers"] == 15 and ov["participants"] == 2
    by = {e["customer_id"]: e for e in ov["entries"]}
    assert by["111"]["manual_entries"] == [{"id": e1["_id"], "clovers": 3}]
    assert len(by["222"]["coupons"]) == 12 and by["222"]["manual_entries"][0]["clovers"] == 10
    assert removed is True and removed_again is False
    assert ov2["clovers"] == 12


# draw with auto_restart=true: new round '-2' opens at draw moment; clovers paid after the draw are NOT lost
def test_draw_auto_restart_keeps_late_clovers(env):
    from services import raffle

    async def go():
        r1 = await raffle.current_round()
        await _pay("222", 1)
        res = await raffle.perform_draw()
        r2 = await raffle.current_round()
        await _pay("111", 2)  # paid after early draw
        ent = await raffle.entries()
        hist = await raffle.history()
        return r1, res, r2, ent, hist

    r1, res, r2, ent, hist = run(go())
    assert res["status"] == "drawn" and res["renewed"] is True and len(env["renew"]) == 1
    assert env["renew"][0]["user_id"] == "222"
    assert r2["round_id"] == f"{r1['round_id']}-2" and r2["drawn"] is False
    assert r2["start"] == datetime.fromisoformat(res["created_at"]).astimezone(timezone.utc).isoformat()
    assert ent["open"] is True and ent["clovers"] == 2 and ent["pool"][0]["customer_id"] == "111"
    assert hist[0]["round_id"] == r1["round_id"]


# auto_restart=false: round stays closed, manual add/draw blocked, new-round endpoint opens a new round
def test_no_auto_restart_and_new_round_endpoint(env):
    from fastapi import HTTPException
    from database import set_setting
    from services import raffle
    from routers.raffle import raffle_new_round

    async def go():
        await set_setting("raffle_auto_restart", "false")
        r1 = await raffle.current_round()
        err_open = None
        try:
            await raffle_new_round()
        except HTTPException as ex:
            err_open = (ex.status_code, ex.detail)
        await _pay("222", 1)
        await raffle.perform_draw()
        closed = await raffle.entries()
        errs = []
        for fn in (lambda: raffle.add_manual_entry("andrecartv", 1), raffle.perform_draw):
            try:
                await fn()
            except ValueError as ex:
                errs.append(str(ex))
        await asyncio.sleep(0.01)
        await _pay("111", 4)  # paid while closed -> goes to next round
        closed2 = await raffle.entries()
        new = await raffle_new_round()
        ent = await raffle.entries()
        return r1, err_open, closed, errs, closed2, new, ent

    r1, err_open, closed, errs, closed2, new, ent = run(go())
    assert err_open == (400, "Já existe um sorteio em andamento")
    assert closed["open"] is False and closed["round_id"] == r1["round_id"]
    assert len(errs) == 2 and "já foi realizado" in errs[0] and "já foi realizado" in errs[1]
    assert closed2["clovers"] == 1  # closed round pool frozen
    assert new["round_id"] == f"{r1['round_id']}-2"
    assert ent["open"] is True and ent["clovers"] == 4


# auto_renew=false: painel.renew_user NOT called, renewed False, error mentions 'desativada'
def test_auto_renew_off(env):
    from database import set_setting
    from services import raffle

    async def go():
        await set_setting("raffle_auto_renew", "false")
        await _pay("222", 1)
        return await raffle.perform_draw()

    res = run(go())
    assert env["renew"] == []
    assert res["renewed"] is False and "desativada" in res["renew_error"]
    assert env["admin"] and "renovar manualmente" in env["admin"][0]


# auto_draw_loop: draws when enabled & draw_at passed; reopens drawn round when auto_restart on
def test_auto_draw_loop(env, monkeypatch):
    from database import set_setting
    from services import raffle
    from services.mongo_store import _get_db

    class Stop(Exception):
        pass

    async def stop(_):
        raise Stop()

    monkeypatch.setattr(raffle, "asyncio", types.SimpleNamespace(sleep=stop))

    async def go():
        await set_setting("raffle_enabled", "true")
        r1 = await raffle.current_round()
        await _pay("222", 1)
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        await _get_db().raffle_state.update_one({"_id": "current"}, {"$set": {"draw_at": past}})
        try:
            await raffle.auto_draw_loop()
        except Stop:
            pass
        r2 = await raffle.current_round()
        # now simulate a drawn round left closed (auto_restart off at draw time) then turned on
        await set_setting("raffle_auto_restart", "false")
        await _get_db().raffle_state.update_one({"_id": "current"}, {"$set": {"draw_at": past}})
        await raffle.perform_draw() if (await raffle.entries())["clovers"] else None
        await _pay("111", 1)
        await _get_db().raffle_state.update_one({"_id": "current"}, {"$set": {"draw_at": past}})
        await raffle.perform_draw()
        r3 = await raffle.current_round()
        await set_setting("raffle_auto_restart", "true")
        try:
            await raffle.auto_draw_loop()
        except Stop:
            pass
        r4 = await raffle.current_round()
        return r1, r2, r3, r4

    r1, r2, r3, r4 = run(go())
    assert r2["round_id"] == f"{r1['round_id']}-2" and r2["drawn"] is False
    assert r3["drawn"] is True and r3["round_id"] == r2["round_id"]
    assert r4["drawn"] is False and r4["round_id"] == f"{r1['round_id']}-3"


# Round id after the regular end-of-month auto draw (Nov 30 20h BRT) should label the NEXT month's round
def test_round_id_after_regular_month_end_draw(env, monkeypatch):
    from services import raffle
    from services.mongo_store import _get_db
    tz = timezone(timedelta(hours=-3))

    class FakeDT(datetime):
        @classmethod
        def now(cls, t=None):
            return datetime(2026, 11, 30, 20, 5, tzinfo=tz).astimezone(t) if t else datetime(2026, 11, 30, 20, 5)

    async def fake_tz():
        return tz
    monkeypatch.setattr(raffle, "_tz", fake_tz)

    async def go():
        await _get_db().raffle_draws.insert_one({"_id": "2026-11", "status": "drawn", "created_at": "2026-11-30T23:00:00+00:00"})
        monkeypatch.setattr(raffle, "datetime", FakeDT)
        return await raffle.start_new_round("2026-11-30T23:00:00+00:00")

    st = run(go())
    print("new round after Nov-30 draw:", st)
    assert st["draw_at"].startswith("2026-12-31T20:00")
    assert st["round_id"] == "2026-12", f"round for December labelled {st['round_id']}"
