"""Unit tests for system_detector."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.system_detector import detect_system_type  # noqa: E402


def test_package_id_iptv_only():
    assert detect_system_type({"package_id": 43}) == "iptv"
    assert detect_system_type({"package_id": 56}) == "iptv"
    assert detect_system_type({"package_id": 58}) == "iptv"


def test_package_id_p2p_hybrid_ambiguous_falls_back_iptv():
    # 42/55/57 are shared between p2p and hybrid — heuristic picks iptv as most common
    assert detect_system_type({"package_id": 42}) == "iptv"


def test_structured_system_type_iptv():
    assert detect_system_type({"system_type": "IPTV Mensal"}) == "iptv"


def test_structured_p2p():
    assert detect_system_type({"package_name": "P2P Trimestral"}) == "p2p"


def test_structured_hybrid():
    assert detect_system_type({"plan": "Hybrid Combo 6m"}) == "hybrid"


def test_dream_keyword_maps_iptv():
    assert detect_system_type({"server": "Dream Player"}) == "iptv"


def test_brazuca_keyword_maps_p2p():
    assert detect_system_type({"product": "Brazuca 12M"}) == "p2p"


def test_notes_iptv():
    assert detect_system_type({"notas": "cliente IPTV, Smarters instalado"}) == "iptv"


def test_notes_p2p():
    assert detect_system_type({"obs": "usa p2p no celular"}) == "p2p"


def test_mac_present_means_iptv():
    assert detect_system_type({"mac": "AA:BB:CC:DD:EE:FF"}) == "iptv"


def test_mac_in_notes_means_iptv():
    assert detect_system_type({"notes": "MAC 00:1A:2B:3C:4D:5E instalado"}) == "iptv"


def test_no_signal_returns_none():
    assert detect_system_type({"username": "joao", "name": "Joao"}) is None


def test_priority_package_id_over_notes():
    u = {"package_id": 43, "notes": "cliente p2p"}  # package wins
    assert detect_system_type(u) == "iptv"


def test_hybrid_priority_over_iptv_in_text():
    u = {"notes": "hybrid iptv combo"}
    assert detect_system_type(u) == "hybrid"


def test_nested_custom_fields():
    u = {"custom_fields": [{"key": "system", "value": "IPTV Premium"}]}
    assert detect_system_type(u) == "iptv"


# --- Real painel.fun payload tests ---

def test_painel_fun_system_1_iptv():
    assert detect_system_type({"system": 1}) == "iptv"


def test_painel_fun_system_2_p2p():
    assert detect_system_type({"system": 2}) == "p2p"


def test_painel_fun_system_3_hybrid():
    assert detect_system_type({"system": 3}) == "hybrid"


def test_painel_fun_real_payload():
    u = {
        "id": 227420601,
        "macaddr": "",
        "username": "rogeriotvv",
        "system": 2,
        "reseller_notes": "+55 (11) 94774-8236",
        "packages": "[40,41,43,63,61,62,47,65,66,74,26,1021]",
    }
    assert detect_system_type(u) == "p2p"


def test_painel_fun_system_priority_over_mac():
    # even with a MAC (would suggest IPTV), system=2 (p2p) wins
    u = {"macaddr": "AA:BB:CC:DD:EE:FF", "system": 2}
    assert detect_system_type(u) == "p2p"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
