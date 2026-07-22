"""Tests: POST /api/notifications/{event_key}/restore-defaults resets a
template to the shipping default (from services.default_templates).

Preserves the `enabled` flag so admins don't accidentally re-enable a
template they'd turned off.
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
    os.environ["SQLITE_PATH"] = str(tmp_path / "restore.db")
    import importlib
    import database
    importlib.reload(database)
    from routers import notifications
    importlib.reload(notifications)
    from services import mongo_store
    importlib.reload(mongo_store)
    return database


def test_restore_overwrites_customized_body(tmp_path):
    database = _fresh_env(tmp_path)
    import aiosqlite
    from routers import notifications as notif
    from services import mongo_store

    async def go():
        await database.init_db()
        # Customize renewal_success so restore has something to undo
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "UPDATE notification_templates SET body = 'MEU CUSTOM' WHERE event_key = 'renewal_success'"
            )
            await db.commit()

        with patch.object(mongo_store, "upsert_template", new=lambda t: asyncio.sleep(0)):
            return await notif.restore_default_template("renewal_success")

    result = _run(go())
    assert "{user}" in result.body   # <-- the whole point
    assert "MEU CUSTOM" not in result.body
    assert result.event_key == "renewal_success"


def test_restore_preserves_enabled_flag(tmp_path):
    database = _fresh_env(tmp_path)
    import aiosqlite
    from routers import notifications as notif
    from services import mongo_store

    async def go():
        await database.init_db()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "UPDATE notification_templates SET enabled = 0, body = 'X' WHERE event_key = 'expiration_7d'"
            )
            await db.commit()
        with patch.object(mongo_store, "upsert_template", new=lambda t: asyncio.sleep(0)):
            return await notif.restore_default_template("expiration_7d")

    result = _run(go())
    assert result.enabled == 0  # <-- preserved
    assert "{user}" in result.body


def test_restore_unknown_key_returns_404(tmp_path):
    database = _fresh_env(tmp_path)
    from fastapi import HTTPException
    from routers import notifications as notif

    async def go():
        await database.init_db()
        try:
            return await notif.restore_default_template("nao_existe")
        except HTTPException as e:
            return e.status_code

    assert _run(go()) == 404


def test_defaults_contain_user_variable(tmp_path):
    """Regression: every default template with `{name}` should also have `{user}`."""
    _fresh_env(tmp_path)
    from services.default_templates import DEFAULT_TEMPLATES
    for t in DEFAULT_TEMPLATES:
        assert "{name}" in t["body"], t["event_key"]
        assert "{user}" in t["body"], f"{t['event_key']} missing {{user}}"
