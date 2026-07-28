"""Regression tests for duplicate renewal confirmation messages.

Scenario A (the actual production bug reported by the user):
  1. Client returns from InfinitePay → `/check-status` (or poller) marks
     the payment as PAID but has NO `transaction_nsu` (check_payment API
     doesn't return one). Client is notified — GOOD.
  2. Minutes later, the real InfinitePay webhook arrives WITH a
     `transaction_nsu`. Previously this was treated as a "new capture on
     an existing paid link" and CLONED the payment → re-notified the
     client → duplicate confirmation message. BUG.

Scenario B: race condition — two concurrent callers process the same
pending payment near-simultaneously. Only one should flip status and
send the notification.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "dedup.db")
    import importlib
    import database
    importlib.reload(database)
    # Force re-import of payment code so it uses the new DB_PATH
    import routers.payments as payments_mod
    importlib.reload(payments_mod)
    return database, payments_mod


def _run(coro):
    return asyncio.run(coro)


async def _seed_pending_payment(database, payment_id: str, order_nsu: str,
                                customer_id: str = "cust1"):
    import aiosqlite
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "INSERT INTO customers (id, name, whatsapp, system_type, "
            "painel_username, current_package_id, status, created_at, updated_at) "
            "VALUES (?, 'Cliente Teste', '+5511999998888', 'iptv', 'testuser', 61,"
            " 'active', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
            (customer_id,),
        )
        await db.execute(
            "INSERT INTO payments (id, customer_id, plan_months, amount_cents, "
            "package_id, status, order_nsu, created_at) "
            "VALUES (?, ?, 1, 1700, 61, 'pending', ?, '2026-01-01T00:00:00+00:00')",
            (payment_id, customer_id, order_nsu),
        )
        await db.commit()


def test_pay_return_then_webhook_does_not_reclone(tmp_path, monkeypatch):
    """Scenario A — the reported bug.

    check-status confirms first (no txn_nsu), then webhook arrives with
    txn_nsu=XXXX. The webhook must NOT clone the row and must NOT re-run
    the renewal/notification chain.
    """
    database, payments_mod = _fresh_env(tmp_path)

    # Track how many times renewal-side effects fire. We patch the two
    # side-effect functions used inside _process_payment_confirmation.
    renew_calls = []
    notify_calls = []

    from services import painel
    import services.notifier as notifier_mod

    async def fake_renew_user(**kwargs):
        renew_calls.append(kwargs)
        return {"ok": True, "new_expires_at": "2026-02-01"}

    async def fake_send_notification(event_key, phone, ctx, customer_id=None, **_):
        notify_calls.append({"event_key": event_key, "phone": phone,
                             "customer_id": customer_id})
        return True

    monkeypatch.setattr(painel, "renew_user", fake_renew_user)
    monkeypatch.setattr(notifier_mod, "send_notification", fake_send_notification)
    # Silence admin alert
    monkeypatch.setattr(notifier_mod, "send_admin_alert", lambda *a, **k: None)
    monkeypatch.setattr(notifier_mod, "send_hardcoded", lambda *a, **k: None)

    async def go():
        await database.init_db()
        await _seed_pending_payment(database, "pay1", "renew-228116806-1m")

        # Step 1: pay-page return (no transaction_nsu in raw)
        r1 = await payments_mod._process_payment_confirmation(
            "renew-228116806-1m", paid=True, source="signed_redirect",
            raw={"token_matched": True},
        )
        assert r1["ok"] is True
        # First call went through the full renewal flow → status is 'renewed'
        # (or 'renewed_no_expiry' if painel didn't return expiry) or 'paid'.
        assert r1.get("status") not in ("already_processed",), (
            f"first call should NOT be already_processed, got {r1}"
        )

        # Step 2: real webhook arrives — has transaction_nsu
        r2 = await payments_mod._process_payment_confirmation(
            "renew-228116806-1m", paid=True, source="webhook",
            raw={"transaction_nsu": "TXN-1234", "receipt_url": "https://r/1"},
        )
        # Must be idempotent, NOT a new capture
        assert r2["status"] == "already_processed", (
            f"expected already_processed, got {r2}"
        )

        # Backfill happened: the payment row now has transaction_nsu stored
        import aiosqlite
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM payments")
            rows = [dict(r) for r in await cur.fetchall()]
        # Only ONE payment row must exist (no clone)
        assert len(rows) == 1, f"expected 1 payment row, got {len(rows)}: {rows}"
        assert rows[0]["transaction_nsu"] == "TXN-1234"
        assert rows[0]["status"] == "paid"

    _run(go())

    # Renewal + notification each fired at most ONCE, from the first call.
    assert len(renew_calls) == 1, f"renew_user called {len(renew_calls)} times"
    # Filter to renewal_success only (excludes admin alerts via notify_admin)
    renewal_notifs = [n for n in notify_calls if n["event_key"] == "renewal_success"]
    assert len(renewal_notifs) == 1, (
        f"renewal_success notified {len(renewal_notifs)} times: {renewal_notifs}"
    )


def test_second_webhook_with_new_txn_still_clones(tmp_path, monkeypatch):
    """Sanity: if a client legitimately pays TWICE on the same link (two
    distinct transaction_nsus), we SHOULD still clone + re-renew."""
    database, payments_mod = _fresh_env(tmp_path)

    renew_calls = []
    from services import painel
    import services.notifier as notifier_mod

    async def fake_renew_user(**kwargs):
        renew_calls.append(kwargs)
        return {"ok": True, "new_expires_at": "2026-02-01"}
    async def fake_send_notification(*a, **k): return True
    monkeypatch.setattr(painel, "renew_user", fake_renew_user)
    monkeypatch.setattr(notifier_mod, "send_notification", fake_send_notification)
    async def _noop(*a, **k): return True
    monkeypatch.setattr(notifier_mod, "send_admin_alert", _noop)
    monkeypatch.setattr(notifier_mod, "send_hardcoded", _noop)

    async def go():
        await database.init_db()
        await _seed_pending_payment(database, "pay1", "renew-228116806-1m")

        # First webhook (has transaction_nsu)
        await payments_mod._process_payment_confirmation(
            "renew-228116806-1m", paid=True, source="webhook",
            raw={"transaction_nsu": "TXN-1"},
        )
        # Second webhook — DIFFERENT transaction_nsu (real second capture)
        r2 = await payments_mod._process_payment_confirmation(
            "renew-228116806-1m", paid=True, source="webhook",
            raw={"transaction_nsu": "TXN-2"},
        )
        # Should have cloned
        import aiosqlite
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM payments ORDER BY created_at")
            rows = [dict(r) for r in await cur.fetchall()]
        assert len(rows) == 2, f"expected 2 payment rows (clone), got {len(rows)}"
        assert {rows[0]["transaction_nsu"], rows[1]["transaction_nsu"]} == {"TXN-1", "TXN-2"}
        return r2

    r2 = _run(go())
    # Renewal fires for BOTH captures
    assert len(renew_calls) == 2, f"expected 2 renewals, got {len(renew_calls)}"


def test_concurrent_pending_confirmation_only_notifies_once(tmp_path, monkeypatch):
    """Scenario B — race: webhook + poller hit at the same instant."""
    database, payments_mod = _fresh_env(tmp_path)

    renew_calls = []
    from services import painel
    import services.notifier as notifier_mod

    async def fake_renew_user(**kwargs):
        renew_calls.append(kwargs)
        return {"ok": True, "new_expires_at": "2026-02-01"}
    async def fake_send_notification(*a, **k): return True
    monkeypatch.setattr(painel, "renew_user", fake_renew_user)
    monkeypatch.setattr(notifier_mod, "send_notification", fake_send_notification)
    async def _noop(*a, **k): return True
    monkeypatch.setattr(notifier_mod, "send_admin_alert", _noop)
    monkeypatch.setattr(notifier_mod, "send_hardcoded", _noop)

    async def go():
        await database.init_db()
        await _seed_pending_payment(database, "pay1", "renew-228116806-1m")

        # Fire two concurrent confirmations — only ONE should win the race.
        r1, r2 = await asyncio.gather(
            payments_mod._process_payment_confirmation(
                "renew-228116806-1m", paid=True, source="webhook",
                raw={"transaction_nsu": "TXN-1"},
            ),
            payments_mod._process_payment_confirmation(
                "renew-228116806-1m", paid=True, source="poller",
                raw={},  # poller often has no txn_nsu
            ),
        )
        return r1, r2

    r1, r2 = _run(go())
    # Exactly one renewal must fire, not two.
    assert len(renew_calls) == 1, (
        f"race not guarded — got {len(renew_calls)} renewals; results: {r1}, {r2}"
    )
