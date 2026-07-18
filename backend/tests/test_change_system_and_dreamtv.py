"""Tests for the new painel.fun flow:

- change_system(user_id, system_id) — 2=P2P, 3=Hybrid
- validate_mac_dreamtv(mac) — checks api.dreamtv.life
- create_dreamtv_playlist(user_id, mac) — activates DreamTV for user+MAC
- create_trial end-to-end for P2P (calls change_system), Hybrid+MAC (change_system +
  validate + dreamtv/playlist), IPTV+MAC (validate + dreamtv/playlist).
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
        self._json = json_data if json_data is not None else {"ok": True}
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


# ---------------- change_system ----------------

def test_change_system_p2p_hits_correct_endpoint():
    captured = {}

    def fake_post(url, json=None, headers=None, **kwargs):
        captured["url"] = url
        captured["payload"] = json
        return FakeResp(200, {"ok": True})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.change_system("228124762", 2)

    _run(go())
    assert captured["url"] == "https://api.controle.fit/api/users/228124762/change_system"
    assert captured["payload"] == {"system_id": 2}


def test_change_system_hybrid_sends_system_id_3():
    captured = {}

    def fake_post(url, json=None, headers=None, **kwargs):
        captured["payload"] = json
        return FakeResp(200)

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.change_system("228124764", 3)

    _run(go())
    assert captured["payload"]["system_id"] == 3


def test_change_system_raises_on_error():
    def fake_post(url, json=None, headers=None, **kwargs):
        return FakeResp(500, text="boom")

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.change_system("1", 2)

    import pytest
    with pytest.raises(RuntimeError):
        _run(go())


# ---------------- validate_mac_dreamtv ----------------

def test_validate_mac_dreamtv_success_valid_true():
    def fake_get(url, params=None, **kwargs):
        assert url == "https://api.dreamtv.life/api/validate_mac"
        assert params == {"mac": "AA:BB:CC:DD:EE:FF"}
        return FakeResp(200, {"valid": True})

    async def go():
        with patch("services.painel.cffi_requests.get", side_effect=fake_get):
            return await painel.validate_mac_dreamtv("AA:BB:CC:DD:EE:FF")

    assert _run(go()) is True


def test_validate_mac_dreamtv_returns_false_on_400():
    def fake_get(url, params=None, **kwargs):
        return FakeResp(400, text="invalid mac")

    async def go():
        with patch("services.painel.cffi_requests.get", side_effect=fake_get):
            return await painel.validate_mac_dreamtv("00:00:00:00:00:00")

    assert _run(go()) is False


def test_validate_mac_dreamtv_returns_false_on_exception():
    def fake_get(url, params=None, **kwargs):
        raise ConnectionError("dreamtv down")

    async def go():
        with patch("services.painel.cffi_requests.get", side_effect=fake_get):
            return await painel.validate_mac_dreamtv("AA:BB:CC:DD:EE:FF")

    assert _run(go()) is False


def test_validate_mac_dreamtv_empty_mac_false():
    async def go():
        return await painel.validate_mac_dreamtv("")

    assert _run(go()) is False


# ---------------- create_dreamtv_playlist ----------------

def test_create_dreamtv_playlist_hits_correct_endpoint():
    captured = {}

    def fake_post(url, json=None, headers=None, **kwargs):
        captured["url"] = url
        captured["payload"] = json
        return FakeResp(200, {"ok": True})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            await painel.create_dreamtv_playlist("228124751", "D8:A3:5C:56:86:56")

    _run(go())
    assert captured["url"] == "https://api.controle.fit/api/users/228124751/dreamtv/playlist"
    assert captured["payload"]["macaddr"] == "D8:A3:5C:56:86:56"


# ---------------- create_trial end-to-end ----------------

def test_create_trial_p2p_calls_change_system_2_and_resync_p2p():
    """P2P trial: POST /trial_users → POST /change_system {2} → POST /resync_p2p."""
    calls = []

    def fake_post(url, json=None, headers=None, **kwargs):
        calls.append({"url": url, "payload": json})
        if "trial_users" in url:
            return FakeResp(200, {"id": 111, "username": (json or {}).get("username")})
        return FakeResp(200, {"ok": True})

    def fake_get(url, params=None, **kwargs):
        return FakeResp(200, {"valid": True})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post), \
             patch("services.painel.cffi_requests.get", side_effect=fake_get):
            await painel.create_trial(
                system_type="p2p", name="Ana", whatsapp="551190000012"
            )

    _run(go())
    urls = [c["url"] for c in calls]

    # 1) trial_users creation
    assert any(u.endswith("/api/trial_users") for u in urls)
    # 2) change_system with system_id=2
    change_calls = [c for c in calls if c["url"].endswith("/change_system")]
    assert len(change_calls) == 1
    assert change_calls[0]["payload"] == {"system_id": 2}
    assert change_calls[0]["url"] == "https://api.controle.fit/api/users/111/change_system"
    # 3) resync_p2p (exact endpoint)
    assert any(u.endswith("/api/users/111/resync_p2p") for u in urls)


def test_create_trial_hybrid_full_flow():
    """Hybrid + MAC: trial_users → change_system{3} → resync_hybrid.

    Hybrid does NOT call DreamTV validate/playlist — that's IPTV-only.
    The macaddr is already sent in the initial trial_users payload.
    """
    calls = []

    def fake_post(url, json=None, headers=None, **kwargs):
        calls.append({"url": url, "payload": json})
        if "trial_users" in url:
            return FakeResp(200, {"id": 222, "username": (json or {}).get("username")})
        return FakeResp(200, {"ok": True})

    dreamtv_called = {"flag": False}

    def fake_get(url, params=None, **kwargs):
        dreamtv_called["flag"] = True
        return FakeResp(200, {"valid": True})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post), \
             patch("services.painel.cffi_requests.get", side_effect=fake_get):
            await painel.create_trial(
                system_type="hybrid", name="Bruno", whatsapp="551190000023",
                mac="55:F0:DC:50:5C:2C",
            )

    _run(go())
    urls = [c["url"] for c in calls]

    # change_system {3}
    cs = [c for c in calls if c["url"].endswith("/change_system")]
    assert len(cs) == 1
    assert cs[0]["payload"] == {"system_id": 3}
    # NO dreamtv/playlist for hybrid
    assert not any(u.endswith("/dreamtv/playlist") for u in urls)
    # NO dreamtv validate_mac for hybrid
    assert dreamtv_called["flag"] is False
    # macaddr must be in the initial trial_users payload
    trial_call = next(c for c in calls if c["url"].endswith("/trial_users"))
    assert trial_call["payload"].get("macaddr") == "55:F0:DC:50:5C:2C"
    # resync_hybrid
    assert any(u.endswith("/api/users/222/resync_hybrid") for u in urls)


def test_create_trial_iptv_with_mac_calls_dreamtv_but_not_change_system():
    calls = []

    def fake_post(url, json=None, headers=None, **kwargs):
        calls.append({"url": url, "payload": json})
        if "trial_users" in url:
            return FakeResp(200, {"id": 333, "username": (json or {}).get("username")})
        return FakeResp(200, {"ok": True})

    def fake_get(url, params=None, **kwargs):
        return FakeResp(200, {"valid": True})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post), \
             patch("services.painel.cffi_requests.get", side_effect=fake_get):
            await painel.create_trial(
                system_type="iptv", name="Carla", whatsapp="551190000045",
                mac="D8:A3:5C:56:86:56",
            )

    _run(go())
    urls = [c["url"] for c in calls]

    # No change_system (IPTV is default)
    assert not any(u.endswith("/change_system") for u in urls)
    # dreamtv/playlist called
    assert any(u.endswith("/dreamtv/playlist") for u in urls)
    # No resync for IPTV
    assert not any("resync" in u for u in urls)


def test_create_trial_hybrid_fails_when_mac_invalid_on_dreamtv():
    """Hybrid should NOT call DreamTV — so even with 'invalid' MAC, trial succeeds
    (change_system happens, macaddr is stored on the user, and resync completes).
    """
    def fake_post(url, json=None, headers=None, **kwargs):
        if "trial_users" in url:
            return FakeResp(200, {"id": 444, "username": (json or {}).get("username")})
        return FakeResp(200, {"ok": True})

    dreamtv_called = {"flag": False}

    def fake_get(url, params=None, **kwargs):
        dreamtv_called["flag"] = True
        return FakeResp(200, {"valid": False})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post), \
             patch("services.painel.cffi_requests.get", side_effect=fake_get):
            return await painel.create_trial(
                system_type="hybrid", name="Dan", whatsapp="551190000067",
                mac="00:00:00:00:00:00",
            )

    result = _run(go())
    assert result["id"] == 444
    # DreamTV must NOT be consulted for hybrid
    assert dreamtv_called["flag"] is False


def test_create_trial_iptv_fails_when_mac_invalid_on_dreamtv():
    """IPTV+MAC (DreamTV) must fail if MAC is rejected by dreamtv.life."""
    def fake_post(url, json=None, headers=None, **kwargs):
        if "trial_users" in url:
            return FakeResp(200, {"id": 555, "username": (json or {}).get("username")})
        return FakeResp(200, {"ok": True})

    def fake_get(url, params=None, **kwargs):
        return FakeResp(200, {"valid": False})

    async def go():
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting", side_effect=_fake_get_setting), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post), \
             patch("services.painel.cffi_requests.get", side_effect=fake_get):
            await painel.create_trial(
                system_type="iptv", name="Eve", whatsapp="551190000089",
                mac="00:00:00:00:00:00",
            )

    import pytest
    with pytest.raises(RuntimeError, match=r"DreamTV"):
        _run(go())


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
