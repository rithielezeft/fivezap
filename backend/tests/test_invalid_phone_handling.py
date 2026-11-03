"""Bug fix: when WhatsApp service returns `404 — "Este número não está no
WhatsApp"`, we must:
  1. NOT retry (5x is wasteful — the number will never be on WhatsApp)
  2. NOT alert the admin (it's not actionable, just spam)
  3. Mark the delivery as `invalid_phone` (distinguishable from failed_permanent)
  4. Clear the invalid phone from the local `customers` row so future syncs
     don't re-enqueue for the same broken number.
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "invalid_phone.db")
    import importlib
    import database as _db
    importlib.reload(_db)
    from services import delivery_queue, notifier
    importlib.reload(delivery_queue)
    importlib.reload(notifier)
    _run(_db.init_db())
    return _db


INVALID_PHONE_ERROR = (
    'WA send failed: 404 {"error":"Este número não está no WhatsApp",'
    '"phone":"5511900000000"}'
)


def test_invalid_phone_marks_delivery_and_stops_retry(tmp_path):
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client
    import aiosqlite
    import database

    async def go():
        async def raise_invalid(*a, **kw):
            raise RuntimeError(INVALID_PHONE_ERROR)

        with patch.object(whatsapp_client, "send_message", new=raise_invalid):
            did = await delivery_queue.enqueue(
                "expiration_0d", "5511900000000", "seu plano venceu",
                dedup_window_minutes=0,
            )
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM notification_deliveries WHERE id = ?", (did,)
            )
            row = await cur.fetchone()
        return dict(row)

    d = _run(go())
    assert d["status"] == "invalid_phone", (
        f"Expected 'invalid_phone', got {d['status']}. last_error={d['last_error']}"
    )
    assert d["attempts"] == 1, f"Expected only 1 attempt, got {d['attempts']}"
    assert d["next_retry_at"] is None, "No retry should be scheduled"


def test_invalid_phone_does_not_alert_admin(tmp_path):
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client
    import database

    admin_msgs = []

    async def fake_send(phone, body, **kw):
        # If the admin_whatsapp is set and we're called with THAT number,
        # count it as an admin alert.
        if phone == "5511987654321":
            admin_msgs.append({"phone": phone, "body": body})
            return True
        raise RuntimeError(INVALID_PHONE_ERROR)

    async def go():
        await database.set_setting("admin_whatsapp", "5511987654321")
        with patch.object(whatsapp_client, "send_message", new=fake_send):
            await delivery_queue.enqueue(
                "expiration_0d", "5511900000000", "seu plano venceu",
                dedup_window_minutes=0,
            )

    _run(go())
    assert not admin_msgs, (
        f"Admin should NOT be alerted for invalid_phone errors. Got: {admin_msgs}"
    )


def test_invalid_phone_clears_local_customer_whatsapp(tmp_path):
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client
    import aiosqlite
    import database

    async def go():
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, "
                "expires_at, status, created_at, updated_at) "
                "VALUES ('c1', 'Zé', '5511900000000', 'iptv', '', 'active', "
                "'2026-01-01', '2026-01-01')",
            )
            await db.commit()

        async def raise_invalid(*a, **kw):
            raise RuntimeError(INVALID_PHONE_ERROR)

        with patch.object(whatsapp_client, "send_message", new=raise_invalid):
            await delivery_queue.enqueue(
                "expiration_0d", "5511900000000", "vence hoje",
                dedup_window_minutes=0,
            )

        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT whatsapp FROM customers WHERE id = 'c1'")
            row = await cur.fetchone()
        return row["whatsapp"]

    wa = _run(go())
    assert wa == "", (
        f"Invalid phone must be cleared from customer to avoid re-enqueue. Got: {wa!r}"
    )


def test_regular_failure_still_retries_and_alerts(tmp_path):
    """Non-invalid-phone errors must keep the previous retry + alert behaviour."""
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client
    import aiosqlite
    import database

    async def go():
        async def raise_timeout(*a, **kw):
            raise RuntimeError("Connection timed out (whatsapp service down)")

        with patch.object(whatsapp_client, "send_message", new=raise_timeout):
            did = await delivery_queue.enqueue(
                "expiration_0d", "5511987654321", "body",
                dedup_window_minutes=0,
            )
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM notification_deliveries WHERE id = ?", (did,)
            )
            row = await cur.fetchone()
        return dict(row)

    d = _run(go())
    # Regular failure → status stays pending with retry scheduled
    assert d["status"] == "pending", f"Expected pending retry, got {d['status']}"
    assert d["next_retry_at"] is not None, "Retry must be scheduled"


def test_invalid_phone_detection_various_formats(tmp_path):
    _fresh_env(tmp_path)
    from services.delivery_queue import _is_invalid_phone_error

    positives = [
        'WA send failed: 404 {"error":"Este número não está no WhatsApp"}',
        'Este numero nao esta no whatsapp',  # ASCII-only
        'phone not on WhatsApp',
        'error: not a WhatsApp number',
        '{"code":404,"details":"no whatsapp account for this phone"}',
        'HTTP 404 WhatsApp check failed',
    ]
    negatives = [
        'Connection timed out',
        'WA service returned 500',
        'Unknown internal error',
        'rate limited',
        '',
    ]
    for e in positives:
        assert _is_invalid_phone_error(e), f"Should be detected as invalid: {e!r}"
    for e in negatives:
        assert not _is_invalid_phone_error(e), (
            f"Should NOT be detected as invalid: {e!r}"
        )


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
