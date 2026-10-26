"""Tests for the two P0 fixes:

1) create_trial must send `system` as int (1=IPTV, 2=P2P, 3=Hybrid).
2) resync_user must call the exact painel.fun endpoints:
     /api/users/{id}/resync_p2p   for P2P
     /api/users/{id}/resync_hybrid for Hybrid
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
        self._json = json_data if json_data is not None else {"id": 1}
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


# ---------------- system int mapping ----------------

def _capture_payload_for(system_type: str, mac=None):
    captured = {}

    def fake_post(url, json=None, headers=None, **kwargs):
        # Only capture the initial /api/trial_users payload (not change_system/dreamtv)
        if "trial_users" in url and "payload" not in captured:
            captured["url"] = url
            captured["payload"] = json
        return FakeResp(200, {"id": 10, "username": (json or {}).get("username")})

    def fake_get(url, params=None, **kwargs):
        return FakeResp(200, {"valid": True})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch.object(painel, "resync_user", new=AsyncMock(return_value={"ok": True})), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post), \
             patch("services.painel.cffi_requests.get", side_effect=fake_get):
            await painel.create_trial(
                system_type=system_type, name="Guilherme",
                whatsapp="5511987654344", mac=mac,
            )

    _run(go())
    return captured


def test_iptv_sends_system_1():
    cap = _capture_payload_for("iptv", mac="AA:BB:CC:DD:EE:FF")
    assert cap["payload"]["system"] == 1
    assert cap["payload"]["system_type"] == "iptv"


def test_p2p_sends_system_2():
    cap = _capture_payload_for("p2p")
    assert cap["payload"]["system"] == 2
    assert cap["payload"]["system_type"] == "p2p"


def test_hybrid_sends_system_3():
    cap = _capture_payload_for("hybrid", mac="AA:BB:CC:DD:EE:FF")
    assert cap["payload"]["system"] == 3
    assert cap["payload"]["system_type"] == "hybrid"


def test_system_case_insensitive():
    cap = _capture_payload_for("P2P")
    assert cap["payload"]["system"] == 2


# ---------------- resync_user exact endpoints ----------------

def test_resync_p2p_hits_exact_endpoint():
    captured = {}

    def fake_post(url, headers=None, **kwargs):
        captured["url"] = url
        return FakeResp(200, {"ok": True})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.resync_user("777", system_type="p2p")

    _run(go())
    assert captured["url"] == "https://api.controle.fit/api/users/777/resync_p2p"


def test_resync_hybrid_hits_exact_endpoint():
    captured = {}

    def fake_post(url, headers=None, **kwargs):
        captured["url"] = url
        return FakeResp(200, {"ok": True})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.resync_user("888", system_type="hybrid")

    _run(go())
    assert captured["url"] == "https://api.controle.fit/api/users/888/resync_hybrid"


def test_resync_defaults_to_p2p_when_system_missing():
    captured = {}

    def fake_post(url, headers=None, **kwargs):
        captured["url"] = url
        return FakeResp(200, {"ok": True})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.resync_user("999")

    _run(go())
    assert captured["url"].endswith("/api/users/999/resync_p2p")


def test_resync_raises_on_error_status():
    def fake_post(url, headers=None, **kwargs):
        return FakeResp(500, {}, text="server error")

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.resync_user("111", system_type="p2p")

    import pytest
    with pytest.raises(RuntimeError):
        _run(go())


# ---------------- End-to-end: create_trial p2p triggers resync_p2p endpoint ----------------

def test_create_trial_p2p_full_chain_calls_resync_p2p():
    """Full chain: no resync_user mock — verify the real endpoint is hit."""
    calls = []

    def fake_post(url, json=None, headers=None, **kwargs):
        calls.append(url)
        if "trial_users" in url:
            return FakeResp(200, {"id": 555, "username": json.get("username")})
        # resync call
        return FakeResp(200, {"ok": True})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.create_trial(
                system_type="p2p", name="Ana", whatsapp="551199999912"
            )

    _run(go())
    assert any(u.endswith("/api/users/555/resync_p2p") for u in calls), calls


def test_create_trial_hybrid_full_chain_calls_resync_hybrid():
    calls = []

    def fake_post(url, json=None, headers=None, **kwargs):
        calls.append(url)
        if "trial_users" in url:
            return FakeResp(200, {"id": 666, "username": json.get("username")})
        return FakeResp(200, {"ok": True})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.create_trial(
                system_type="hybrid", name="Bruno", whatsapp="551199999934",
                mac="AA:BB:CC:DD:EE:FF",
            )

    _run(go())
    assert any(u.endswith("/api/users/666/resync_hybrid") for u in calls), calls


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
