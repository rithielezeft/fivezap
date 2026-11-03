"""Tests for InfinitePay integration."""
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.infinitepay import _sanitize_handle, build_direct_url  # noqa: E402


def test_sanitize_handle_strips_dollar():
    assert _sanitize_handle("$rithiele") == "rithiele"
    assert _sanitize_handle("  $rithiele  ") == "rithiele"


def test_sanitize_handle_plain():
    assert _sanitize_handle("rithiele") == "rithiele"
    assert _sanitize_handle("zeferius-solutions") == "zeferius-solutions"


def test_sanitize_handle_empty():
    assert _sanitize_handle("") == ""
    assert _sanitize_handle("   ") == ""
    assert _sanitize_handle(None or "") == ""


def test_build_direct_url_structure():
    url = build_direct_url(
        handle="rithiele",
        amount_cents=3500,
        description="Renovação IPTV",
    )
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "checkout.infinitepay.io"
    assert parsed.path == "/rithiele"

    qs = parse_qs(parsed.query)
    import json
    items = json.loads(qs["items"][0])
    assert items[0]["price"] == 3500
    assert items[0]["quantity"] == 1
    assert items[0]["description"] == "Renovação IPTV"


def test_build_direct_url_sanitizes_handle():
    url = build_direct_url(handle="$rithiele", amount_cents=100, description="teste")
    assert "checkout.infinitepay.io/rithiele?" in url
    assert "$" not in urlparse(url).path


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
