"""Tests: GET /api/painel/users?force=true blocks until fresh data is
pulled from painel.fun before responding. This is what the Clientes page
uses on mount so the client never sees stale local data on first open.

Also tests that `{user}` (painel_username) is exposed in the scheduler
reminder ctx so the template can render `{user}` in addition to `{name}`.
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "force.db")
    import importlib
    import database
    importlib.reload(database)
    from routers import painel_users
    importlib.reload(painel_users)
    return database


def test_force_true_awaits_refresh_before_reading_cache(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import painel_users as pu

    refresh_calls = []

    async def fake_refresh():
        refresh_calls.append(1)
        # Simulate a refresh that writes fresh users to the cache
        await pu._write_cache([{
            "id": "42", "username": "fresh_user", "full_name": "Fresh",
        }])

    async def go():
        await database.init_db()
        # Pre-populate cache with stale data
        await pu._write_cache([{"id": "1", "username": "stale", "full_name": "Old"}])
        with patch.object(pu, "refresh_cache_task", new=fake_refresh):
            return await pu.list_users(force=True)

    result = _run(go())
    # Refresh was awaited BEFORE serving
    assert len(refresh_calls) == 1
    # Response contains the fresh data, not the stale one
    users = result["users"]
    assert any(u.get("id") == "42" for u in users)


def test_force_false_returns_cache_without_awaiting(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import painel_users as pu

    refresh_calls = []

    async def fake_refresh():
        refresh_calls.append(1)

    async def go():
        await database.init_db()
        await pu._write_cache([{"id": "1", "username": "cached"}])
        with patch.object(pu, "refresh_cache_task", new=fake_refresh):
            return await pu.list_users()  # no force

    _run(go())
    # Fresh cache (just now) → no background refresh triggered synchronously
    assert refresh_calls == []


def test_force_refresh_survives_painel_failure(tmp_path):
    """If painel.fun is unreachable, force=true still returns cached data."""
    database = _fresh_env(tmp_path)
    from routers import painel_users as pu

    async def bad_refresh():
        raise RuntimeError("painel down")

    async def go():
        await database.init_db()
        await pu._write_cache([{"id": "1", "username": "cached_fallback"}])
        with patch.object(pu, "refresh_cache_task", new=bad_refresh):
            return await pu.list_users(force=True)

    result = _run(go())
    # Endpoint didn't crash — cache was served
    users = result["users"]
    assert len(users) == 1
    assert users[0]["username"] == "cached_fallback"


# ---------- {user} variable in scheduler ctx ----------

def test_scheduler_ctx_includes_user_variable(tmp_path):
    """Every reminder template can render `{user}` (=painel_username)."""
    database = _fresh_env(tmp_path)
    from datetime import datetime, timezone, timedelta
    from services import scheduler, painel, whatsapp_client

    bodies = []

    async def fake_wa(phone, body, image_url=None, typing_ms=0):
        bodies.append(body)

    async def fake_list_users(limit=10000):
        return [{
            "id": "228116806",
            "username": "joao_iptv44",
            "full_name": "João Cliente",
            "as_number": "5511987654321",
            "enabled": 1,
            "exp_date": (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
        }]

    async def go():
        await database.init_db()
        await database.set_setting("notification_days", "3")
        await database.set_setting("notification_pacing_seconds", "0")
        # Point the template body at {user} so we can verify substitution
        import aiosqlite
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "UPDATE notification_templates SET body = 'Olá {user} (nome: {name})' "
                "WHERE event_key = 'expiration_3d'"
            )
            await db.commit()
        with patch.object(painel, "list_users", new=fake_list_users), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):
            await scheduler._check_and_notify()

    _run(go())
    assert len(bodies) == 1
    assert "joao_iptv44" in bodies[0]  # {user} rendered
    assert "João Cliente" in bodies[0]  # {name} rendered
