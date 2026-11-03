"""Tests: settings and templates writes must be mirrored to Atlas.

The mirror is best-effort — Atlas failing must NEVER break local writes.
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
    os.environ["SQLITE_PATH"] = str(tmp_path / "sync.db")
    import importlib
    import database
    importlib.reload(database)
    from services import mongo_store
    importlib.reload(mongo_store)
    return database


def test_set_setting_mirrors_to_mongo(tmp_path):
    database = _fresh_env(tmp_path)
    from services import mongo_store

    calls = []

    async def fake_upsert(key, value):
        calls.append((key, value))
        return True

    async def go():
        await database.init_db()
        with patch.object(mongo_store, "upsert_setting", new=fake_upsert):
            await database.set_setting("admin_whatsapp", "5511777777777")
            await database.set_setting("discount_7d_percent", "5")

    _run(go())
    assert ("admin_whatsapp", "5511777777777") in calls
    assert ("discount_7d_percent", "5") in calls


def test_set_setting_survives_mongo_failure(tmp_path):
    """Atlas down → local write must still succeed."""
    database = _fresh_env(tmp_path)
    from services import mongo_store

    async def bad_upsert(key, value):
        raise RuntimeError("Atlas unreachable")

    async def go():
        await database.init_db()
        with patch.object(mongo_store, "upsert_setting", new=bad_upsert):
            await database.set_setting("test_key", "test_value")
        # Local read succeeds
        return await database.get_setting("test_key")

    assert _run(go()) == "test_value"


def test_template_update_mirrors_to_mongo(tmp_path):
    database = _fresh_env(tmp_path)
    import aiosqlite
    from routers import notifications as notif
    from services import mongo_store
    from routers.notifications import NotifUpdate

    called = []

    async def fake_upsert_tpl(tpl):
        called.append(tpl)
        return True

    async def go():
        await database.init_db()
        # Templates are seeded by init_db — pick renewal_success and update it
        with patch.object(mongo_store, "upsert_template", new=fake_upsert_tpl):
            payload = NotifUpdate(body="✅ Novo corpo do template {name}")
            return await notif.update_notification("renewal_success", payload)

    result = _run(go())
    assert "Novo corpo do template" in result.body
    assert len(called) == 1
    assert called[0]["event_key"] == "renewal_success"
