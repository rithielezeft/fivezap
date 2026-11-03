"""Tests for the system_type inference guard in _run_trial_creation.

Scenario reported by user: production templates had `system_type='iptv'`
but their trigger_command / name said "Hybrid" or "Dream TV" — causing
Hybrid commands to create DreamTV trials and vice-versa.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.bot import _infer_system_type


def test_hybrid_trigger_forces_hybrid_even_when_template_says_iptv():
    """Bug repro: template.system_type='iptv' but trigger='hybrid' → force hybrid."""
    assert _infer_system_type("hybrid", "Teste Hybrid", "iptv") == "hybrid"
    assert _infer_system_type("hybrid new", "New Hybrid", "iptv") == "hybrid"


def test_dream_tv_trigger_stays_iptv():
    """Dream TV command IS IPTV (with MAC). Correct system_type = 'iptv'."""
    assert _infer_system_type("dream tv", "Dream TV", "iptv") == "iptv"
    assert _infer_system_type("dreamtv new", "DreamTV", "iptv") == "iptv"
    assert _infer_system_type("dream tv new", "New Dream TV", "hybrid") == "iptv"


def test_p2p_trigger_forces_p2p():
    assert _infer_system_type("p2p new", "P2P New Braz", "iptv") == "p2p"
    assert _infer_system_type("braz", "New Braz", "hybrid") == "p2p"


def test_hybrid_wins_over_p2p_when_both_words_present():
    """If both 'hybrid' and 'p2p' appear (e.g. 'Hybrid P2P Combined'), prefer hybrid."""
    assert _infer_system_type("hybrid p2p", "Hybrid P2P Combined", "iptv") == "hybrid"


def test_accented_hibrido_also_detected():
    """PT: 'híbrido' should match hybrid."""
    assert _infer_system_type("hibrido", "Teste Híbrido", "iptv") == "hybrid"
    assert _infer_system_type("hibrido novo", "hibrido", "iptv") == "hybrid"


def test_current_valid_type_preserved_when_no_hint():
    """When trigger/name has no keyword, keep the template's declared system_type."""
    assert _infer_system_type("teste", "Teste Genérico", "hybrid") == "hybrid"
    assert _infer_system_type("teste", "Teste Genérico", "p2p") == "p2p"
    assert _infer_system_type("teste", "Teste Genérico", "iptv") == "iptv"


def test_defaults_to_iptv_when_all_unknown():
    assert _infer_system_type("xyz", "abc", "") == "iptv"
    assert _infer_system_type("", "", "unknown_type") == "iptv"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
