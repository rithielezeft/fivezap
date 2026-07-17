"""Tests for the trial-duplication bug fix (iteration 9).

Covers:
- Backend dedup by (phone, body, direction) in bot.process_incoming_message
- normalize_phone semantics (@lid preserved, @c.us stripped, plain kept)
- _recent_messages is a global dict initialized at import time
- POST /api/whatsapp/incoming rapid double-fire dedup
- POST /api/whatsapp/incoming distinct bodies both processed
- /api/health responsive
"""
import asyncio
import os
import sys
import time
from pathlib import Path

import pytest
import requests

# Make backend importable
sys.path.insert(0, "/app/backend")

# Load public backend URL
_env_file = Path("/app/frontend/.env")
BASE_URL = None
for line in _env_file.read_text().splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL missing"
API = f"{BASE_URL}/api"


# ---------------------------------------------------------------------------
# Unit: normalize_phone
# ---------------------------------------------------------------------------
class TestNormalizePhone:
    def test_lid_preserved(self):
        from services.bot import normalize_phone
        assert normalize_phone("123456789@lid") == "123456789@lid"

    def test_c_us_stripped(self):
        from services.bot import normalize_phone
        assert normalize_phone("5511987654321@c.us") == "5511987654321"

    def test_plain_phone_unchanged(self):
        from services.bot import normalize_phone
        assert normalize_phone("5511987654321") == "5511987654321"

    def test_empty_returns_empty(self):
        from services.bot import normalize_phone
        assert normalize_phone("") == ""
        assert normalize_phone(None) == ""

    def test_plain_with_symbols_only_digits(self):
        from services.bot import normalize_phone
        assert normalize_phone("+55 (11) 98765-4321") == "5511987654321"


# ---------------------------------------------------------------------------
# Unit: _recent_messages global exists as dict
# ---------------------------------------------------------------------------
class TestRecentMessagesGlobal:
    def test_module_has_recent_messages_dict(self):
        from services import bot
        assert hasattr(bot, "_recent_messages"), "_recent_messages missing"
        assert isinstance(bot._recent_messages, dict), "_recent_messages must be dict"


# ---------------------------------------------------------------------------
# Unit: process_incoming_message dedup logic (direct import, no HTTP)
# ---------------------------------------------------------------------------
class TestProcessIncomingDedup:
    """Invoke process_incoming_message directly (async) and verify dedup skips
    the second identical call. We disable templates to short-circuit before
    any external call (painel.fun)."""

    def _run(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro) if False else asyncio.run(coro)

    def test_identical_within_30s_deduped(self, monkeypatch):
        from services import bot

        # Clear the dedup cache
        bot._recent_messages.clear()

        save_calls = []

        async def fake_save_message(phone, message, direction, customer_id=None):
            save_calls.append((phone, message, direction))

        async def fake_find_or_create_customer(phone, name=None):
            return {"id": "cust_test", "name": name or phone, "whatsapp": phone, "system_type": "unknown"}

        async def fake_log_activity(*a, **k):
            pass

        # Force "no templates loaded" path so it returns early after save_message
        import aiosqlite
        monkeypatch.setattr(bot, "save_message", fake_save_message)
        monkeypatch.setattr(bot, "find_or_create_customer", fake_find_or_create_customer)
        monkeypatch.setattr(bot, "log_activity", fake_log_activity)

        # Also monkey-patch DB access for templates: patch aiosqlite.connect so
        # the templates query returns [].  Easier: patch the templates query by
        # patching connect to a context manager returning empty rows.
        class _FakeCursor:
            async def fetchall(self):
                return []
            async def fetchone(self):
                return None

        class _FakeDB:
            row_factory = None
            async def execute(self, *a, **k):
                return _FakeCursor()
            async def commit(self):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False

        def fake_connect(*a, **k):
            return _FakeDB()

        monkeypatch.setattr(bot.aiosqlite, "connect", fake_connect)

        async def run_twice():
            await bot.process_incoming_message("5511999@c.us", "p2p ok", from_me=False)
            await bot.process_incoming_message("5511999@c.us", "p2p ok", from_me=False)

        asyncio.run(run_twice())

        # First call goes through save_message once; second is deduped BEFORE save_message
        in_saves = [c for c in save_calls if c[2] == "in"]
        assert len(in_saves) == 1, f"expected 1 save, got {len(in_saves)}: {save_calls}"

    def test_distinct_bodies_both_processed(self, monkeypatch):
        from services import bot
        bot._recent_messages.clear()

        save_calls = []

        async def fake_save_message(phone, message, direction, customer_id=None):
            save_calls.append((phone, message, direction))

        async def fake_find_or_create_customer(phone, name=None):
            return {"id": "cust_test", "name": name or phone, "whatsapp": phone, "system_type": "unknown"}

        async def fake_log_activity(*a, **k):
            pass

        class _FakeCursor:
            async def fetchall(self):
                return []
            async def fetchone(self):
                return None

        class _FakeDB:
            row_factory = None
            async def execute(self, *a, **k):
                return _FakeCursor()
            async def commit(self):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(bot, "save_message", fake_save_message)
        monkeypatch.setattr(bot, "find_or_create_customer", fake_find_or_create_customer)
        monkeypatch.setattr(bot, "log_activity", fake_log_activity)
        monkeypatch.setattr(bot.aiosqlite, "connect", lambda *a, **k: _FakeDB())

        async def run():
            await bot.process_incoming_message("5511999@c.us", "p2p ok", from_me=False)
            await bot.process_incoming_message("5511999@c.us", "iptv ok", from_me=False)

        asyncio.run(run())

        in_saves = [c for c in save_calls if c[2] == "in"]
        assert len(in_saves) == 2, f"distinct bodies should both process. got: {save_calls}"

    def test_dedup_expires_after_30s(self, monkeypatch):
        """Simulate expiry by manually aging the timestamp."""
        from services import bot
        bot._recent_messages.clear()

        save_calls = []

        async def fake_save_message(phone, message, direction, customer_id=None):
            save_calls.append((phone, message, direction))

        async def fake_find_or_create_customer(phone, name=None):
            return {"id": "cust_test", "name": phone, "whatsapp": phone, "system_type": "unknown"}

        async def fake_log_activity(*a, **k):
            pass

        class _FakeCursor:
            async def fetchall(self): return []
            async def fetchone(self): return None

        class _FakeDB:
            row_factory = None
            async def execute(self, *a, **k): return _FakeCursor()
            async def commit(self): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

        monkeypatch.setattr(bot, "save_message", fake_save_message)
        monkeypatch.setattr(bot, "find_or_create_customer", fake_find_or_create_customer)
        monkeypatch.setattr(bot, "log_activity", fake_log_activity)
        monkeypatch.setattr(bot.aiosqlite, "connect", lambda *a, **k: _FakeDB())

        async def run():
            await bot.process_incoming_message("5511999@c.us", "p2p ok", from_me=False)
            # Age all entries in dedup cache by 60s
            for k in list(bot._recent_messages.keys()):
                bot._recent_messages[k] -= 60
            await bot.process_incoming_message("5511999@c.us", "p2p ok", from_me=False)

        asyncio.run(run())
        in_saves = [c for c in save_calls if c[2] == "in"]
        assert len(in_saves) == 2, f"after TTL expiry both should process. got: {save_calls}"


# ---------------------------------------------------------------------------
# Integration: /api/health + /api/whatsapp/incoming HTTP
# ---------------------------------------------------------------------------
class TestHealthAndIncoming:
    def test_health(self):
        r = requests.get(f"{API}/health", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "healthy" or data.get("ok") is True or "status" in data

    def test_incoming_returns_ok(self):
        # Endpoint is a fire-and-forget: always 200 OK
        payload = {
            "phone": "5511900000001@c.us",
            "message": "hello unit-test dedup",
            "from_me": False,
            "name": "PyTest",
        }
        r = requests.post(f"{API}/whatsapp/incoming", json=payload, timeout=10)
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_incoming_double_fire_same_body(self):
        """Post the same payload twice quickly. Both should return 200 OK
        (endpoint always accepts) — dedup happens inside the async task."""
        payload = {
            "phone": "5511900000002@c.us",
            "message": f"dedup-http-{int(time.time())}",
            "from_me": False,
        }
        r1 = requests.post(f"{API}/whatsapp/incoming", json=payload, timeout=10)
        r2 = requests.post(f"{API}/whatsapp/incoming", json=payload, timeout=10)
        assert r1.status_code == 200 and r2.status_code == 200
        # Give async task time to run
        time.sleep(2)

    def test_incoming_distinct_bodies(self):
        base = int(time.time())
        p1 = {"phone": "5511900000003@c.us", "message": f"a-{base}", "from_me": False}
        p2 = {"phone": "5511900000003@c.us", "message": f"b-{base}", "from_me": False}
        r1 = requests.post(f"{API}/whatsapp/incoming", json=p1, timeout=10)
        r2 = requests.post(f"{API}/whatsapp/incoming", json=p2, timeout=10)
        assert r1.status_code == 200 and r2.status_code == 200
