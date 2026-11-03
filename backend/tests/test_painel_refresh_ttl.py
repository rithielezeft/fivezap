"""Test that the `painel_refresh_interval_seconds` setting controls when
the /api/painel/users endpoint triggers a background painel.fun refresh.

Each background refresh burns 2Captcha credits, so raising this setting
in the admin UI must actually reduce refresh frequency.
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
    os.environ["SQLITE_PATH"] = str(tmp_path / "refresh_ttl.db")
    import importlib
    import database as _db
    importlib.reload(_db)
    from routers import painel_users
    importlib.reload(painel_users)
    # Reset the module-level "running" flag so guard doesn't block us.
    painel_users._refresh_state["running"] = False
    _run(_db.init_db())
    return _db


async def _backdate_cache(seconds_ago: int):
    """Set cache updated_at to `seconds_ago` ago so list_users sees it stale."""
    import aiosqlite
    import database
    when = (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "UPDATE painel_users_cache SET updated_at = ? WHERE id = 'all'",
            (when,),
        )
        await db.commit()


def test_default_ttl_is_300_seconds(tmp_path):
    """With default setting (300s), a 400s-old cache triggers a refresh."""
    _fresh_env(tmp_path)
    from routers import painel_users
    from fastapi import BackgroundTasks

    async def go():
        # Seed some cache so `users` is truthy — otherwise it always refreshes.
        await painel_users._write_cache([{"id": 1, "username": "u1"}])
        await _backdate_cache(400)  # older than 300s default
        bg = BackgroundTasks()
        with patch.object(painel_users, "refresh_cache_task",
                          new=AsyncMock(return_value=None)) as mock_refresh:
            await painel_users.list_users(background_tasks=bg)
        return bg.tasks, mock_refresh.call_count

    tasks, calls = _run(go())
    # Background task was scheduled (calls happen when bg executes, but
    # the task list contains the function)
    assert len(tasks) == 1, "Refresh must be scheduled when cache is stale"


def test_custom_ttl_from_setting_disables_short_refreshes(tmp_path):
    """With setting=600s, a 400s-old cache should NOT trigger a refresh."""
    _fresh_env(tmp_path)
    from routers import painel_users
    from fastapi import BackgroundTasks
    import database

    async def go():
        await database.set_setting("painel_refresh_interval_seconds", "600")
        await painel_users._write_cache([{"id": 1, "username": "u1"}])
        await _backdate_cache(400)  # NEWER than 600s setting
        bg = BackgroundTasks()
        await painel_users.list_users(background_tasks=bg)
        return bg.tasks

    tasks = _run(go())
    assert len(tasks) == 0, (
        "With 600s TTL, a 400s-old cache is still fresh → no refresh"
    )


def test_ttl_setting_respected_when_cache_older(tmp_path):
    """Cache older than the setting must trigger a refresh."""
    _fresh_env(tmp_path)
    from routers import painel_users
    from fastapi import BackgroundTasks
    import database

    async def go():
        await database.set_setting("painel_refresh_interval_seconds", "600")
        await painel_users._write_cache([{"id": 1, "username": "u1"}])
        await _backdate_cache(700)  # older than 600s setting
        bg = BackgroundTasks()
        await painel_users.list_users(background_tasks=bg)
        return bg.tasks

    tasks = _run(go())
    assert len(tasks) == 1


def test_minimum_ttl_of_30_seconds_enforced(tmp_path):
    """Admin can't set below 30s (accidental hammering protection)."""
    _fresh_env(tmp_path)
    from routers import painel_users
    from fastapi import BackgroundTasks
    import database

    async def go():
        await database.set_setting("painel_refresh_interval_seconds", "5")  # too low
        await painel_users._write_cache([{"id": 1, "username": "u1"}])
        await _backdate_cache(20)  # would trigger if 5s honored, but clamped to 30
        bg = BackgroundTasks()
        await painel_users.list_users(background_tasks=bg)
        return bg.tasks

    tasks = _run(go())
    assert len(tasks) == 0, "Setting <30 is clamped to 30 → 20s cache is fresh"


def test_invalid_setting_falls_back_to_300(tmp_path):
    _fresh_env(tmp_path)
    from routers import painel_users
    from fastapi import BackgroundTasks
    import database

    async def go():
        await database.set_setting("painel_refresh_interval_seconds", "not-a-number")
        await painel_users._write_cache([{"id": 1, "username": "u1"}])
        await _backdate_cache(200)  # under 300 fallback → no refresh
        bg = BackgroundTasks()
        await painel_users.list_users(background_tasks=bg)
        return bg.tasks

    tasks = _run(go())
    assert len(tasks) == 0


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
