"""Iteration 20 tests: (1) reseller_notes contains only phone; (2) display_timezone persists."""
import os
import re
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://trial-manager-7.preview.emergentagent.com").rstrip("/")
ADMIN_PASSWORD = "Rithi0518@"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


# Feature 1: source-code assertion — reseller_notes MUST be ONLY the phone number
def test_reseller_notes_source_contains_only_phone():
    src = open("/app/backend/services/painel.py").read()
    m = re.search(r'payload\["reseller_notes"\]\s*=\s*(.+)', src)
    assert m, "reseller_notes assignment not found in painel.py"
    line = m.group(1).strip()
    # Must be exactly f"+{whatsapp}" — no name, no full_name
    assert 'name' not in line.lower(), f"reseller_notes still references name: {line}"
    assert 'whatsapp' in line, f"reseller_notes should include whatsapp: {line}"
    assert line.startswith('f"+{whatsapp}"') or line == 'f"+{whatsapp}"', f"Unexpected: {line}"


# Feature 2: display_timezone update + persistence
def test_display_timezone_persists_madrid(headers):
    r = requests.put(f"{BASE_URL}/api/settings", json={"display_timezone": "Europe/Madrid"}, headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    g = requests.get(f"{BASE_URL}/api/settings", headers=headers, timeout=30)
    assert g.status_code == 200
    assert g.json().get("display_timezone") == "Europe/Madrid"


def test_display_timezone_reset_saopaulo(headers):
    r = requests.put(f"{BASE_URL}/api/settings", json={"display_timezone": "America/Sao_Paulo"}, headers=headers, timeout=30)
    assert r.status_code == 200
    g = requests.get(f"{BASE_URL}/api/settings", headers=headers, timeout=30)
    assert g.json().get("display_timezone") == "America/Sao_Paulo"


def test_display_timezone_accepts_utc(headers):
    r = requests.put(f"{BASE_URL}/api/settings", json={"display_timezone": "UTC"}, headers=headers, timeout=30)
    assert r.status_code == 200
    g = requests.get(f"{BASE_URL}/api/settings", headers=headers, timeout=30)
    assert g.json().get("display_timezone") == "UTC"
    # cleanup
    requests.put(f"{BASE_URL}/api/settings", json={"display_timezone": "America/Sao_Paulo"}, headers=headers, timeout=30)
