# Unit tests (temp DB copy, fake WA sender): atomic 'sending' claim prevents duplicate sends
import asyncio
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import database  # noqa: E402
from services import delivery_queue as dq  # noqa: E402
from services import whatsapp_client  # noqa: E402

REAL_DB = os.path.join(os.path.dirname(__file__), "..", "whatsflow.db")


@pytest.fixture
def tmpdb(monkeypatch):
    d = tempfile.mkdtemp()
    path = os.path.join(d, "copy.db")
    shutil.copy(REAL_DB, path)
    monkeypatch.setattr(database, "DB_PATH", path)
    calls = []

    async def fake_send(phone, body, image_url=None, typing_ms=0, idempotency_key=None):
        calls.append((phone, body, idempotency_key))
        await asyncio.sleep(0.5)
        return {"success": True}

    monkeypatch.setattr(whatsapp_client, "send_message", fake_send)

    async def no_pace():
        return None
    monkeypatch.setattr(dq, "_wait_for_pace_slot", no_pace)
    yield path, calls
    shutil.rmtree(d, ignore_errors=True)


async def _status(path, did):
    async with aiosqlite.connect(path) as db:
        cur = await db.execute("SELECT status, attempts FROM notification_deliveries WHERE id=?", (did,))
        return await cur.fetchone()


def test_enqueue_concurrent_attempt_and_retry_single_send(tmpdb):
    path, calls = tmpdb

    async def run():
        t = asyncio.create_task(dq.enqueue("TEST_evt", "5511900000001", "TEST body unique 1", force=True))
        await asyncio.sleep(0.1)  # enqueue is inside fake send now
        async with aiosqlite.connect(path) as db:
            cur = await db.execute("SELECT id FROM notification_deliveries WHERE event_key='TEST_evt'")
            did = (await cur.fetchone())[0]
        # concurrent duplicates while in flight
        r = await asyncio.gather(dq._attempt(did), dq._attempt(did), dq.retry_loop_iteration())
        await t
        # after completion — retry loop and attempt again
        await dq.retry_loop_iteration()
        again = await dq._attempt(did)
        return did, r, again

    did, r, again = asyncio.run(run())
    assert len(calls) == 1, calls
    assert calls[0][2] == did  # idempotency key = delivery id
    st = asyncio.run(_status(path, did))
    assert st[0] == "sent" and st[1] == 1
    assert r[0] is False and r[1] is False
    assert again is True


def test_many_concurrent_attempts_on_pending_row(tmpdb):
    path, calls = tmpdb

    async def run():
        did = "TEST_row_concurrent"
        async with aiosqlite.connect(path) as db:
            await db.execute(
                "INSERT INTO notification_deliveries (id, event_key, phone, body, status, attempts, max_attempts, "
                "next_retry_at, created_at) VALUES (?, 'TEST_evt2', '5511900000002', 'b', 'pending', 0, 5, NULL, ?)",
                (did, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()
        await asyncio.gather(*[dq._attempt(did) for _ in range(5)], dq.retry_loop_iteration())
        return did

    did = asyncio.run(run())
    assert len([c for c in calls if c[2] == did]) == 1
    assert asyncio.run(_status(path, did))[0] == "sent"


def test_stale_sending_released_to_pending(tmpdb):
    path, calls = tmpdb

    async def run():
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(seconds=200)).isoformat()
        async with aiosqlite.connect(path) as db:
            for did, nra in (("TEST_stale", past), ("TEST_fresh", future)):
                await db.execute(
                    "INSERT INTO notification_deliveries (id, event_key, phone, body, status, attempts, max_attempts, "
                    "next_retry_at, created_at) VALUES (?, 'TEST_evt3', '5511900000003', ?, 'sending', 0, 5, ?, ?)",
                    (did, did, nra, past),
                )
            await db.commit()
        await dq.retry_loop_iteration()

    asyncio.run(run())
    assert asyncio.run(_status(path, "TEST_stale"))[0] == "sent"
    assert asyncio.run(_status(path, "TEST_fresh"))[0] == "sending"
    assert [c[2] for c in calls] == ["TEST_stale"]


def test_real_db_untouched():
    # sanity: no TEST_ rows ever reached the real DB
    async def q():
        async with aiosqlite.connect(REAL_DB) as db:
            cur = await db.execute("SELECT COUNT(*) FROM notification_deliveries WHERE id LIKE 'TEST_%' OR event_key LIKE 'TEST_%'")
            return (await cur.fetchone())[0]
    assert asyncio.run(q()) == 0
