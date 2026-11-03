"""Bug fix: refresh_cache_task must REPLACE the cache with painel data,
not merge it. Otherwise users deleted on painel persist as ghosts in the
Clientes page — customer count grows unbounded (263 shown vs 200 real).

Trial injections (upsert_users_in_cache marks `_pending_from_trial=True`)
must still survive one refresh cycle until painel reflects them.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_db():
    import aiosqlite

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    async def init():
        async with aiosqlite.connect(path) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS painel_users_cache "
                "(id TEXT PRIMARY KEY, data TEXT, updated_at TEXT)"
            )
            await db.commit()

    _run(init())
    return path


def test_refresh_purges_users_removed_from_painel(monkeypatch):
    """The main bug: painel returns 200 users, but local cache still has
    263 because deleted users were never purged. After the fix, the cache
    reflects painel exactly (minus any pending-from-trial injections).
    """
    from routers import painel_users
    from services import painel

    db_path = _fresh_db()
    monkeypatch.setattr(painel_users, "DB_PATH", db_path)

    async def go():
        # Seed cache with 3 users (as if painel returned them earlier)
        await painel_users._write_cache([
            {"id": 111, "username": "u1"},
            {"id": 222, "username": "u2"},
            {"id": 333, "username": "u3_deleted_on_painel"},
        ])
        # Now painel only returns 2 users (333 was deleted).
        painel_return = [
            {"id": 111, "username": "u1"},
            {"id": 222, "username": "u2"},
        ]
        with patch.object(painel, "list_users", new=AsyncMock(return_value=painel_return)):
            with patch("services.mongo_store.upsert_customer", new=AsyncMock(return_value="x")):
                await painel_users.refresh_cache_task()
        users, _ = await painel_users._read_cache()
        return users

    users = _run(go())
    ids = {str(u["id"]) for u in users}
    assert ids == {"111", "222"}, (
        f"Ghost user 333 must be purged after refresh. Got: {ids}"
    )


def test_refresh_preserves_pending_trials(monkeypatch):
    """Freshly-created trials (injected via upsert_users_in_cache) are marked
    `_pending_from_trial=True`. They must SURVIVE the next full refresh even
    though painel may not have reflected them yet (30–90s lag)."""
    from routers import painel_users
    from services import painel

    db_path = _fresh_db()
    monkeypatch.setattr(painel_users, "DB_PATH", db_path)

    async def go():
        # A trial just got created and injected via upsert (marks pending).
        await painel_users.upsert_users_in_cache([
            {"id": 999, "username": "brand_new_trial"},
        ])
        # painel_users.upsert marks with _pending_from_trial=True
        # Full refresh returns 2 old users (trial not yet reflected).
        painel_return = [
            {"id": 111, "username": "u1"},
            {"id": 222, "username": "u2"},
        ]
        with patch.object(painel, "list_users", new=AsyncMock(return_value=painel_return)):
            with patch("services.mongo_store.upsert_customer", new=AsyncMock(return_value="x")):
                await painel_users.refresh_cache_task()
        users, _ = await painel_users._read_cache()
        return users

    users = _run(go())
    ids = {str(u["id"]) for u in users}
    assert ids == {"111", "222", "999"}, (
        f"Pending trial 999 must survive refresh. Got: {ids}"
    )


def test_refresh_purges_trial_once_painel_confirms(monkeypatch):
    """Once painel returns the trial in its own list, subsequent refreshes
    should NOT keep a duplicate. The `_pending_from_trial` flag applies only
    when the id is NOT in the painel_keys set."""
    from routers import painel_users
    from services import painel

    db_path = _fresh_db()
    monkeypatch.setattr(painel_users, "DB_PATH", db_path)

    async def go():
        await painel_users.upsert_users_in_cache([
            {"id": 999, "username": "trial"},
        ])
        # Now painel also returns 999 as a real user.
        painel_return = [
            {"id": 111, "username": "u1"},
            {"id": 999, "username": "trial", "full_name": "From Painel"},
        ]
        with patch.object(painel, "list_users", new=AsyncMock(return_value=painel_return)):
            with patch("services.mongo_store.upsert_customer", new=AsyncMock(return_value="x")):
                await painel_users.refresh_cache_task()
        users, _ = await painel_users._read_cache()
        return users

    users = _run(go())
    # Exactly 2 users, no duplicate on id 999
    ids = [str(u["id"]) for u in users]
    assert sorted(ids) == ["111", "999"], f"Expected 2 unique users, got {ids}"
    # And the version stored should be the one from painel (full_name present)
    id_999 = next(u for u in users if str(u["id"]) == "999")
    assert id_999.get("full_name") == "From Painel"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
