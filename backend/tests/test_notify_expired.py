"""Feature: manual "Notify Expired" button.

Endpoints:
- GET /api/painel/expired → preview of expired users with WhatsApp available.
- POST /api/painel/notify-expired → enqueues manual_expired_alert to
  selected user_ids (or ALL expired users when list is empty).
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "notify_expired.db")
    import importlib
    import database as _db
    importlib.reload(_db)
    from routers import painel_users
    importlib.reload(painel_users)
    _run(_db.init_db())
    return _db


def _make_user(uid, wa=None, days_offset=-5, name="Cliente", system_type="iptv"):
    """Build a painel-like user dict with a synthetic _status computed by the
    services.expiration.compute_expiration_info function."""
    from datetime import datetime, timezone, timedelta
    exp = datetime.now(timezone.utc) + timedelta(days=days_offset)
    return {
        "id": uid,
        "username": f"user{uid}",
        "full_name": name,
        "as_number": wa or "",
        "exp_date": int(exp.timestamp()),
        "enabled": 1,
        "system": 1 if system_type == "iptv" else 2,
    }


def test_list_expired_only_returns_expired_users(tmp_path):
    _fresh_env(tmp_path)
    from routers import painel_users

    async def go():
        # Seed cache with 1 active + 2 expired + 1 expiring_soon
        await painel_users._write_cache([
            _make_user(1, wa="5511100000001", days_offset=-10, name="Vencido1"),
            _make_user(2, wa="5511100000002", days_offset=-2, name="Vencido2"),
            _make_user(3, wa="5511100000003", days_offset=+30, name="AtivoLongo"),
            _make_user(4, wa=None, days_offset=+2, name="Vencendo"),
        ])
        # Import the endpoint and call it directly
        return await painel_users.list_expired()

    result = _run(go())
    assert result["count"] == 2, f"Should return only expired users, got {result}"
    ids = {u["user_id"] for u in result["users"]}
    assert ids == {"1", "2"}


def test_notify_expired_only_enqueues_users_with_whatsapp(tmp_path):
    _fresh_env(tmp_path)
    from routers import painel_users

    calls = []

    async def fake_send(event_key, phone, ctx, customer_id=None, **kw):
        calls.append({"event_key": event_key, "phone": phone,
                      "customer_id": customer_id, "ctx": ctx})
        return True

    async def go():
        await painel_users._write_cache([
            _make_user(10, wa="5511999998888", days_offset=-3, name="ComWA"),
            _make_user(11, wa=None, days_offset=-3, name="SemWA"),
            _make_user(12, wa="5511977776666", days_offset=-10, name="OutroComWA"),
        ])
        with patch("services.notifier.send_notification", new=fake_send):
            payload = painel_users.NotifyExpiredPayload(user_ids=[])
            return await painel_users.notify_expired(payload)

    result = _run(go())
    assert result["success"] is True
    # 2 users with WA → enqueued=2, 1 without → skipped_no_whatsapp=1
    assert result["enqueued"] == 2, f"Expected 2 enqueued, got {result}"
    assert result["skipped_no_whatsapp"] == 1
    # Sent to the right phones
    phones = sorted(c["phone"] for c in calls)
    assert phones == ["5511977776666", "5511999998888"]
    # All used manual_expired_alert
    assert all(c["event_key"] == "manual_expired_alert" for c in calls)


def test_notify_expired_respects_user_ids_selection(tmp_path):
    _fresh_env(tmp_path)
    from routers import painel_users

    calls = []

    async def fake_send(event_key, phone, ctx, customer_id=None, **kw):
        calls.append({"event_key": event_key, "phone": phone, "customer_id": customer_id})
        return True

    async def go():
        await painel_users._write_cache([
            _make_user(20, wa="5511900000001", days_offset=-3),
            _make_user(21, wa="5511900000002", days_offset=-3),
            _make_user(22, wa="5511900000003", days_offset=-3),
        ])
        with patch("services.notifier.send_notification", new=fake_send):
            payload = painel_users.NotifyExpiredPayload(user_ids=["20", "22"])
            return await painel_users.notify_expired(payload)

    result = _run(go())
    assert result["enqueued"] == 2
    phones = sorted(c["phone"] for c in calls)
    assert phones == ["5511900000001", "5511900000003"]


def test_notify_expired_skips_non_expired_even_if_selected(tmp_path):
    """A malicious/stale client may pass an active user_id — server must
    re-validate `_status == expired` before firing."""
    _fresh_env(tmp_path)
    from routers import painel_users

    calls = []

    async def fake_send(event_key, phone, ctx, customer_id=None, **kw):
        calls.append(phone)
        return True

    async def go():
        await painel_users._write_cache([
            _make_user(30, wa="5511988887777", days_offset=-5),
            _make_user(31, wa="5511977776666", days_offset=+60),  # ACTIVE
        ])
        with patch("services.notifier.send_notification", new=fake_send):
            payload = painel_users.NotifyExpiredPayload(user_ids=["30", "31"])
            return await painel_users.notify_expired(payload)

    result = _run(go())
    assert result["enqueued"] == 1
    assert result["skipped_not_expired"] == 1
    assert calls == ["5511988887777"]


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
