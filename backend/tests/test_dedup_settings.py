"""Test that the new admin-controlled dedup settings (`dedup_enabled` and
`dedup_window_minutes`) actually change delivery_queue behavior."""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "dedup_settings.db")
    import importlib
    import database as _db
    importlib.reload(_db)
    from services import delivery_queue, notifier
    importlib.reload(delivery_queue)
    importlib.reload(notifier)
    _run(_db.init_db())
    return _db


def test_dedup_disabled_via_setting(tmp_path):
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client
    import database

    async def go():
        # Turn dedup OFF via setting
        await database.set_setting("dedup_enabled", "false")
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            a = await delivery_queue.enqueue(
                "manual_expired_alert", "5511999998888", "hi 1",
            )
            b = await delivery_queue.enqueue(
                "manual_expired_alert", "5511999998888", "hi 2",
            )
        return a, b

    a, b = _run(go())
    assert a != b, "With dedup_enabled=false, both enqueues must create new rows"


def test_dedup_window_from_setting(tmp_path):
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client
    import database
    import aiosqlite
    from datetime import datetime, timezone, timedelta

    async def go():
        await database.set_setting("dedup_enabled", "true")
        # 30-minute window
        await database.set_setting("dedup_window_minutes", "30")
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            first = await delivery_queue.enqueue(
                "manual_expired_alert", "5511999998888", "old",
            )
            # Backdate to 40min ago — outside the 30-min window
            forty_ago = (
                datetime.now(timezone.utc) - timedelta(minutes=40)
            ).isoformat()
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute(
                    "UPDATE notification_deliveries "
                    "SET sent_at = ?, created_at = ? WHERE id = ?",
                    (forty_ago, forty_ago, first),
                )
                await db.commit()
            second = await delivery_queue.enqueue(
                "manual_expired_alert", "5511999998888", "new",
            )
        return first, second

    a, b = _run(go())
    assert a != b, "Send older than 30min (custom setting) should not dedup"


def test_dedup_enabled_setting_defaults_to_60min(tmp_path):
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client
    import database

    async def go():
        await database.set_setting("dedup_enabled", "true")
        await database.set_setting("dedup_window_minutes", "60")
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            a = await delivery_queue.enqueue(
                "manual_expired_alert", "5511999998888", "hi",
            )
            b = await delivery_queue.enqueue(
                "manual_expired_alert", "5511999998888", "hi again",
            )
        return a, b

    a, b = _run(go())
    assert a == b, "Within 60min with dedup enabled, second enqueue must reuse row"


def test_dedup_enabled_setting_falsey_variants(tmp_path):
    """`dedup_enabled` = '0', 'no', 'off', ''  should all disable dedup."""
    _fresh_env(tmp_path)
    from services import delivery_queue, whatsapp_client
    import database

    async def one(value: str):
        await database.set_setting("dedup_enabled", value)
        with patch.object(whatsapp_client, "send_message", new=AsyncMock(return_value=True)):
            a = await delivery_queue.enqueue(
                "manual_expired_alert", f"55119{hash(value) % 1000000000:09d}", "x",
            )
            b = await delivery_queue.enqueue(
                "manual_expired_alert", f"55119{hash(value) % 1000000000:09d}", "y",
            )
        assert a != b, f"Value '{value}' should disable dedup but reused row"

    async def go():
        for v in ("false", "0", "no", "off", ""):
            await one(v)

    _run(go())


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
