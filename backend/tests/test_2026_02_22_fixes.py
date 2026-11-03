"""Coverage for the 4 fixes shipped 2026-02-22:
1. Admin payment alert includes painel_username.
2. Scheduler daily-key is set BEFORE send (prevents duplicates when
   dedup_window_minutes is too small).
3. WhatsApp /restart endpoint exists.
4. Payment poller keeps polling pending payments for 7 days.
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "fixes.db")
    import importlib
    import database as _db
    importlib.reload(_db)
    _run(_db.init_db())
    return _db


# ---------- 1. painel_username in admin alert ----------

def test_admin_alert_includes_painel_login(tmp_path):
    """The `admin_msg` string in _process_payment_confirmation must have a
    Login line with the painel_username of the client."""
    import inspect
    from routers import payments
    src = inspect.getsource(payments._process_payment_confirmation)
    assert "Login:" in src
    assert "painel_user" in src, "Admin alert must include painel_user variable"


# ---------- 2. Scheduler sets daily-key BEFORE send ----------

def test_scheduler_marks_daily_key_before_send(tmp_path):
    """Even if send_notification raises/queues, the daily key must be set
    so the next hourly cycle doesn't retry (which would cause duplicates
    when dedup_window is small)."""
    _fresh_env(tmp_path)
    from services import scheduler, painel
    import database

    seed_user = {
        "id": 500,
        "username": "u500",
        "as_number": "5511900000500",
        # 3 days in future
        "exp_date": int((__import__("datetime").datetime.utcnow().timestamp() + 3 * 86400)),
    }

    async def go():
        await database.set_setting("notification_days", "3")
        await database.set_setting("public_base_url", "https://example.com")
        await database.set_setting("notification_pacing_seconds", "0")
        # A template must exist so send_notification tries to enqueue.
        async with __import__("aiosqlite").connect(database.DB_PATH) as db:
            from models import new_id, now_iso
            await db.execute(
                "INSERT OR REPLACE INTO notification_templates (id, event_key, title, body, "
                "image_url, enabled, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (new_id(), "expiration_3d", "3d", "hi {name}", "", now_iso()),
            )
            await db.commit()

        # Make send_notification RAISE — we want to verify daily key is set anyway.
        async def raising_send(*a, **kw):
            raise RuntimeError("simulated whatsapp down")

        with patch.object(painel, "list_users", new=AsyncMock(return_value=[seed_user])), \
             patch("services.scheduler.send_notification", new=raising_send):
            try:
                await scheduler._check_and_notify()
            except Exception:
                # scheduler's inner try/except should have swallowed this.
                pass

        # Daily-key must still exist so next cycle doesn't retry the same day.
        from datetime import datetime as _dt, timezone as _tz
        today = _dt.now(_tz.utc).date().isoformat()
        key = f"notified_500_3_{today}"
        val = await database.get_setting(key)
        return val

    val = _run(go())
    assert val == "1", (
        f"Daily key must be set BEFORE send_notification, even if send fails. "
        f"Got: {val!r}"
    )


# ---------- 3. WhatsApp /restart endpoint exists ----------

def test_whatsapp_restart_endpoint_registered():
    from routers import whatsapp
    routes = [r for r in whatsapp.router.routes]
    paths = [r.path for r in routes]
    methods = [(r.path, sorted(r.methods)) for r in routes]
    assert "/api/whatsapp/restart" in paths, f"POST /restart missing. Have: {paths}"
    restart_route = next(r for r in routes if r.path == "/api/whatsapp/restart")
    assert "POST" in restart_route.methods


def test_whatsapp_restart_calls_stop_then_start(tmp_path):
    """The restart endpoint must kill Node process THEN respawn it."""
    from routers import whatsapp

    call_order = []

    def fake_stop():
        call_order.append("stop")

    def fake_start():
        call_order.append("start")

    async def go():
        import server as _srv
        # Replace the functions on the server module reference
        with patch.object(_srv, "_stop_whatsapp_service", side_effect=fake_stop), \
             patch.object(_srv, "_start_whatsapp_service", side_effect=fake_start), \
             patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            # Fake `_wa_process` since it's read after start.
            _srv._wa_process = MagicMock(pid=12345)
            return await whatsapp.restart()

    result = _run(go())
    assert call_order == ["stop", "start"], f"Wrong order: {call_order}"
    assert result["success"] is True
    assert result["pid"] == 12345


# ---------- 4. Payment poller max_age = 7 days (168h) ----------

def test_payment_poller_max_age_is_seven_days():
    """The poller was 48h; now 168h so late payers (3rd/5th day pix) still
    reconcile."""
    from services import payment_poller
    assert payment_poller.MAX_AGE_HOURS >= 168, (
        f"Poller should keep polling for 7 days, got {payment_poller.MAX_AGE_HOURS}h"
    )


def test_payment_page_pending_cutoff_is_seven_days():
    """The /pay-page-return endpoint also reads only recent pending — must
    be at least 168h to catch late captures."""
    from routers import payments
    import inspect
    src = inspect.getsource(payments)
    # Search for the cutoff line and check the hours arg
    import re
    matches = re.findall(r"timedelta\(hours=(\d+)\)", src)
    assert matches, "Should find timedelta(hours=N) in payments.py"
    # At least one of them should be >=168
    max_hours = max(int(m) for m in matches)
    assert max_hours >= 168, (
        f"Some hours=N < 168. Values found: {matches}"
    )


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
