"""Bug fix: when a trial user pays their conversion link, we must cancel
any pending `trial_1h_reminder` / `trial_expired` scheduled_reminders for
that phone. Otherwise the client keeps receiving 'seu teste vai expirar'
messages after already renewing.
"""
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "cancel_reminders.db")
    import importlib
    import database as _db
    importlib.reload(_db)
    from services import reminders as _r
    importlib.reload(_r)
    _run(_db.init_db())
    return _db


def _insert_reminder(event_key, phone, sent=0):
    import aiosqlite
    import database

    async def go():
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO scheduled_reminders (id, event_key, phone, "
                "context, send_at, sent, created_at) VALUES "
                "(?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), event_key, phone, json.dumps({}),
                 datetime.now(timezone.utc).isoformat(), sent,
                 datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    _run(go())


def _count_by_status(status: int, phone: str = None) -> int:
    import aiosqlite
    import database

    async def go():
        async with aiosqlite.connect(database.DB_PATH) as db:
            if phone:
                cur = await db.execute(
                    "SELECT COUNT(*) FROM scheduled_reminders "
                    "WHERE sent = ? AND phone = ?", (status, phone),
                )
            else:
                cur = await db.execute(
                    "SELECT COUNT(*) FROM scheduled_reminders WHERE sent = ?",
                    (status,),
                )
            row = await cur.fetchone()
            return row[0]

    return _run(go())


def test_cancel_pending_for_phone_only_cancels_pending(tmp_path):
    _fresh_env(tmp_path)
    from services.reminders import cancel_pending_for_phone

    _insert_reminder("trial_1h_reminder", "5511999998888")
    _insert_reminder("trial_expired", "5511999998888")
    _insert_reminder("trial_1h_reminder", "5511777776666")  # Other phone

    cancelled = _run(cancel_pending_for_phone(
        "5511999998888", event_keys=["trial_1h_reminder", "trial_expired"],
    ))

    assert cancelled == 2
    # Other phone's reminder untouched
    assert _count_by_status(0, "5511777776666") == 1
    # Target phone's are cancelled (sent=3)
    assert _count_by_status(3, "5511999998888") == 2
    assert _count_by_status(0, "5511999998888") == 0


def test_cancel_skips_already_sent_reminders(tmp_path):
    _fresh_env(tmp_path)
    from services.reminders import cancel_pending_for_phone

    _insert_reminder("trial_1h_reminder", "5511111111111", sent=1)  # already sent
    _insert_reminder("trial_expired", "5511111111111", sent=0)  # pending

    cancelled = _run(cancel_pending_for_phone(
        "5511111111111", event_keys=["trial_1h_reminder", "trial_expired"],
    ))
    # Only the pending one is cancelled (sent 1 → stays 1)
    assert cancelled == 1
    assert _count_by_status(1) == 1
    assert _count_by_status(3) == 1


def test_trial_webhook_cancels_reminders_on_payment(tmp_path):
    """End-to-end: trial user pays → webhook calls cancel_pending_for_phone."""
    _fresh_env(tmp_path)

    from routers import payments as pmt
    import aiosqlite
    import database

    async def seed():
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, "
                "painel_username, expires_at, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                ("cust-cancel", "Cliente Trial", "5511988887777", "iptv",
                 "trialX", "", "2026-01-01", "2026-01-01"),
            )
            await db.execute(
                "INSERT INTO trials (id, customer_id, system_type, mac, "
                "painel_user, painel_pass, trial_user_id, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("trial-cancel-1", "cust-cancel", "iptv", "", "trialX", "abc",
                 "888777", "", "2026-01-01"),
            )
            await db.commit()

    _run(seed())
    # Insert 2 pending reminders for the client's phone
    _insert_reminder("trial_1h_reminder", "5511988887777")
    _insert_reminder("trial_expired", "5511988887777")

    async def go():
        with patch("services.painel.renew_user",
                   new=AsyncMock(return_value={"expires_at": "2027-01-01"})), \
             patch("services.notifier.send_notification",
                   new=AsyncMock(return_value=True)), \
             patch("services.notifier.send_admin_alert",
                   new=AsyncMock(return_value=True)):
            return await pmt._process_payment_confirmation(
                order_nsu="trial-888777-1m",
                paid=True,
                source="webhook",
                raw={"transaction_nsu": "TXN-CANCEL", "paid_amount": 3500},
            )

    result = _run(go())
    assert result.get("error") != "payment not found"

    # Both trial reminders got cancelled
    assert _count_by_status(3, "5511988887777") == 2, (
        "Trial reminders should be cancelled once client renews"
    )
    assert _count_by_status(0, "5511988887777") == 0


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
