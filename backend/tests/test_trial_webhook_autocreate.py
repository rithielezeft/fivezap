"""Bug fix: when a trial customer pays via InfinitePay, no local payment row
exists (the trial pay link is created directly by services.bot without an
INSERT INTO payments). The webhook receives `order_nsu=trial-<painel_id>-<n>m`
and used to bail out with 'payment not found', so the client never got the
renewal + confirmation message.

The fix: `_process_payment_confirmation` auto-creates a pending payment row
for trial-prefixed order_nsus, then falls through to the normal renewal +
notification path.
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
    """Isolated SQLite DB with the schema."""
    os.environ["SQLITE_PATH"] = str(tmp_path / "trial_webhook.db")
    import importlib
    import database as _db
    importlib.reload(_db)
    from routers import painel_users, payments
    importlib.reload(painel_users)
    importlib.reload(payments)
    _run(_db.init_db())
    return _db


def test_trial_webhook_autocreates_payment_and_notifies(tmp_path):
    """
    Simulate: client took a trial (no local payment row), then paid the
    trial→checkout link. Webhook must:
      1. Auto-create a payments row keyed on `order_nsu=trial-<painel_id>-1m`.
      2. Mark it paid.
      3. Call painel.renew_user with the extracted painel_id.
      4. Send `renewal_success` template to the client's WhatsApp.
    """
    _fresh_env(tmp_path)

    from routers import payments as pmt
    import aiosqlite
    import database

    # Seed a trials row so _process_payment_confirmation can resolve
    # customer_id + system_type. (Emulates services.bot.create_trial.)
    async def seed():
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, "
                "painel_username, expires_at, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                ("cust-trial-1", "João Teste", "5511999998888", "p2p",
                 "trialuser99", "", "2026-01-01", "2026-01-01"),
            )
            await db.execute(
                "INSERT INTO trials (id, customer_id, system_type, mac, "
                "painel_user, painel_pass, trial_user_id, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("trial-1", "cust-trial-1", "p2p", "", "trialuser99", "abc",
                 "999888", "", "2026-01-01"),
            )
            await db.commit()

    _run(seed())

    renew_calls = []
    notify_calls = []

    async def fake_renew(user_id, package_id):
        renew_calls.append({"user_id": user_id, "package_id": package_id})
        return {"expires_at": "2027-01-01T00:00:00Z"}

    async def fake_send_notification(event_key, phone, ctx, customer_id=None, **kw):
        notify_calls.append({
            "event_key": event_key, "phone": phone, "ctx": ctx,
            "customer_id": customer_id,
        })
        return True

    async def go():
        with patch("services.painel.renew_user", new=fake_renew), \
             patch("services.notifier.send_notification", new=fake_send_notification), \
             patch("services.notifier.send_admin_alert", new=AsyncMock(return_value=True)):
            return await pmt._process_payment_confirmation(
                order_nsu="trial-999888-1m",
                paid=True,
                source="webhook",
                raw={
                    "transaction_nsu": "TXN-ABC-123",
                    "paid_amount": 3500,
                    "invoice_slug": "inv-xyz",
                    "receipt_url": "https://recibo.example/x",
                },
            )

    result = _run(go())

    # 1. It didn't return "payment not found"
    assert result.get("error") != "payment not found", (
        f"Trial webhook still bails out: {result}"
    )
    # 2. Renewal fired for the painel_id extracted from order_nsu
    assert len(renew_calls) == 1, f"Expected 1 renew call, got {renew_calls}"
    assert renew_calls[0]["user_id"] == "999888"

    # 3. Client got the renewal_success notification (or a fallback).
    events = [c["event_key"] for c in notify_calls]
    assert "renewal_success" in events, (
        f"Client must receive renewal_success template. Got: {events}"
    )
    # And it went to the right phone number.
    rs = next(c for c in notify_calls if c["event_key"] == "renewal_success")
    assert rs["phone"] == "5511999998888"


def test_trial_webhook_persists_payment_row(tmp_path):
    """Assert the auto-created payments row is actually inserted so future
    idempotency checks + admin listings work correctly."""
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
                ("cust-x", "N", "551199", "iptv",
                 "u2", "", "2026-01-01", "2026-01-01"),
            )
            await db.execute(
                "INSERT INTO trials (id, customer_id, system_type, mac, "
                "painel_user, painel_pass, trial_user_id, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("trial-2", "cust-x", "iptv", "", "u2", "p", "777",
                 "", "2026-01-01"),
            )
            await db.commit()

    _run(seed())

    async def go():
        with patch("services.painel.renew_user",
                   new=AsyncMock(return_value={"expires_at": "2027-01-01"})), \
             patch("services.notifier.send_notification",
                   new=AsyncMock(return_value=True)), \
             patch("services.notifier.send_admin_alert",
                   new=AsyncMock(return_value=True)):
            await pmt._process_payment_confirmation(
                order_nsu="trial-777-3m",
                paid=True,
                source="webhook",
                raw={"transaction_nsu": "TXN-1", "paid_amount": 9000},
            )
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM payments WHERE order_nsu = ?", ("trial-777-3m",)
            )
            return await cur.fetchone()

    row = _run(go())
    assert row is not None, "Trial payment row was not persisted"
    assert row["status"] == "paid"
    assert row["plan_months"] == 3
    assert row["order_nsu"] == "trial-777-3m"
    # Amount from paid_amount (in cents on real webhook)
    assert row["amount_cents"] == 9000


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
