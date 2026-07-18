"""Test that painel users cache refresh is triggered after every trial creation.

Ensures the admin /customers page shows freshly-created trials immediately.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_fake_aiosqlite(template_row):
    class _FakeCursor:
        def __init__(self, rows):
            self._rows = rows
        async def fetchall(self):
            return self._rows
        async def fetchone(self):
            return self._rows[0] if self._rows else None

    class _FakeDB:
        row_factory = None
        async def execute(self, sql, *a, **k):
            up = sql.upper() if isinstance(sql, str) else ""
            if "COMMAND_TEMPLATES" in up and "SELECT" in up:
                return _FakeCursor([template_row])
            return _FakeCursor([])
        async def commit(self): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    return lambda *a, **k: _FakeDB()


def _template_row():
    return {
        "id": "tpl_x",
        "name": "P2P",
        "trigger_command": "p2p",
        "system_type": "p2p",
        "requires_mac": 0,
        "package_id": None,
        "response_template": "ok {user}",
        "enabled": 1,
        "trigger_source": "both",
        "created_at": "2026-01-01T00:00:00Z",
    }


def test_bot_triggers_cache_refresh_after_trial_creation(monkeypatch):
    from services import bot, painel, whatsapp_client
    from routers import painel_users

    bot._recent_messages.clear()

    refresh_calls = {"count": 0}

    async def fake_refresh():
        refresh_calls["count"] += 1

    monkeypatch.setattr(painel_users, "refresh_cache_task", fake_refresh)

    async def fake_save_message(*a, **k): pass
    async def fake_find(phone, name=None):
        return {"id": "c1", "name": name or phone, "whatsapp": phone, "system_type": "unknown"}
    async def fake_log(*a, **k): pass
    async def fake_get_setting(key, default=None):
        return {"public_base_url": "https://x.test", "infinitepay_handle": ""}.get(key, default or "")

    monkeypatch.setattr(bot, "save_message", fake_save_message)
    monkeypatch.setattr(bot, "find_or_create_customer", fake_find)
    monkeypatch.setattr(bot, "log_activity", fake_log)
    monkeypatch.setattr(bot.aiosqlite, "connect", _make_fake_aiosqlite(_template_row()))
    import database
    monkeypatch.setattr(database, "get_setting", fake_get_setting)

    async def fake_create_trial(**kw):
        return {"id": 999, "username": "u", "password": "p", "expires_at": "x"}
    monkeypatch.setattr(painel, "create_trial", fake_create_trial)

    async def fake_send(phone, msg, *a, **k): pass
    monkeypatch.setattr(whatsapp_client, "send_message", fake_send)

    # Reminders: no-op
    from services import reminders
    async def _no_schedule(*a, **k): pass
    monkeypatch.setattr(reminders, "schedule", _no_schedule)

    async def go():
        await bot.process_incoming_message("5511@c.us", "p2p", from_me=False)
        # Give the fire-and-forget create_task a tick to run
        await asyncio.sleep(0.05)

    asyncio.run(go())

    assert refresh_calls["count"] == 1, \
        f"Expected 1 cache refresh after trial creation, got {refresh_calls['count']}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
