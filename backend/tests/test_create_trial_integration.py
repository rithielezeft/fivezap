"""Integration-level tests for painel.create_trial with mocked HTTP + login.

pytest-asyncio isn't installed in this env, so we wrap the async coros with asyncio.run.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import painel  # noqa: E402


class FakeResp:
    def __init__(self, status=200, json_data=None, text=""):
        self.status_code = status
        self._json = json_data if json_data is not None else {"id": 12345}
        self.text = text or "{}"

    def json(self):
        return self._json


async def _fake_get_setting(key):
    return {
        "painel_base_url": "https://api.controle.fit",
        "trial_package_id": "61",
        "painel_username": "reseller_test",
    }.get(key, "")


def _run(coro):
    return asyncio.run(coro)


# ---------------- Username payload verification ----------------

def test_username_guilherme_format():
    """Guilherme + 5511987654344 → guilherme44new."""
    captured = {}

    def fake_post(url, json=None, headers=None, **kwargs):
        captured["payload"] = json
        return FakeResp(200, {"id": 42, "username": json.get("username")})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="fake_token")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch.object(painel, "resync_user", new=AsyncMock(return_value={"ok": True})), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            return await painel.create_trial(
                system_type="iptv", name="Guilherme", whatsapp="5511987654344"
            )

    result = _run(go())
    assert captured["payload"]["username"] == "guilherme44new"
    assert result["id"] == 42


def test_username_joao_da_silva():
    captured = {}

    def fake_post(url, json=None, headers=None, **kwargs):
        captured["payload"] = json
        return FakeResp(200, {"id": 1})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch.object(painel, "resync_user", new=AsyncMock()), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.create_trial(
                system_type="iptv", name="João da Silva", whatsapp="5511912345678"
            )

    _run(go())
    assert captured["payload"]["username"] == "joao78new"


def test_username_with_emoji_prefix():
    captured = {}

    def fake_post(url, json=None, headers=None, **kwargs):
        captured["payload"] = json
        return FakeResp(200, {"id": 1})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch.object(painel, "resync_user", new=AsyncMock()), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.create_trial(
                system_type="iptv", name="💚 Maria", whatsapp="5511900000099"
            )

    _run(go())
    assert captured["payload"]["username"] == "maria99new"


def test_username_fallback_empty_name():
    captured = {}

    def fake_post(url, json=None, headers=None, **kwargs):
        captured["payload"] = json
        return FakeResp(200, {"id": 1})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch.object(painel, "resync_user", new=AsyncMock()), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.create_trial(
                system_type="iptv", name="", whatsapp="5511987654321"
            )

    _run(go())
    assert captured["payload"]["username"].startswith("test")


# ---------------- Resync call verification ----------------

def test_resync_called_for_p2p():
    resync_mock = AsyncMock(return_value={"ok": True})

    def fake_post(url, json=None, headers=None, **kwargs):
        return FakeResp(200, {"id": 777, "username": json["username"]})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch.object(painel, "resync_user", new=resync_mock), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.create_trial(
                system_type="p2p", name="Guilherme", whatsapp="5511987654344"
            )

    _run(go())
    resync_mock.assert_awaited_once()
    assert resync_mock.await_args.args[0] == "777"


def test_resync_called_for_hybrid():
    resync_mock = AsyncMock(return_value={"ok": True})

    def fake_post(url, json=None, headers=None, **kwargs):
        return FakeResp(200, {"id": 888})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch.object(painel, "resync_user", new=resync_mock), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.create_trial(
                system_type="hybrid", name="Ana", whatsapp="551190000012",
                mac="AA:BB:CC:DD:EE:FF",
            )

    _run(go())
    resync_mock.assert_awaited_once()
    assert resync_mock.await_args.args[0] == "888"


def test_resync_NOT_called_for_iptv():
    resync_mock = AsyncMock(return_value={"ok": True})

    def fake_post(url, json=None, headers=None, **kwargs):
        return FakeResp(200, {"id": 999})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch.object(painel, "resync_user", new=resync_mock), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.create_trial(
                system_type="iptv", name="Ana", whatsapp="551190000012",
                mac="AA:BB:CC:DD:EE:FF",
            )

    _run(go())
    resync_mock.assert_not_awaited()


def test_resync_failure_is_non_fatal():
    """If resync throws, create_trial still returns a successful result."""
    resync_mock = AsyncMock(side_effect=RuntimeError("resync boom"))

    def fake_post(url, json=None, headers=None, **kwargs):
        return FakeResp(200, {"id": 555, "username": json["username"]})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch.object(painel, "resync_user", new=resync_mock), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            return await painel.create_trial(
                system_type="p2p", name="Bruno", whatsapp="5511900000021"
            )

    result = _run(go())
    assert result["id"] == 555
    resync_mock.assert_awaited_once()


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
