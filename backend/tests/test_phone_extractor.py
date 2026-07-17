"""Unit tests for phone_extractor — run with: pytest backend/tests/test_phone_extractor.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.phone_extractor import extract_whatsapp  # noqa: E402


def test_structured_whatsapp():
    assert extract_whatsapp({"whatsapp": "11987654321"}) == "5511987654321"


def test_structured_phone_with_mask():
    assert extract_whatsapp({"phone": "(11) 98765-4321"}) == "5511987654321"


def test_with_country_code():
    assert extract_whatsapp({"whatsapp": "+55 11 98765-4321"}) == "5511987654321"


def test_notes_free_text():
    u = {"notes": "cliente VIP, contato: 11 98765-4321, entrega manha"}
    assert extract_whatsapp(u) == "5511987654321"


def test_notas_portuguese():
    u = {"notas": "WhatsApp: (21) 99887-6655 — indicado pelo Joao"}
    assert extract_whatsapp(u) == "5521998876655"


def test_obs_field():
    u = {"obs": "Zap 55 11 9 8765 4321"}
    assert extract_whatsapp(u) == "5511987654321"


def test_no_number():
    u = {"notes": "sem contato ainda"}
    assert extract_whatsapp(u) is None


def test_nested_custom_fields_list():
    u = {"custom_fields": [{"key": "whatsapp", "value": "11987654321"}]}
    assert extract_whatsapp(u) == "5511987654321"


def test_nested_meta_dict():
    u = {"meta": {"notes": "contato 11 98765-4321"}}
    assert extract_whatsapp(u) == "5511987654321"


def test_priority_structured_over_notes():
    u = {"whatsapp": "11912345678", "notes": "backup 21999998888"}
    assert extract_whatsapp(u) == "5511912345678"


def test_landline_10_digits():
    # (11) 3456-7890 — landline without the extra 9
    u = {"notes": "fixo (11) 3456-7890"}
    assert extract_whatsapp(u) == "551134567890"


# --- Real painel.fun payload tests ---

def test_painel_fun_as_number():
    u = {"as_number": "+5511947748236", "reseller_notes": "+55 (11) 94774-8236"}
    assert extract_whatsapp(u) == "5511947748236"


def test_painel_fun_only_reseller_notes():
    u = {"reseller_notes": "+55 (11) 94774-8236"}
    assert extract_whatsapp(u) == "5511947748236"


def test_painel_fun_as_number_without_plus():
    u = {"as_number": "5511947748236"}
    assert extract_whatsapp(u) == "5511947748236"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
