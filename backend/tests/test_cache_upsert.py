"""Tests for cache upsert + resilient refresh (never wipes existing users)."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_db():
    """Create an isolated SQLite DB for this test."""
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


def test_upsert_users_in_cache_adds_new_users(monkeypatch):
    from routers import painel_users
    db_path = _fresh_db()
    monkeypatch.setattr(painel_users, "DB_PATH", db_path)

    async def go():
        added = await painel_users.upsert_users_in_cache([
            {"id": 111, "username": "u1", "full_name": "One"},
            {"id": 222, "username": "u2", "full_name": "Two"},
        ])
        users, _ = await painel_users._read_cache()
        return added, users

    added, users = _run(go())
    assert added == 2
    assert len(users) == 2
    ids = {str(u["id"]) for u in users}
    assert ids == {"111", "222"}


def test_upsert_merges_updates_existing_user(monkeypatch):
    """Upserting an existing user must UPDATE it, not duplicate."""
    from routers import painel_users
    db_path = _fresh_db()
    monkeypatch.setattr(painel_users, "DB_PATH", db_path)

    async def go():
        await painel_users.upsert_users_in_cache([
            {"id": 111, "username": "u1", "full_name": "Old Name"},
        ])
        # Now update with new data
        await painel_users.upsert_users_in_cache([
            {"id": 111, "username": "u1", "full_name": "New Name", "extra": "field"},
        ])
        users, _ = await painel_users._read_cache()
        return users

    users = _run(go())
    assert len(users) == 1
    assert users[0]["full_name"] == "New Name"
    assert users[0]["extra"] == "field"


def test_upsert_preserves_existing_when_adding_new(monkeypatch):
    """Adding a new user must NOT wipe already-present users (main bug fix)."""
    from routers import painel_users
    db_path = _fresh_db()
    monkeypatch.setattr(painel_users, "DB_PATH", db_path)

    async def go():
        # Seed with 3 existing users
        await painel_users.upsert_users_in_cache([
            {"id": 111, "username": "u1"},
            {"id": 222, "username": "u2"},
            {"id": 333, "username": "u3"},
        ])
        # Inject a single new one (like after trial creation)
        added = await painel_users.upsert_users_in_cache([
            {"id": 999, "username": "brand_new_trial"},
        ])
        users, _ = await painel_users._read_cache()
        return added, users

    added, users = _run(go())
    assert added == 1
    ids = {str(u["id"]) for u in users}
    assert ids == {"111", "222", "333", "999"}, \
        "Upsert must NOT wipe existing users — payment links for other customers would break!"


def test_refresh_task_keeps_cache_on_empty_painel_response(monkeypatch):
    """If painel returns [] (transient error), existing cache MUST be preserved.
    Otherwise every active pay link would break."""
    from routers import painel_users
    from services import painel
    db_path = _fresh_db()
    monkeypatch.setattr(painel_users, "DB_PATH", db_path)

    async def go():
        # Pre-populate cache with active users
        await painel_users.upsert_users_in_cache([
            {"id": 555, "username": "active_customer_1"},
            {"id": 666, "username": "active_customer_2"},
        ])
        # painel.list_users returns empty → simulate transient outage
        with patch.object(painel, "list_users", new=AsyncMock(return_value=[])):
            await painel_users.refresh_cache_task()
        users, _ = await painel_users._read_cache()
        return users

    users = _run(go())
    ids = {str(u["id"]) for u in users}
    assert ids == {"555", "666"}, \
        "Empty painel response must not wipe existing users"


def test_refresh_task_keeps_cache_on_painel_exception(monkeypatch):
    from routers import painel_users
    from services import painel
    db_path = _fresh_db()
    monkeypatch.setattr(painel_users, "DB_PATH", db_path)

    async def go():
        await painel_users.upsert_users_in_cache([
            {"id": 777, "username": "still_active"},
        ])

        async def broken_list(**k):
            raise RuntimeError("cloudflare 403")

        with patch.object(painel, "list_users", new=broken_list):
            await painel_users.refresh_cache_task()
        users, _ = await painel_users._read_cache()
        return users

    users = _run(go())
    assert len(users) == 1
    assert str(users[0]["id"]) == "777"


def test_refresh_task_merges_new_users_with_existing(monkeypatch):
    """When painel returns fresh users, merge them with existing rather than replacing."""
    from routers import painel_users
    from services import painel
    db_path = _fresh_db()
    monkeypatch.setattr(painel_users, "DB_PATH", db_path)

    async def go():
        # Cache has a very recent trial (just created, injected via upsert)
        await painel_users.upsert_users_in_cache([
            {"id": 999, "username": "just_created_trial"},
        ])
        # painel.list_users returns previously-known users (not yet including the trial)
        painel_return = [
            {"id": 111, "username": "old1", "full_name": "Old1"},
            {"id": 222, "username": "old2", "full_name": "Old2"},
        ]
        with patch.object(painel, "list_users", new=AsyncMock(return_value=painel_return)):
            await painel_users.refresh_cache_task()
        users, _ = await painel_users._read_cache()
        return users

    users = _run(go())
    ids = {str(u["id"]) for u in users}
    assert ids == {"111", "222", "999"}, \
        "Freshly-injected trial (999) must survive the refresh even if painel doesn't return it yet"


def test_refresh_task_mirrors_all_users_to_mongo(monkeypatch):
    """When the customer-page refresh runs, EVERY painel user (not just new
    trials) must be pushed to MongoDB Atlas so their /pay/{id} works globally."""
    from routers import painel_users
    from services import painel, mongo_store
    db_path = _fresh_db()
    monkeypatch.setattr(painel_users, "DB_PATH", db_path)

    mongo_upserts = []

    async def fake_upsert(doc):
        mongo_upserts.append(doc)
        return str(doc.get("_id", ""))

    monkeypatch.setattr(mongo_store, "upsert_customer", fake_upsert)

    painel_users_data = [
        {"id": 111, "username": "u1", "full_name": "One", "exp_date": 1900000000, "enabled": 1, "as_number": "5511111"},
        {"id": 222, "username": "u2", "full_name": "Two", "exp_date": 1900000000, "enabled": 1, "as_number": "5511222"},
        {"id": 333, "username": "u3", "full_name": "Three", "exp_date": 1900000000, "enabled": 1, "as_number": "5511333"},
    ]

    async def go():
        with patch.object(painel, "list_users", new=AsyncMock(return_value=painel_users_data)):
            await painel_users.refresh_cache_task()

    _run(go())

    # All 3 users pushed to Mongo
    ids = {u["_id"] for u in mongo_upserts}
    assert ids == {"111", "222", "333"}, \
        "refresh_cache_task must sync EVERY painel user to Mongo, not just some"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
