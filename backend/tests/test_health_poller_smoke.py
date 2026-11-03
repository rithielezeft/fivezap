"""Smoke/regression tests for the payment poller lifespan wiring.

Guards against the iteration-14 silent-failure class of bug where
@app.on_event was ignored due to FastAPI(lifespan=...) — the poller
would never start and pending payments would never reconcile.

These tests hit the live REACT_APP_BACKEND_URL (public URL), so they
double as a production smoke check.
"""
import os
import re
import requests


def _base_url():
    """Read REACT_APP_BACKEND_URL from env or /app/frontend/.env fallback."""
    url = os.environ.get("REACT_APP_BACKEND_URL", "").strip().rstrip("/")
    if url:
        return url
    env_path = "/app/frontend/.env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                m = re.match(r'^\s*REACT_APP_BACKEND_URL\s*=\s*"?([^"\n]+)"?', line)
                if m:
                    return m.group(1).strip().rstrip("/")
    return "http://localhost:8001"


BASE_URL = _base_url()


def test_health_poller_is_public_and_running():
    """GET /api/health/poller — no auth, returns 200 with running=true."""
    r = requests.get(f"{BASE_URL}/api/health/poller", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["running"] is True, f"Poller task NOT running: {body}"
    assert body["task_name"] == "payment_poller"
    assert body["task_done"] is False


def test_health_root_public():
    r = requests.get(f"{BASE_URL}/api/health", timeout=10)
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_payment_poller_started_in_supervisor_logs():
    """Regression guard: after every backend restart the log MUST have a
    'Payment poller started' line — proves lifespan() actually invoked
    start_poller() and the @app.on_event vs lifespan= foot-gun did not
    silently regress."""
    log_path = "/var/log/supervisor/backend.err.log"
    if not os.path.exists(log_path):
        import pytest
        pytest.skip(f"{log_path} not accessible in this environment")
    with open(log_path) as f:
        contents = f.read()
    assert "Payment poller started" in contents, (
        "'Payment poller started' NOT found in backend log — this means the "
        "poller was never scheduled at startup (likely the lifespan=/@on_event "
        "regression from iteration 14 came back)."
    )


def test_check_status_by_customer_is_public():
    """POST /api/payments/check-status/{id} — public (no auth) endpoint."""
    r = requests.post(
        f"{BASE_URL}/api/payments/check-status/228116806", timeout=15
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] in ("renewed", "still_pending", "no_pending")


def test_check_status_get_still_blocked():
    """GET on the same path must remain 401 (only POST is public)."""
    r = requests.get(
        f"{BASE_URL}/api/payments/check-status/228116806", timeout=10
    )
    assert r.status_code == 401


def test_poll_now_requires_admin():
    r = requests.post(f"{BASE_URL}/api/payments/poll-now", timeout=10)
    assert r.status_code == 401


def test_poll_now_works_with_admin_token():
    pw = os.environ.get("ADMIN_PASSWORD") or "Rithi0518@"
    login = requests.post(
        f"{BASE_URL}/api/auth/login", json={"password": pw}, timeout=10
    )
    assert login.status_code == 200, login.text
    token = login.json().get("access_token") or login.json().get("token")
    assert token, f"No access_token in login response: {login.json()}"
    r = requests.post(
        f"{BASE_URL}/api/payments/poll-now",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "checked" in data
    assert "paid" in data
    assert "errors" in data


def test_no_dead_on_event_handlers_in_server_py():
    """Static guard: no leftover @app.on_event decorators (would be dead
    code under FastAPI(lifespan=...) and confuse maintainers)."""
    import ast
    from pathlib import Path
    src = Path("/app/backend/server.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                # Match @app.on_event(...) or @<any>.on_event(...)
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Attribute) and target.attr == "on_event":
                    raise AssertionError(
                        f"Found active @*.on_event decorator on {node.name!r} "
                        f"(line {node.lineno}) — remove it; startup/shutdown "
                        "must live inside lifespan()."
                    )
