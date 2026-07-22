"""Bug fix: prevent duplicate WhatsApp messages when the queue is called
twice for the same (event_key, phone) within a short window.

Covers:
- delivery_queue.enqueue with default dedup_window_minutes=60
- notify_expired two-step flow: first call returns needs_confirmation for
  duplicates; second call with force=True bypasses dedup.
- send_hardcoded skips dedup (admin alerts must always fire).
"""
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "dedup.db")
    import importlib
    import database as _db
    importlib.reload(_db)
    from services import delivery_queue, notifier
    importlib.reload(delivery_queue)
    importlib.reload(notifier)
    from routers import painel_users
    importlib.reload(painel_users)
    _run(_db.init_db())
    return _db


# ---------- delivery_queue.enqueue ----------

def test_enqueue_dedup_reuses_recent_delivery(tmp_path):
    """Two enqueue calls for same (phone, event) within window return the
    SAME delivery id — the second call is a no-op."""
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client

    async def go():
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            first = await delivery_queue.enqueue(
                "manual_expired_alert", "5511987654321", "hello",
            )
            second = await delivery_queue.enqueue(
                "manual_expired_alert", "5511987654321", "hello again",
            )
        return first, second

    a, b = _run(go())
    assert a == b, f"Second enqueue must return existing id, got {a} vs {b}"


def test_enqueue_dedup_bypassed_with_force(tmp_path):
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client

    async def go():
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            first = await delivery_queue.enqueue(
                "manual_expired_alert", "5511987654321", "hello",
            )
            second = await delivery_queue.enqueue(
                "manual_expired_alert", "5511987654321", "hello resent",
                force=True,
            )
        return first, second

    a, b = _run(go())
    assert a != b, "force=True must create a new delivery row"


def test_enqueue_dedup_disabled_when_window_zero(tmp_path):
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client

    async def go():
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            first = await delivery_queue.enqueue(
                "admin_alert", "5511987654321", "payment 1",
                dedup_window_minutes=0,
            )
            second = await delivery_queue.enqueue(
                "admin_alert", "5511987654321", "payment 2",
                dedup_window_minutes=0,
            )
        return first, second

    a, b = _run(go())
    assert a != b, "dedup_window_minutes=0 must always create a new row"


def test_dedup_scoped_per_event_key(tmp_path):
    """Same phone + DIFFERENT event_key → no dedup collision."""
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client

    async def go():
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            a = await delivery_queue.enqueue(
                "expired_1d", "5511987654321", "expired 1d",
            )
            b = await delivery_queue.enqueue(
                "renewal_success", "5511987654321", "renewal",
            )
        return a, b

    a, b = _run(go())
    assert a != b


def test_dedup_scoped_per_phone(tmp_path):
    """Same event_key + DIFFERENT phone → each gets its own delivery row."""
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client

    async def go():
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            a = await delivery_queue.enqueue(
                "manual_expired_alert", "5511111111111", "hi 1",
            )
            b = await delivery_queue.enqueue(
                "manual_expired_alert", "5522222222222", "hi 2",
            )
        return a, b

    a, b = _run(go())
    assert a != b


def test_dedup_expires_after_window(tmp_path):
    """A send older than the window is not considered a duplicate."""
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client
    import aiosqlite
    import database

    async def go():
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            first = await delivery_queue.enqueue(
                "manual_expired_alert", "5511999998888", "old",
            )
            # Backdate the delivery to 2h ago (outside the 60min window).
            two_hours_ago = (
                datetime.now(timezone.utc) - timedelta(hours=2)
            ).isoformat()
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute(
                    "UPDATE notification_deliveries "
                    "SET sent_at = ?, created_at = ? WHERE id = ?",
                    (two_hours_ago, two_hours_ago, first),
                )
                await db.commit()
            second = await delivery_queue.enqueue(
                "manual_expired_alert", "5511999998888", "new",
            )
        return first, second

    a, b = _run(go())
    assert a != b, "Send older than 60min should not dedup"


# ---------- notify_expired two-step confirmation ----------

def _seed_expired(uid, wa, days_offset=-5, name=None):
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    exp = _dt.now(_tz.utc) + _td(days=days_offset)
    return {
        "id": uid,
        "username": f"user{uid}",
        "full_name": name or f"Cliente {uid}",
        "as_number": wa,
        "exp_date": int(exp.timestamp()),
        "enabled": 1,
        "system": 1,
    }


def test_notify_expired_second_call_returns_confirmation(tmp_path):
    _fresh_env(tmp_path)
    from routers import painel_users
    from services import whatsapp_client

    async def go():
        await painel_users._write_cache([
            _seed_expired(50, "5511900000050", -3, "A"),
            _seed_expired(51, "5511900000051", -3, "B"),
        ])
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            # First call: fires everything
            r1 = await painel_users.notify_expired(
                painel_users.NotifyExpiredPayload(user_ids=[])
            )
            # Second call: same target set → all should be duplicates.
            r2 = await painel_users.notify_expired(
                painel_users.NotifyExpiredPayload(user_ids=[])
            )
        return r1, r2

    r1, r2 = _run(go())
    assert r1["enqueued"] == 2
    assert r2.get("needs_confirmation") is True
    assert r2.get("duplicate_count") == 2
    assert r2.get("fresh_count") == 0
    # No duplicates were actually enqueued in the second call.
    assert "enqueued" not in r2 or r2.get("enqueued") == 0


def test_notify_expired_force_resends(tmp_path):
    _fresh_env(tmp_path)
    from routers import painel_users
    from services import whatsapp_client
    import aiosqlite
    import database

    async def count_deliveries():
        async with aiosqlite.connect(database.DB_PATH) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM notification_deliveries "
                "WHERE event_key = 'manual_expired_alert' "
                "  AND phone = '5511900000060'"
            )
            row = await cur.fetchone()
            return row[0]

    async def go():
        await painel_users._write_cache([
            _seed_expired(60, "5511900000060", -3, "A"),
        ])
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            r1 = await painel_users.notify_expired(
                painel_users.NotifyExpiredPayload(user_ids=[])
            )
            count_after_first = await count_deliveries()
            # Force resend
            r2 = await painel_users.notify_expired(
                painel_users.NotifyExpiredPayload(user_ids=["60"], force=True)
            )
            count_after_force = await count_deliveries()
        return r1, r2, count_after_first, count_after_force

    r1, r2, c1, c2 = _run(go())
    assert r1["enqueued"] == 1
    assert r2["enqueued"] == 1
    assert r2["resent"] == 1, "resent counter must reflect the bypass"
    assert c1 == 1
    assert c2 == 2, "force=True must create a NEW delivery row (dedup bypassed)"


def test_notify_expired_partial_duplicates(tmp_path):
    """One duplicate + one fresh in same wave → confirmation shows counts
    correctly; sending only the fresh id works."""
    _fresh_env(tmp_path)
    from routers import painel_users
    from services import whatsapp_client

    async def go():
        await painel_users._write_cache([
            _seed_expired(70, "5511900000070", -3, "A"),
            _seed_expired(71, "5511900000071", -3, "B"),
        ])
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            # Only send to 70 first.
            r1 = await painel_users.notify_expired(
                painel_users.NotifyExpiredPayload(user_ids=["70"])
            )
            # Then try to send to both — 70 is duplicate, 71 is fresh.
            r2 = await painel_users.notify_expired(
                painel_users.NotifyExpiredPayload(user_ids=["70", "71"])
            )
        return r1, r2

    r1, r2 = _run(go())
    assert r1["enqueued"] == 1
    assert r2.get("needs_confirmation") is True
    assert r2["duplicate_count"] == 1
    assert r2["fresh_count"] == 1
    dup_ids = {d["user_id"] for d in r2["duplicates"]}
    assert dup_ids == {"70"}


# ---------- admin alerts bypass dedup ----------

def test_send_hardcoded_no_dedup(tmp_path):
    """Admin alerts (payment notifications) must NOT dedup — different
    bodies, must always deliver."""
    _fresh_env(tmp_path)
    from services import notifier, whatsapp_client
    import aiosqlite
    import database

    async def go():
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            await notifier.send_hardcoded(
                "5511987654321", "Payment 1 — R$ 35", event_key="admin_alert",
            )
            await notifier.send_hardcoded(
                "5511987654321", "Payment 2 — R$ 90", event_key="admin_alert",
            )
        async with aiosqlite.connect(database.DB_PATH) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM notification_deliveries "
                "WHERE event_key = 'admin_alert' AND phone = '5511987654321'"
            )
            return (await cur.fetchone())[0]

    n = _run(go())
    assert n == 2, "Two admin alerts must produce TWO rows (no dedup)"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
