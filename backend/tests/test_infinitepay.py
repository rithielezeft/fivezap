"""Tests for InfinitePay direct URL builder + handle sanitization."""
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.infinitepay import _sanitize_handle, _build_direct_url  # noqa: E402


def test_sanitize_handle_strips_dollar():
    assert _sanitize_handle("$rithiele") == "rithiele"
    assert _sanitize_handle("  $rithiele  ") == "rithiele"


def test_sanitize_handle_plain():
    assert _sanitize_handle("rithiele") == "rithiele"


def test_sanitize_handle_empty():
    assert _sanitize_handle("") == ""
    assert _sanitize_handle("   ") == ""


def test_direct_url_structure():
    url = _build_direct_url(
        handle="rithiele",
        amount_cents=3500,
        description="Renovação IPTV 1 mês",
        order_nsu="ord-abc123",
        redirect_url="https://example.com/thanks",
    )
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "checkout.infinitepay.io"
    assert parsed.path == "/rithiele"

    qs = parse_qs(parsed.query)
    assert qs["order_nsu"] == ["ord-abc123"]
    assert qs["redirect_url"] == ["https://example.com/thanks"]

    # items must be a valid URL-encoded JSON array
    import json
    items_raw = qs["items"][0]
    items = json.loads(items_raw)
    assert len(items) == 1
    assert items[0]["name"] == "Renovação IPTV 1 mês"
    assert items[0]["price"] == 3500
    assert items[0]["quantity"] == 1


def test_direct_url_no_redirect():
    url = _build_direct_url(
        handle="rithiele",
        amount_cents=1000,
        description="Teste",
        order_nsu="ord-1",
        redirect_url="",
    )
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert "redirect_url" not in qs


def test_direct_url_long_description_truncates():
    url = _build_direct_url(
        handle="foo",
        amount_cents=100,
        description="a" * 500,
        order_nsu="o",
        redirect_url="",
    )
    import json
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    items = json.loads(qs["items"][0])
    assert len(items[0]["name"]) <= 100


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
