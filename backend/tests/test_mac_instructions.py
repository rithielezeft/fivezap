"""Tests for MAC-instruction helpers in bot.py.

DreamTV (IPTV flow) → MAC appears in the CORNER of the DreamTV app screen.
Hybrid / MAG / Formuler → MAC in the Settings/Info menu.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.bot import _mac_where_to_find, _mac_format_help


def test_where_to_find_iptv_mentions_corner_of_screen():
    msg = _mac_where_to_find("iptv")
    lower = msg.lower()
    assert "dreamtv" in lower
    assert "canto da tela" in lower
    # Must NOT push the MAG/Formuler settings-menu path for DreamTV
    assert "info do sistema" not in lower


def test_where_to_find_iptv_case_insensitive():
    assert "canto da tela" in _mac_where_to_find("IPTV").lower()
    assert "canto da tela" in _mac_where_to_find("Iptv").lower()


def test_where_to_find_hybrid_uses_settings_menu():
    msg = _mac_where_to_find("hybrid")
    lower = msg.lower()
    assert "mag/formuler" in lower
    assert "info do sistema" in lower
    # Must NOT push the DreamTV corner hint for Hybrid
    assert "canto da tela" not in lower


def test_where_to_find_none_defaults_to_hybrid_hint():
    """When system_type is missing/None, default to the safer MAG/Formuler
    instruction (Hybrid). Never default to the DreamTV corner hint."""
    msg = _mac_where_to_find(None)
    assert "canto da tela" not in msg.lower()
    assert "menu" in msg.lower()


def test_format_help_iptv_includes_dreamtv_hint():
    help_text = _mac_format_help("iptv")
    assert "AA:BB:CC:DD:EE:FF" in help_text
    assert "canto da tela" in help_text.lower()


def test_format_help_hybrid_includes_settings_hint():
    help_text = _mac_format_help("hybrid")
    assert "AA:BB:CC:DD:EE:FF" in help_text
    assert "info do sistema" in help_text.lower()
    assert "canto da tela" not in help_text.lower()
