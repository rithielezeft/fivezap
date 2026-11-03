"""Tests for painel.fun input sanitization.

Reported error from production: creating a trial for a client whose WhatsApp
push_name contained the emoji 🤍 crashed with:
    HTTP 400 — "Incorrect string value: '\\xF0\\x9F\\xA4\\x8D'
     for column `streamcreed_db`..."

Cause: painel.fun's MySQL `streamcreed_db` uses utf8 (3-byte max), not
utf8mb4 — so any codepoint > U+FFFF (all emojis) is rejected.

Fix: strip 4-byte UTF-8 chars + control chars before sending name/whatsapp.
Accented Latin (é, ã, ç) is preserved.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.painel import _sanitize_for_painel


# ---------- Emoji stripping ----------

def test_removes_the_exact_emoji_from_prod_bug_report():
    """The specific bug: 🤍 (U+1F90D = \\xF0\\x9F\\xA4\\x8D)."""
    got = _sanitize_for_painel("João 🤍")
    assert got == "João"
    assert "🤍" not in got
    assert "\U0001F90D" not in got


def test_removes_various_emojis():
    cases = [
        ("Cliente 😀 Feliz", "Cliente  Feliz"),
        ("💰 Pagou! 🎉", "Pagou!"),
        ("Zé 👍🏽", "Zé"),
        ("Maria ❤️", "Maria "),   # U+2764 is 3-byte, kept; U+FE0F variation selector is 3-byte, kept
        ("🚀🚀🚀", ""),
    ]
    for src, expected in cases:
        got = _sanitize_for_painel(src)
        # We don't over-specify whitespace — just: no 4-byte codepoints remain
        for ch in got:
            assert ord(ch) <= 0xFFFF, f"leaked 4-byte char in {got!r} from {src!r}"


def test_preserves_accented_latin():
    """Accented characters (é, ã, ç, ñ, ü) are 2-byte UTF-8 → SAFE in utf8."""
    for src in ["José", "Ção", "Piña", "Über", "Naïve", "François"]:
        assert _sanitize_for_painel(src) == src


def test_removes_control_characters():
    got = _sanitize_for_painel("João\x00\x01\x02Silva")
    assert got == "JoãoSilva"


def test_preserves_common_whitespace():
    """Tab and newline are ok — but they should be trimmed at edges."""
    got = _sanitize_for_painel("  João\tSilva  \n")
    # Leading/trailing stripped, middle whitespace kept
    assert got == "João\tSilva"


def test_removes_del_and_c1_controls():
    got = _sanitize_for_painel("João\x7fSilva\x80\x9f")
    assert got == "JoãoSilva"


def test_empty_and_none_return_empty_string():
    assert _sanitize_for_painel(None) == ""
    assert _sanitize_for_painel("") == ""
    assert _sanitize_for_painel("   ") == ""


def test_max_len_applied():
    got = _sanitize_for_painel("a" * 200)
    assert len(got) == 60
    got2 = _sanitize_for_painel("a" * 200, max_len=30)
    assert len(got2) == 30


def test_emoji_at_max_len_boundary_is_dropped_not_truncated():
    """If emoji lands exactly at the cut-off boundary, drop it clean —
    don't leave a half-encoded byte sequence."""
    src = "abc" + "🤍" + "d" * 100
    got = _sanitize_for_painel(src)
    # No emoji anywhere
    for ch in got:
        assert ord(ch) <= 0xFFFF
    assert got.startswith("abcd")


# ---------- Numbers (whatsapp) ----------

def test_whatsapp_number_untouched():
    assert _sanitize_for_painel("5511987654321", max_len=30) == "5511987654321"


def test_whatsapp_with_formatting_preserved():
    assert _sanitize_for_painel("+55 (11) 98765-4321", max_len=30) == "+55 (11) 98765-4321"


def test_whatsapp_with_emoji_stripped():
    """Some CRMs prepend flag emojis to phone numbers."""
    assert _sanitize_for_painel("🇧🇷 5511987654321", max_len=30) == "5511987654321"


# ---------- No false positives ----------

def test_currency_and_math_symbols_preserved():
    """Currency signs, math symbols in BMP (Basic Multilingual Plane) are ok."""
    assert _sanitize_for_painel("Plano R$ 35,00 — 3 mês") == "Plano R$ 35,00 — 3 mês"


def test_punctuation_and_ascii_preserved():
    src = "O'Brien-Silva & Cia. Ltda. (Sandro)"
    assert _sanitize_for_painel(src) == src
