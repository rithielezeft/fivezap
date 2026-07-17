"""Tests for expiration helper."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.expiration import compute_expiration_info  # noqa: E402


def _iso(days_from_now):
    return (datetime.now(timezone.utc) + timedelta(days=days_from_now)).isoformat()


def test_active_far_future():
    r = compute_expiration_info({"expires_at": _iso(30)})
    assert r["status"] == "active"
    assert r["days_until_expiry"] == 30


def test_expiring_soon_3d():
    r = compute_expiration_info({"expires_at": _iso(2)})
    assert r["status"] == "expiring_soon"


def test_expired():
    r = compute_expiration_info({"expires_at": _iso(-5)})
    assert r["status"] == "expired"
    assert r["days_until_expiry"] == -5


def test_no_date_active_flag():
    r = compute_expiration_info({"active": True})
    assert r["status"] == "active"
    assert r["days_until_expiry"] is None


def test_no_date_no_status():
    r = compute_expiration_info({"username": "x"})
    assert r["status"] == "unknown"


def test_disabled_overrides_future_date():
    r = compute_expiration_info({"expires_at": _iso(30), "status": "disabled"})
    assert r["status"] == "expired"


def test_br_date_format():
    r = compute_expiration_info({"vencimento": "31/12/2099"})
    assert r["status"] == "active"


def test_iso_zulu():
    r = compute_expiration_info({"expires_at": "2099-01-01T00:00:00Z"})
    assert r["status"] == "active"


# --- Real painel.fun payload tests (exp_date is UNIX SECONDS, enabled is 0/1) ---

def test_painel_fun_unix_timestamp_future():
    # Very far future timestamp
    r = compute_expiration_info({"exp_date": 1806853892, "enabled": 1})
    assert r["status"] == "active"
    assert r["days_until_expiry"] > 0
    assert r["expires_at_iso"] is not None


def test_painel_fun_unix_timestamp_past_disabled():
    # Past timestamp + enabled=0
    r = compute_expiration_info({"exp_date": 1000000000, "enabled": 0})
    assert r["status"] == "expired"


def test_painel_fun_enabled_1_no_date():
    r = compute_expiration_info({"enabled": 1})
    assert r["status"] == "active"


def test_painel_fun_enabled_0_future_date():
    # Enabled=0 must override even a future date
    import time
    future = int(time.time()) + 86400 * 30  # 30 days from now
    r = compute_expiration_info({"exp_date": future, "enabled": 0})
    assert r["status"] == "expired"


def test_painel_fun_unix_string():
    r = compute_expiration_info({"exp_date": "1806853892"})
    assert r["status"] == "active"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
