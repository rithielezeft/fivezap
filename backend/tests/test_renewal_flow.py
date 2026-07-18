"""Tests for the renewal flow: correct endpoint + webhook + manual reprocess."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


class FakeResp:
    def __init__(self, status=200, json_data=None, text=""):
        self.status_code = status
        self._json = json_data if json_data is not None else {"ok": True}
        self.text = text or "{}"

    def json(self):
        return self._json


# ---------------- Renew endpoint URL/body ----------------

def test_renew_user_hits_correct_endpoint_and_body():
    """POST /api/users/{painel_id}/renew with {package_id: X} — no user_id in body."""
    captured = {}

    def fake_post(url, json=None, headers=None, **kwargs):
        captured["url"] = url
        captured["payload"] = json
        return FakeResp(200, {"expires_at": "2026-12-01"})

    async def go():
        from services import painel
        with patch.object(painel, "login", new=AsyncMock(return_value="tok")), \
             patch.object(painel, "get_setting",
                          side_effect=lambda k: {"painel_base_url": "https://api.controle.fit"}.get(k, "")), \
             patch("services.painel.cffi_requests.post", side_effect=fake_post):
            return await painel.renew_user("228059624", 42)

    result = _run(go())
    assert captured["url"] == "https://api.controle.fit/api/users/228059624/renew"
    assert captured["payload"] == {"package_id": 42}
    assert result["expires_at"] == "2026-12-01"


# ---------------- Package ID mapping ----------------

def test_package_ids_match_business_rules():
    """
    P2P + Hybrid: 1m=17, 3m=42, 6m=55, 12m=57
    IPTV DreamTV: 1m=17, 3m=43, 6m=56, 12m=58
    """
    from services.painel import get_package_id
    # P2P
    assert get_package_id("p2p", 1) == 17
    assert get_package_id("p2p", 3) == 42
    assert get_package_id("p2p", 6) == 55
    assert get_package_id("p2p", 12) == 57
    # Hybrid — same as P2P
    assert get_package_id("hybrid", 3) == 42
    assert get_package_id("hybrid", 6) == 55
    assert get_package_id("hybrid", 12) == 57
    # IPTV (DreamTV) — different from 3m onward
    assert get_package_id("iptv", 1) == 17
    assert get_package_id("iptv", 3) == 43
    assert get_package_id("iptv", 6) == 56
    assert get_package_id("iptv", 12) == 58


# ---------------- order_nsu → painel_id extraction ----------------

def test_extract_painel_id_from_order_nsu():
    from routers.payments import _extract_painel_id_from_nsu
    # New format from create_payment (renew flow)
    assert _extract_painel_id_from_nsu("renew-228059624-3m") == "228059624"
    # New format from trial creation
    assert _extract_painel_id_from_nsu("trial-227453827-12m") == "227453827"
    # Empty / malformed
    assert _extract_painel_id_from_nsu("") == ""
    assert _extract_painel_id_from_nsu("nodash") == ""


def test_extract_painel_id_ignores_legacy_ord_format():
    """Legacy 'ord-abc12345' format has no painel_id — must fall back to DB lookup."""
    from routers.payments import _extract_painel_id_from_nsu
    # We DO return the second segment ("abc12345") but that isn't a digit,
    # so the webhook won't use it and will fall back to trials table lookup.
    val = _extract_painel_id_from_nsu("ord-abc12345")
    assert not val.isdigit(), \
        "Legacy 'ord-XXX' must not accidentally be treated as a painel_id"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
