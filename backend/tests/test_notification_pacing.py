"""Tests for expiration-notification pacing.

Requirement: instead of blasting all reminders in one go, we wait 2 minutes
(configurable via `notification_pacing_seconds`) between clients and simulate
"digitando..." (`notification_typing_ms`) so WhatsApp doesn't flag us as spam.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "pacing.db")
    import importlib
    import database
    importlib.reload(database)
    from services import scheduler, notifier, delivery_queue
    importlib.reload(delivery_queue)
    importlib.reload(notifier)
    importlib.reload(scheduler)
    return database


def _painel_user(uid, name, exp_days_ahead):
    exp_dt = (datetime.now(timezone.utc) + timedelta(days=exp_days_ahead))
    return {
        "id": uid, "username": f"user{uid}", "full_name": name,
        "as_number": f"55119000000{uid}", "enabled": 1,
        "exp_date": exp_dt.strftime("%Y-%m-%d %H:%M:%S"),
    }


def test_pacing_waits_between_clients(tmp_path):
    """3 clients matching the threshold → 2 sleeps between them
    (not before the first, not after the last)."""
    database = _fresh_env(tmp_path)
    from services import scheduler, painel, whatsapp_client

    sleeps = []
    real_sleep = asyncio.sleep

    async def spy_sleep(seconds):
        sleeps.append(seconds)
        # Don't actually wait — real_sleep(0) so the test runs fast.
        await real_sleep(0)

    async def fake_list_users(limit=10000):
        return [_painel_user("1", "Alice", 3),
                _painel_user("2", "Bob", 3),
                _painel_user("3", "Carol", 3)]

    typing_ms_seen = []

    async def fake_wa(phone, body, image_url=None, typing_ms=0):
        typing_ms_seen.append(typing_ms)

    async def go():
        await database.init_db()
        await database.set_setting("notification_days", "3")
        await database.set_setting("notification_pacing_seconds", "120")
        await database.set_setting("notification_typing_ms", "4000")
        with patch.object(painel, "list_users", new=fake_list_users), \
             patch.object(whatsapp_client, "send_message", new=fake_wa), \
             patch("services.scheduler.asyncio.sleep", new=spy_sleep):
            await scheduler._check_and_notify()

    _run(go())
    # 3 clients → 2 waits (between 1-2 and 2-3) at 120s each
    assert sleeps == [120, 120], f"got sleeps={sleeps}"
    # typing_ms=4000 forwarded on every send
    assert typing_ms_seen == [4000, 4000, 4000]


def test_pacing_zero_seconds_disables_wait(tmp_path):
    """notification_pacing_seconds=0 → no waits between clients."""
    database = _fresh_env(tmp_path)
    from services import scheduler, painel, whatsapp_client

    sleeps = []
    real_sleep = asyncio.sleep

    async def spy_sleep(seconds):
        sleeps.append(seconds)
        await real_sleep(0)

    async def fake_list_users(limit=10000):
        return [_painel_user("1", "Alice", 3), _painel_user("2", "Bob", 3)]

    async def fake_wa(phone, body, image_url=None, typing_ms=0):
        pass

    async def go():
        await database.init_db()
        await database.set_setting("notification_days", "3")
        await database.set_setting("notification_pacing_seconds", "0")
        with patch.object(painel, "list_users", new=fake_list_users), \
             patch.object(whatsapp_client, "send_message", new=fake_wa), \
             patch("services.scheduler.asyncio.sleep", new=spy_sleep):
            await scheduler._check_and_notify()

    _run(go())
    assert sleeps == [], f"got unexpected sleeps={sleeps}"


def test_only_one_client_has_zero_sleeps(tmp_path):
    """Single match → no sleep at all (nothing to wait between)."""
    database = _fresh_env(tmp_path)
    from services import scheduler, painel, whatsapp_client

    sleeps = []
    real_sleep = asyncio.sleep

    async def spy_sleep(seconds):
        sleeps.append(seconds)
        await real_sleep(0)

    async def fake_list_users(limit=10000):
        return [_painel_user("1", "Solo", 3)]

    async def fake_wa(phone, body, image_url=None, typing_ms=0):
        pass

    async def go():
        await database.init_db()
        await database.set_setting("notification_days", "3")
        with patch.object(painel, "list_users", new=fake_list_users), \
             patch.object(whatsapp_client, "send_message", new=fake_wa), \
             patch("services.scheduler.asyncio.sleep", new=spy_sleep):
            await scheduler._check_and_notify()

    _run(go())
    assert sleeps == []


def test_uses_real_name_not_generic_cliente(tmp_path):
    """The reminder must use the client's REAL name from painel.fun,
    never fall back to 'cliente' when a real name exists."""
    database = _fresh_env(tmp_path)
    from services import scheduler, painel, whatsapp_client

    bodies = []

    async def fake_wa(phone, body, image_url=None, typing_ms=0):
        bodies.append(body)

    async def fake_list_users(limit=10000):
        # Even if `name` is missing, `full_name` should be used.
        return [{
            "id": "99", "username": "guilherme_vip",
            "full_name": "Guilherme Zeferius",  # <-- real name
            "as_number": "5511987654321",
            "enabled": 1,
            "exp_date": (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
        }]

    async def go():
        await database.init_db()
        await database.set_setting("notification_days", "3")
        await database.set_setting("notification_pacing_seconds", "0")
        with patch.object(painel, "list_users", new=fake_list_users), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            await scheduler._check_and_notify()

    _run(go())
    assert len(bodies) == 1, bodies
    # Template body contains the name
    assert "Guilherme Zeferius" in bodies[0], f"body={bodies[0]!r}"
    # Never fall back to 'cliente' when a real name exists
    assert "Olá cliente" not in bodies[0]
