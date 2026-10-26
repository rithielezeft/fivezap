"""Tests for the bot MAC-retry flow (3 attempts before giving up).

Verifies:
- Client sending a template that requires MAC (without MAC) → bot asks for MAC
  and sets pending state.
- Next message from same phone with a valid MAC → trial is created with that MAC.
- Invalid MAC on retry → bot explains format, decrements remaining attempts.
- After 3 invalid attempts → bot gives up and clears state.
- Various MAC input formats are accepted (`:`, `-`, no separator).
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import bot  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ---------------- MAC parsing helper ----------------

def test_parse_mac_colon():
    assert bot._parse_mac("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"


def test_parse_mac_dash():
    assert bot._parse_mac("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"


def test_parse_mac_no_separator():
    assert bot._parse_mac("D8A35C568656") == "D8:A3:5C:56:86:56"


def test_parse_mac_lowercase_normalized():
    assert bot._parse_mac("d8:a3:5c:56:86:56") == "D8:A3:5C:56:86:56"


def test_parse_mac_embedded_in_sentence():
    assert bot._parse_mac("meu mac é 55:F0:DC:50:5C:2C aqui") == "55:F0:DC:50:5C:2C"


def test_parse_mac_invalid_returns_none():
    assert bot._parse_mac("meu numero é 5511987654321") is None
    assert bot._parse_mac("olá") is None
    assert bot._parse_mac("") is None


# ---------------- MAC retry state machine ----------------

def _setup_template_in_db(monkeypatch, requires_mac=True, system="hybrid"):
    """Stub DB access so we don't need a real SQLite for these tests."""
    template = {
        "id": "tpl-hybrid-1",
        "name": "test hybrid",
        "trigger_command": "teste",
        "trigger_source": "client",
        "requires_mac": 1 if requires_mac else 0,
        "system_type": system,
        "package_id": 61,
        "response_template": "OK",
        "enabled": 1,
    }
    return template


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, template):
        self._template = template
        self.row_factory = None

    async def execute(self, sql, args=()):
        if "command_templates" in sql:
            return _FakeCursor([self._template])
        # INSERT / UPDATE / etc.
        return _FakeCursor([])

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass


def _patch_aiosqlite(template):
    """Return a context manager that patches aiosqlite.connect to return FakeConn."""
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        conn = _FakeConn(template)
        with patch("services.bot.aiosqlite.connect", return_value=conn):
            yield

    return _cm()


def test_first_message_without_mac_asks_and_sets_pending():
    """Client sends 'teste' (no MAC) → bot asks, sets _pending_mac state."""
    template = _setup_template_in_db(None, requires_mac=True, system="hybrid")
    bot._pending_mac.clear()

    sent = []

    async def fake_send(phone, text, *a, **kw):
        sent.append((phone, text))

    async def fake_find(phone, name=None):
        return {"id": "c1", "name": "Ana", "whatsapp": phone, "system_type": "unknown"}

    async def fake_save(*a, **kw):
        pass

    async def go():
        with _patch_aiosqlite(template), \
             patch("services.bot.whatsapp_client.send_message", new=fake_send), \
             patch("services.bot.find_or_create_customer", new=fake_find), \
             patch("services.bot.save_message", new=fake_save), \
             patch("services.bot.log_activity", new=AsyncMock()):
            await bot.process_incoming_message("5511900000001", "teste", from_me=False, name="Ana")

    _run(go())
    assert "5511900000001" in bot._pending_mac
    assert bot._pending_mac["5511900000001"]["attempts"] == 0
    assert bot._pending_mac["5511900000001"]["template_id"] == "tpl-hybrid-1"
    # First message should mention the format
    assert any("AA:BB:CC:DD:EE:FF" in s[1] for s in sent)


def test_valid_mac_reply_triggers_trial_creation():
    """After asking, client replies with a valid MAC → _run_trial_creation is called."""
    template = _setup_template_in_db(None, requires_mac=True, system="hybrid")
    bot._pending_mac.clear()
    bot._pending_mac["5511900000002"] = {
        "template_id": "tpl-hybrid-1",
        "attempts": 0,
        "started_at": asyncio.get_event_loop().time() if False else __import__("time").time(),
        "customer_id": "c2",
    }

    run_trial = AsyncMock()

    async def fake_find(phone, name=None):
        return {"id": "c2", "name": "Bruno", "whatsapp": phone, "system_type": "unknown"}

    async def fake_save(*a, **kw):
        pass

    async def go():
        with _patch_aiosqlite(template), \
             patch("services.bot._run_trial_creation", new=run_trial), \
             patch("services.bot.find_or_create_customer", new=fake_find), \
             patch("services.bot.save_message", new=fake_save), \
             patch("services.bot.log_activity", new=AsyncMock()):
            await bot.process_incoming_message("5511900000002", "55:F0:DC:50:5C:2C", from_me=False)

    _run(go())
    run_trial.assert_awaited_once()
    # 3rd arg (positional) is the MAC
    args = run_trial.await_args.args
    assert args[2] == "55:F0:DC:50:5C:2C"
    # State cleared
    assert "5511900000002" not in bot._pending_mac


def test_invalid_mac_reply_decrements_attempts_and_explains():
    template = _setup_template_in_db(None, requires_mac=True, system="hybrid")
    bot._pending_mac.clear()
    import time as _time
    bot._pending_mac["5511900000003"] = {
        "template_id": "tpl-hybrid-1",
        "attempts": 0,
        "started_at": _time.time(),
        "customer_id": "c3",
    }

    sent = []

    async def fake_send(phone, text, *a, **kw):
        sent.append((phone, text))

    async def fake_find(phone, name=None):
        return {"id": "c3", "name": "Carol", "whatsapp": phone, "system_type": "unknown"}

    async def fake_save(*a, **kw):
        pass

    async def go():
        with _patch_aiosqlite(template), \
             patch("services.bot.whatsapp_client.send_message", new=fake_send), \
             patch("services.bot.find_or_create_customer", new=fake_find), \
             patch("services.bot.save_message", new=fake_save), \
             patch("services.bot.log_activity", new=AsyncMock()):
            await bot.process_incoming_message("5511900000003", "não sei meu mac", from_me=False)

    _run(go())
    assert bot._pending_mac["5511900000003"]["attempts"] == 1
    # Format hint sent to client
    assert any("AA:BB:CC:DD:EE:FF" in s[1] for s in sent)
    # And still mentions remaining tries
    assert any("tentativa" in s[1].lower() for s in sent)


def test_three_invalid_attempts_clears_state_and_gives_up():
    template = _setup_template_in_db(None, requires_mac=True, system="hybrid")
    bot._pending_mac.clear()
    import time as _time
    phone = "5511900000004"
    bot._pending_mac[phone] = {
        "template_id": "tpl-hybrid-1",
        "attempts": 0,
        "started_at": _time.time(),
        "customer_id": "c4",
    }

    sent = []

    async def fake_send(p, text, *a, **kw):
        sent.append((p, text))

    async def fake_find(p, name=None):
        return {"id": "c4", "name": "Dan", "whatsapp": p, "system_type": "unknown"}

    async def fake_save(*a, **kw):
        pass

    async def go():
        with _patch_aiosqlite(template), \
             patch("services.bot.whatsapp_client.send_message", new=fake_send), \
             patch("services.bot.find_or_create_customer", new=fake_find), \
             patch("services.bot.save_message", new=fake_save), \
             patch("services.bot.log_activity", new=AsyncMock()):
            # 3 consecutive invalid messages
            await bot.process_incoming_message(phone, "nao sei", from_me=False)
            await bot.process_incoming_message(phone, "onde acho isso?", from_me=False)
            await bot.process_incoming_message(phone, "pode ajudar?", from_me=False)

    _run(go())
    # State cleared after 3rd fail
    assert phone not in bot._pending_mac
    # Last outbound message must mention giving up (or "3 tentativas")
    last = sent[-1][1].lower()
    assert "3 tentativas" in last or "atendente" in last


def test_mac_arriving_after_2_failures_still_works():
    template = _setup_template_in_db(None, requires_mac=True, system="hybrid")
    bot._pending_mac.clear()
    import time as _time
    phone = "5511900000005"
    bot._pending_mac[phone] = {
        "template_id": "tpl-hybrid-1",
        "attempts": 2,  # already failed twice
        "started_at": _time.time(),
        "customer_id": "c5",
    }

    run_trial = AsyncMock()

    async def fake_find(p, name=None):
        return {"id": "c5", "name": "Eve", "whatsapp": p, "system_type": "unknown"}

    async def fake_save(*a, **kw):
        pass

    async def go():
        with _patch_aiosqlite(template), \
             patch("services.bot._run_trial_creation", new=run_trial), \
             patch("services.bot.find_or_create_customer", new=fake_find), \
             patch("services.bot.save_message", new=fake_save), \
             patch("services.bot.log_activity", new=AsyncMock()):
            await bot.process_incoming_message(phone, "AA-BB-CC-DD-EE-FF", from_me=False)

    _run(go())
    run_trial.assert_awaited_once()
    assert phone not in bot._pending_mac


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
