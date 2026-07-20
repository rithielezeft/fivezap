"""Tests for the WhatsApp delivery queue with automatic 10s retry.

Covers:
- Success on first attempt → status='sent', persisted.
- Failure → status='pending', next_retry_at set to now+10s.
- Retry succeeds after WA comes back → status='sent'.
- Max attempts exceeded → status='failed_permanent' + admin alerted.
- retry_loop_iteration only picks up rows whose next_retry_at has passed.
- send_notification uses the queue.
- send_admin_alert uses the queue (with admin_whatsapp setting).
"""
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "delivery.db")
    import importlib
    import database
    importlib.reload(database)
    from services import delivery_queue, notifier
    importlib.reload(delivery_queue)
    importlib.reload(notifier)
    return database


# ---------- Basic success path ----------

def test_enqueue_sends_immediately_and_marks_sent(tmp_path):
    database = _fresh_env(tmp_path)
    import aiosqlite
    from services import delivery_queue, whatsapp_client

    sent = []

    async def fake_wa(phone, body, image_url=None, **kw):
        sent.append((phone, body))

    async def go():
        await database.init_db()
        with patch.object(whatsapp_client, "send_message", new=fake_wa):
            did = await delivery_queue.enqueue(
                event_key="renewal_success", phone="5511900001111",
                body="Test message", customer_id="cust-1",
            )
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM notification_deliveries WHERE id = ?", (did,)
            )
            return dict(await cur.fetchone())

    row = _run(go())
    assert row["status"] == "sent"
    assert row["attempts"] == 1
    assert row["sent_at"] is not None
    assert row["last_error"] is None
    assert sent == [("5511900001111", "Test message")]


# ---------- Failure → pending → retry ----------

def test_enqueue_failure_marks_pending_and_sets_next_retry(tmp_path):
    database = _fresh_env(tmp_path)
    import aiosqlite
    from services import delivery_queue, whatsapp_client

    async def bad_wa(phone, body, image_url=None, **kw):
        raise RuntimeError("wa-service down")

    async def go():
        await database.init_db()
        with patch.object(whatsapp_client, "send_message", new=bad_wa):
            did = await delivery_queue.enqueue(
                event_key="renewal_success", phone="5511900001111",
                body="Test", customer_id="cust-1",
            )
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM notification_deliveries WHERE id = ?", (did,)
            )
            return dict(await cur.fetchone())

    row = _run(go())
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["sent_at"] is None
    assert "wa-service down" in row["last_error"]
    # next_retry_at set to +10s (roughly)
    assert row["next_retry_at"] is not None
    nra = datetime.fromisoformat(row["next_retry_at"])
    delta = (nra - datetime.now(timezone.utc)).total_seconds()
    assert 8 <= delta <= 12, f"next_retry_at should be ~10s in the future, got {delta}s"


def test_retry_succeeds_when_wa_comes_back(tmp_path):
    """Failed once, then retry_loop_iteration runs and succeeds."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from services import delivery_queue, whatsapp_client

    call_count = [0]

    async def flaky_wa(phone, body, image_url=None, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("first fail")
        # 2nd time: success

    async def go():
        await database.init_db()
        with patch.object(whatsapp_client, "send_message", new=flaky_wa):
            did = await delivery_queue.enqueue(
                event_key="renewal_success", phone="5511900001111",
                body="Test", customer_id="cust-1",
            )
            # Force next_retry_at into the past so retry_loop picks it up
            async with aiosqlite.connect(database.DB_PATH) as db:
                past = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
                await db.execute(
                    "UPDATE notification_deliveries SET next_retry_at = ? WHERE id = ?",
                    (past, did),
                )
                await db.commit()
            count = await delivery_queue.retry_loop_iteration()
            return did, count

    did, count = _run(go())
    assert count == 1

    async def check():
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM notification_deliveries WHERE id = ?", (did,)
            )
            return dict(await cur.fetchone())

    row = _run(check())
    assert row["status"] == "sent"
    assert row["attempts"] == 2  # first failed, second succeeded
    assert call_count[0] == 2


def test_retry_loop_ignores_pending_before_next_retry_at(tmp_path):
    """A delivery with next_retry_at 30s in the future is NOT retried yet."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from services import delivery_queue, whatsapp_client

    call_count = [0]

    async def bad_wa(phone, body, image_url=None, **kw):
        call_count[0] += 1
        raise RuntimeError("still down")

    async def go():
        await database.init_db()
        with patch.object(whatsapp_client, "send_message", new=bad_wa):
            did = await delivery_queue.enqueue(
                event_key="renewal_success", phone="5511900001111",
                body="Test", customer_id="cust-1",
            )
            # Immediate attempt happened (that's call #1). Now next_retry_at
            # is ~10s in the future. Run retry_loop_iteration — should NOT
            # touch this row (skipped by the WHERE next_retry_at <= now).
            count = await delivery_queue.retry_loop_iteration()
            return count

    count = _run(go())
    assert count == 0
    assert call_count[0] == 1  # only the initial attempt happened


# ---------- Max attempts → permanent failure ----------

def test_max_attempts_reached_marks_failed_permanent_and_alerts_admin(tmp_path):
    database = _fresh_env(tmp_path)
    import aiosqlite
    from services import delivery_queue, whatsapp_client

    admin_msgs = []
    async def bad_wa(phone, body, image_url=None, **kw):
        if phone == "5511777777777":  # admin
            admin_msgs.append(body)
            return  # admin alert succeeds (no raise)
        raise RuntimeError("client wa down")

    async def go():
        await database.init_db()
        await database.set_setting("admin_whatsapp", "5511777777777")
        with patch.object(whatsapp_client, "send_message", new=bad_wa):
            did = await delivery_queue.enqueue(
                event_key="renewal_success", phone="5511900001111",
                body="Test", customer_id="cust-1", max_attempts=3,
            )
            # Force retries — burn through remaining attempts
            for _ in range(3):
                async with aiosqlite.connect(database.DB_PATH) as db:
                    past = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
                    await db.execute(
                        "UPDATE notification_deliveries SET next_retry_at = ? WHERE id = ?",
                        (past, did),
                    )
                    await db.commit()
                await delivery_queue.retry_loop_iteration()
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM notification_deliveries WHERE id = ?", (did,)
            )
            return dict(await cur.fetchone())

    row = _run(go())
    assert row["status"] == "failed_permanent"
    assert row["attempts"] == 3
    assert "client wa down" in row["last_error"]
    # Admin was told about it (direct send, not through the queue → 1 msg)
    assert len(admin_msgs) == 1
    assert "Falha permanente" in admin_msgs[0]
    assert "renewal_success" in admin_msgs[0]


# ---------- notifier integration ----------

def test_send_notification_uses_delivery_queue(tmp_path):
    """notifier.send_notification must record deliveries in the queue table."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from services import notifier, whatsapp_client

    async def fake_wa(phone, body, image_url=None, **kw):
        pass

    async def go():
        await database.init_db()
        with patch.object(whatsapp_client, "send_message", new=fake_wa):
            ok = await notifier.send_notification(
                "renewal_success", "5511900001111",
                {"name": "Zé", "plan_months": 1, "new_expires_at": "01/03/2027",
                 "system_type": "iptv"},
                customer_id="cust-1",
            )
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM notification_deliveries WHERE event_key = 'renewal_success'"
            )
            rows = [dict(r) for r in await cur.fetchall()]
        return ok, rows

    ok, rows = _run(go())
    assert ok is True
    assert len(rows) == 1
    assert rows[0]["status"] == "sent"
    assert rows[0]["customer_id"] == "cust-1"
    assert "Zé" in rows[0]["body"]


def test_send_admin_alert_uses_queue_when_configured(tmp_path):
    database = _fresh_env(tmp_path)
    import aiosqlite
    from services import notifier, whatsapp_client

    async def fake_wa(phone, body, image_url=None, **kw):
        pass

    async def go():
        await database.init_db()
        await database.set_setting("admin_whatsapp", "5511777777777")
        with patch.object(whatsapp_client, "send_message", new=fake_wa):
            ok = await notifier.send_admin_alert("💰 pagamento")
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM notification_deliveries WHERE event_key = 'admin_alert'"
            )
            rows = [dict(r) for r in await cur.fetchall()]
        return ok, rows

    ok, rows = _run(go())
    assert ok is True
    assert len(rows) == 1
    assert rows[0]["status"] == "sent"
    assert rows[0]["phone"] == "5511777777777"


def test_send_admin_alert_noop_when_setting_empty(tmp_path):
    database = _fresh_env(tmp_path)
    import aiosqlite
    from services import notifier, whatsapp_client

    sent = []

    async def fake_wa(phone, body, image_url=None, **kw):
        sent.append(phone)

    async def go():
        await database.init_db()
        # No admin_whatsapp
        with patch.object(whatsapp_client, "send_message", new=fake_wa):
            ok = await notifier.send_admin_alert("hi")
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT COUNT(*) as c FROM notification_deliveries"
            )
            return ok, dict(await cur.fetchone())["c"]

    ok, count = _run(go())
    assert ok is False
    assert count == 0
    assert sent == []
