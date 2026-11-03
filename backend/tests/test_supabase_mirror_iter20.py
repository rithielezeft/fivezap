# Supabase mirror: POST /api/supabase/mirror/run + status (asyncpg dependency regression)
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"password": "Rithi0518@"}, timeout=30)
    if r.status_code == 200:
        return r.json()["access_token"]
    # Legacy password login disabled on preview -> mint token with backend's own create_token
    import subprocess
    out = subprocess.run(["python", "/app/backend/tests/mint_token_iter20.py"], capture_output=True, text=True)
    tok = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    if not tok:
        pytest.skip(f"login failed {r.status_code} {r.text[:200]}")
    return tok


def test_mirror_run_requires_auth():
    r = requests.post(f"{BASE_URL}/api/supabase/mirror/run", timeout=60)
    assert r.status_code in (401, 403)


def test_mirror_run_ok(token):
    r = requests.post(f"{BASE_URL}/api/supabase/mirror/run",
                      headers={"Authorization": f"Bearer {token}"}, timeout=180)
    print(r.status_code, r.text[:500])
    assert r.status_code == 200
    d = r.json()
    counts = d.get("counts", d)
    assert counts["customers"] > 1000
    assert counts["trials"] > 100
    assert counts["painel_users"] >= 1


def test_mirror_status_no_error(token):
    r = requests.get(f"{BASE_URL}/api/supabase/mirror",
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    print(r.status_code, r.text[:500])
    assert r.status_code == 200
    d = r.json()
    assert d.get("configured") is True
    assert not d.get("last_error")
    assert d.get("last_run")
