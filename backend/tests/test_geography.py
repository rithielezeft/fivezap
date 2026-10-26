"""Tests for geography aggregation — phone number → country + BR state."""
from services.geography import resolve_country, resolve_br_state, COUNTRIES, BR_DDD


def test_resolve_br_number():
    r = resolve_country("5511987654321")
    assert r["code"] == "BR"
    assert r["ddi"] == "55"
    assert r["flag"] == "🇧🇷"


def test_resolve_spain_number():
    r = resolve_country("34612345678")
    assert r["code"] == "ES"
    assert r["ddi"] == "34"


def test_resolve_portugal_longest_prefix_beats_short():
    """351 must win over 3 (which isn't a valid DDI but proves the length
    priority). Same principle: 55 beats 5."""
    r = resolve_country("351912345678")
    assert r["code"] == "PT"
    assert r["ddi"] == "351"


def test_resolve_us_1digit_ddi():
    r = resolve_country("14155551234")
    assert r["code"] == "US"


def test_resolve_returns_none_for_unknown():
    # DDI 999 doesn't exist
    r = resolve_country("999123456")
    assert r is None


def test_resolve_returns_none_for_empty():
    assert resolve_country("") is None
    assert resolve_country("abc") is None


def test_br_state_ddd_sp():
    r = resolve_br_state("5511987654321")
    assert r["ddd"] == "11"
    assert r["uf"] == "SP"


def test_br_state_ddd_rj():
    r = resolve_br_state("5521987654321")
    assert r["ddd"] == "21"
    assert r["uf"] == "RJ"


def test_br_state_returns_none_for_non_br():
    assert resolve_br_state("34612345678") is None
    assert resolve_br_state("") is None


def test_br_state_returns_none_for_unknown_ddd():
    # DDD 99 doesn't map (but 98/99 for MA does — check 20 which is not a real BR DDD)
    r = resolve_br_state("5520987654321")
    assert r is None


def test_all_ddis_are_strings_of_digits():
    for prefix in COUNTRIES.keys():
        assert prefix.isdigit(), f"Bad DDI key: {prefix!r}"
        assert 1 <= len(prefix) <= 3, f"DDI length out of range: {prefix!r}"


def test_all_ddds_are_valid():
    for ddd in BR_DDD.keys():
        assert ddd.isdigit() and len(ddd) == 2, f"Bad DDD: {ddd!r}"
