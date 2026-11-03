"""International phone support — the system should NOT force +55 on numbers
that already have a foreign country code.

Real-world scenario: clients in Spain (+34), Portugal (+351), USA (+1),
UK (+44), Argentina (+54), etc. all use WhatsApp and buy the service.
Previously, the extractor mangled `+34 612345678` to `55 34612345678`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_plus_sign_prevents_prepending_55():
    from services.phone_extractor import _clean
    # Spain
    assert _clean("+34 612 345 678") == "34612345678"
    # Portugal
    assert _clean("+351 912 345 678") == "351912345678"
    # USA
    assert _clean("+1 (555) 123-4567") == "15551234567"
    # UK
    assert _clean("+44 7700 900123") == "447700900123"


def test_bare_brazilian_still_gets_55():
    from services.phone_extractor import _clean
    assert _clean("11987654321") == "5511987654321"
    assert _clean("(11) 98765-4321") == "5511987654321"
    assert _clean("1198765-4321") == "5511987654321"
    # 10-digit landline
    assert _clean("1133334444") == "551133334444"


def test_already_prefixed_brazilian_kept():
    from services.phone_extractor import _clean
    assert _clean("5511987654321") == "5511987654321"
    assert _clean("+55 11 98765-4321") == "5511987654321"


def test_foreign_number_without_plus_kept_when_12_or_more_digits():
    """A 12+ digit number without `+` is assumed to already have a country
    code and is kept as-is. Only 10-11 digit bare numbers get +55 prepended
    (they're ambiguous but the system's primary market is Brazil)."""
    from services.phone_extractor import _clean
    # Portugal +351 with 9-digit local = 12 digits total
    assert _clean("351912345678") == "351912345678"
    # UK +44 with 10-digit local = 12 digits total
    assert _clean("447700900123") == "447700900123"
    # BUT: bare 11-digit `34612345678` (Spain no plus) is ambiguous with
    # BR local 11-digit → user MUST include the `+` sign for foreign
    # numbers. This is standard E.164 practice.


def test_foreign_bare_11_digits_needs_plus_sign():
    """Bare 11-digit foreign numbers (like Spain without `+`) are ambiguous
    with BR São Paulo mobile. Enforce that user provides `+` prefix."""
    from services.phone_extractor import _clean
    # WITH plus: correctly identified as foreign
    assert _clean("+34612345678") == "34612345678"
    # WITHOUT plus: falls back to BR interpretation (system's default)
    assert _clean("34612345678") == "5534612345678"


def test_argentina_not_confused_with_brazil():
    """Argentina is +54, Brazil is +55. Must not confuse them."""
    from services.phone_extractor import _clean
    # +54 9 11 6123 4567 = 13 digits (starts with 54)
    assert _clean("5491161234567") == "5491161234567"


def test_extract_whatsapp_from_international_note():
    """Painel notes containing international numbers must be extracted correctly."""
    from services.phone_extractor import extract_whatsapp
    user = {
        "username": "carlos_es",
        "reseller_notes": "Cliente español, WhatsApp +34 612 345 678",
    }
    result = extract_whatsapp(user)
    assert result == "34612345678", f"Got: {result!r}"


def test_extract_whatsapp_portuguese_number():
    from services.phone_extractor import extract_whatsapp
    user = {
        "username": "joao_pt",
        "notes": "Contato: +351 912-345-678",
    }
    assert extract_whatsapp(user) == "351912345678"


def test_extract_whatsapp_us_number():
    from services.phone_extractor import extract_whatsapp
    user = {
        "username": "john_us",
        "notes": "WA +1 (555) 123-4567",
    }
    assert extract_whatsapp(user) == "15551234567"


def test_extract_whatsapp_brazil_still_works():
    from services.phone_extractor import extract_whatsapp
    user = {
        "username": "maria_br",
        "reseller_notes": "WhatsApp: (11) 98765-4321",
    }
    assert extract_whatsapp(user) == "5511987654321"


def test_as_number_field_with_foreign_code():
    """`as_number` (painel's structured phone field) with foreign country
    code must be preserved as-is, not remapped to +55."""
    from services.phone_extractor import extract_whatsapp
    user = {
        "username": "pierre_fr",
        "as_number": "+33 6 12 34 56 78",
    }
    assert extract_whatsapp(user) == "33612345678"


def test_short_numbers_not_prepended():
    """Numbers too short to be valid must not be silently mangled."""
    from services.phone_extractor import _clean
    # 5 digits — clearly not a phone
    assert _clean("12345") == "12345"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
