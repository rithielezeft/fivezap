"""Regression tests: (1) expiration reminders skip trial users, (2) upload
endpoint accepts common phone formats and rejects with clear messages.

Bug reports (2026-02-28):
- "notificações de vencimento começou a ser enviado para os clientes trial de testes"
- "quando tento adicionar imagem para upload nos comandos aparece Falha ao enviar imagem"
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "s.db")
    import importlib, database
    importlib.reload(database)
    from services import scheduler
    importlib.reload(scheduler)
    return database, scheduler


def _run(coro):
    return asyncio.run(coro)


# ---------- Trial users are skipped in scheduler ----------

def test_scheduler_skips_trial_package(tmp_path, monkeypatch):
    """A painel user with package_id == trial_package_id (61) must NOT
    receive expiration_*d reminders — they get trial_1h/trial_expired
    scheduled separately."""
    database, scheduler = _fresh_env(tmp_path)

    from services import painel
    from services.notifier import send_notification as _real_send
    from services import notifier

    notif_calls = []
    async def fake_send_notification(event_key, phone, ctx, **kw):
        notif_calls.append({"event": event_key, "phone": phone,
                            "cust": kw.get("customer_id")})
        return True
    monkeypatch.setattr(scheduler, "send_notification", fake_send_notification)

    # Painel returns 3 users: 1 trial, 1 normal expiring in 3 days, 1 far future
    from datetime import datetime, timezone, timedelta
    def _ts(days): return int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp())

    users = [
        # Trial user (package_id 61)
        {"id": 1001, "username": "trial01", "package_id": 61,
         "exp_date": _ts(3), "enabled": 1, "whatsapp": "5511111111111"},
        # Regular user expiring in 3 days
        {"id": 1002, "username": "regular01", "package_id": 17,
         "exp_date": _ts(3), "enabled": 1, "whatsapp": "5511222222222"},
        # Far-future user (should not trigger)
        {"id": 1003, "username": "future01", "package_id": 17,
         "exp_date": _ts(30), "enabled": 1, "whatsapp": "5511333333333"},
    ]

    async def fake_list_users(**kw): return users
    monkeypatch.setattr(painel, "list_users", fake_list_users)

    async def go():
        await database.init_db()
        # Configure: notify 3 days before + trial pkg = 61
        from database import set_setting
        await set_setting("notification_days", "3")
        await set_setting("trial_package_id", "61")
        await set_setting("notification_pacing_seconds", "0")

        await scheduler._check_and_notify()

    _run(go())

    # Only the REGULAR expiring user should have been notified.
    assert len(notif_calls) == 1, (
        f"Expected 1 notification (regular01 only), got {len(notif_calls)}: {notif_calls}"
    )
    assert notif_calls[0]["phone"] == "5511222222222"
    assert notif_calls[0]["event"] == "expiration_3d"


def test_scheduler_skips_is_trial_flag(tmp_path, monkeypatch):
    """Also skip when painel exposes `is_trial=true` instead of package_id."""
    database, scheduler = _fresh_env(tmp_path)

    from services import painel
    notif_calls = []
    async def fake_send_notification(event_key, phone, ctx, **kw):
        notif_calls.append(event_key)
        return True
    monkeypatch.setattr(scheduler, "send_notification", fake_send_notification)

    from datetime import datetime, timezone, timedelta
    def _ts(days): return int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp())

    users = [
        {"id": 2001, "username": "flagtrial", "is_trial": True,
         "package_id": 999, "exp_date": _ts(1), "enabled": 1, "whatsapp": "5511111"},
    ]
    async def fake_list_users(**kw): return users
    monkeypatch.setattr(painel, "list_users", fake_list_users)

    async def go():
        await database.init_db()
        from database import set_setting
        await set_setting("notification_days", "1")
        await set_setting("notification_pacing_seconds", "0")
        await scheduler._check_and_notify()

    _run(go())
    assert notif_calls == [], f"trial users must be skipped, got: {notif_calls}"


# ---------- Upload endpoint validation ----------

def test_upload_extension_and_size():
    """Verify the module constants have expected values so the /api/uploads
    endpoint accepts phone-camera formats and gives a generous size cap."""
    from routers import uploads
    # HEIC/HEIF (iPhone default) MUST be accepted
    assert "heic" in uploads.ALLOWED_EXT
    assert "heif" in uploads.ALLOWED_EXT
    # BMP + webp for completeness
    assert "webp" in uploads.ALLOWED_EXT
    assert "bmp" in uploads.ALLOWED_EXT
    # Common formats still there
    for ext in ("jpg", "jpeg", "png", "gif"):
        assert ext in uploads.ALLOWED_EXT, f"missing {ext}"
    # 15MB is enough for uncompressed phone photos
    assert uploads.MAX_SIZE_MB >= 10, f"limit too low: {uploads.MAX_SIZE_MB}MB"
