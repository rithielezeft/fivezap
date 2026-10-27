# Unit tests (TEMP DB copy, fake painel users + fake sender): scheduler RUN_STATE/cancel_run_items + delivery cancel during pace wait
import asyncio
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import database  # noqa: E402
from services import delivery_queue as dq  # noqa: E402
from services import whatsapp_client, painel, scheduler  # noqa: E402

REAL_DB = os.path.join(os.path.dirname(__file__), "..", "whatsflow.db")


@pytest.fixture
def tmpdb(monkeypatch):
    d = tempfile.mkdtemp()
    path = os.path.join(d, "copy.db")
    shutil.copy(REAL_DB, path)
    monkeypatch.setattr(database, "DB_PATH", path)
    monkeypatch.setattr(scheduler, "DB_PATH", path)
    wa_calls = []

    async def fake_wa(*a, **k):
        wa_calls.append((a, k))
        return {"success": True}
    monkeypatch.setattr(whatsapp_client, "send_message", fake_wa)
    yield path, wa_calls
    shutil.rmtree(d, ignore_errors=True)


async def _insert_pending(path, did):
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "INSERT INTO notification_deliveries (id,event_key,phone,body,status,attempts,max_attempts,created_at) "
            "VALUES (?,?,?,?,'pending',0,5,?)",
            (did, "TEST_evt", "5511900000009", "TEST body", datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()


async def _st(path, did):
    async with aiosqlite.connect(path) as db:
        cur = await db.execute("SELECT status FROM notification_deliveries WHERE id=?", (did,))
        return (await cur.fetchone())[0]


def test_delivery_cancelled_during_pace_wait_not_sent(tmpdb, monkeypatch):
    path, wa_calls = tmpdb

    async def slow_pace():
        await asyncio.sleep(0.5)
    monkeypatch.setattr(dq, "_wait_for_pace_slot", slow_pace)

    async def run():
        await _insert_pending(path, "TEST_c1")
        t = asyncio.create_task(dq._attempt("TEST_c1"))
        await asyncio.sleep(0.15)
        assert await _st(path, "TEST_c1") == "sending"
        async with aiosqlite.connect(path) as db:  # same SQL as /api/queue/cancel
            await db.execute("UPDATE notification_deliveries SET status='cancelled', next_retry_at=NULL "
                             "WHERE id='TEST_c1' AND status IN ('pending','sending')")
            await db.commit()
        return await t
    assert asyncio.run(run()) is False
    assert wa_calls == []
    assert asyncio.run(_st(path, "TEST_c1")) == "cancelled"


def test_failure_path_does_not_overwrite_cancelled(tmpdb, monkeypatch):
    path, _ = tmpdb

    async def no_pace():
        return None
    monkeypatch.setattr(dq, "_wait_for_pace_slot", no_pace)

    async def failing(*a, **k):
        # admin cancels while the send is in flight, then the send fails
        async with aiosqlite.connect(path) as db:
            await db.execute("UPDATE notification_deliveries SET status='cancelled' WHERE id='TEST_c2'")
            await db.commit()
        raise RuntimeError("WA not ready")
    monkeypatch.setattr(whatsapp_client, "send_message", failing)

    async def run():
        await _insert_pending(path, "TEST_c2")
        r = await dq._attempt("TEST_c2")
        await dq.retry_loop_iteration()
        return r
    assert asyncio.run(run()) is False
    assert asyncio.run(_st(path, "TEST_c2")) == "cancelled"


def _fake_users(n):
    exp = int((datetime.now(timezone.utc) + timedelta(days=3, hours=1)).timestamp())
    return [{"id": f"TESTU{i}", "username": f"testu{i}", "full_name": f"TEST User {i}",
             "whatsapp": f"551190000000{i}", "exp_date": exp, "package_id": 1} for i in range(1, n + 1)]


def _setup_sched(monkeypatch, n):
    sends = []

    async def fake_list(limit=10000):
        return _fake_users(n)
    monkeypatch.setattr(painel, "list_users", fake_list)

    async def fake_send(event_key, phone, ctx, customer_id=None, typing_ms=0, **k):
        sends.append((event_key, phone, customer_id))
        return True
    monkeypatch.setattr(scheduler, "send_notification", fake_send)

    async def prep():
        await database.set_setting("notification_days", "3")
        await database.set_setting("notification_pacing_seconds", "2")
        await database.set_setting("notification_typing_ms", "0")
    asyncio.run(prep())
    return sends


def test_scheduler_cancel_selected_run_item(tmpdb, monkeypatch):
    sends = _setup_sched(monkeypatch, 3)

    async def run():
        t = asyncio.create_task(scheduler._check_and_notify())
        for _ in range(50):
            await asyncio.sleep(0.1)
            if scheduler.RUN_STATE["running"] and scheduler.RUN_STATE["items"]:
                break
        items = scheduler.RUN_STATE["items"]
        assert len(items) == 3, items
        assert all(it["body"] for it in items)
        ids = [it["id"] for it in items]
        n = len(scheduler.cancel_run_items({ids[1]}))
        await t
        return ids, n
    ids, n = asyncio.run(run())
    assert n == 1
    phones = [s[1] for s in sends]
    assert len(sends) == 2 and "5511900000002" not in "".join(phones), sends
    st = {it["id"]: it["status"] for it in scheduler.RUN_STATE["items"]}
    assert st[ids[1]] == "cancelled" and st[ids[0]] == "sent" and st[ids[2]] == "sent"
    assert scheduler.RUN_STATE["running"] is False
    key = [it["key"] for it in scheduler.RUN_STATE["items"] if it["id"] == ids[1]][0]
    assert asyncio.run(database.get_setting(key, "")) == "cancelled"


def test_scheduler_cancel_all_waiting(tmpdb, monkeypatch):
    sends = _setup_sched(monkeypatch, 3)

    async def run():
        t = asyncio.create_task(scheduler._check_and_notify())
        for _ in range(50):
            await asyncio.sleep(0.1)
            if sends:
                break
        t0 = time.monotonic()
        n = len(scheduler.cancel_run_items(None))
        await t
        return n, time.monotonic() - t0
    n, elapsed = asyncio.run(run())
    assert n == 2
    assert len(sends) == 1
    assert elapsed < 2.5  # pacing wait interrupted promptly
