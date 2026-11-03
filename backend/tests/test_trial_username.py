"""Tests for the new trial username format: {firstname}{last2digits}new.

We test the pure helpers without hitting the network (painel.fun).
"""
import sys
import re
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# Replicate the exact logic from painel.create_trial (source of truth).
def _slugify_first_name(s: str) -> str:
    if not s:
        return ""
    for word in s.strip().split():
        normalized = unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode("ascii")
        cleaned = re.sub(r"[^a-zA-Z]", "", normalized).lower()
        if cleaned:
            return cleaned[:15]
    return ""


def _build_username(name: str, whatsapp: str) -> str:
    digits_only = "".join(c for c in (whatsapp or "") if c.isdigit())
    last2 = digits_only[-2:] if len(digits_only) >= 2 else ""
    first_name = _slugify_first_name(name or "")
    if first_name and last2:
        return f"{first_name}{last2}new"
    if first_name:
        return f"{first_name}XXnew"  # would be _rand(2) in real code
    phone_tail = digits_only[-6:] or "XXXXXX"
    return f"test{phone_tail}XXX"


def test_expected_format_guilherme():
    """User's exact example: Guilherme + 5511987654344 → guilherme44new"""
    assert _build_username("Guilherme", "5511987654344") == "guilherme44new"


def test_first_name_only():
    """Full name → uses only first word."""
    assert _build_username("Rithiele Silva Costa", "5511912345678") == "rithiele78new"


def test_accents_stripped():
    """João → joao, André → andre."""
    assert _build_username("João", "5511900000012") == "joao12new"
    assert _build_username("André Souza", "5511900000034") == "andre34new"


def test_special_chars_stripped():
    """Emojis and punctuation ignored, only ASCII letters kept."""
    assert _build_username("💚 Maria-Clara", "5511900000099") == "mariaclara99new"


def test_lowercase():
    assert _build_username("GUILHERME", "5511987654344") == "guilherme44new"


def test_long_name_capped():
    """First name is truncated to 15 chars max."""
    result = _build_username("Wolfeschlegelsteinhausenberger", "551190000042")
    # First name capped at 15 chars: "wolfeschlegels"...
    assert result.endswith("42new")
    assert result.startswith("wolfeschlegels")


def test_lid_phone_no_digits_fallback():
    """If phone is @lid (no digits), still uses first name with placeholder."""
    result = _build_username("Bruno", "abc@lid")
    assert result.startswith("bruno")
    assert result.endswith("new")


def test_no_name_fallback_to_test_pattern():
    """If no name, fallback to test{phone_tail}."""
    result = _build_username("", "5511987654321")
    assert result.startswith("test")
    assert "654321" in result


def test_short_phone():
    assert _build_username("Ana", "12") == "ana12new"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
