"""Tests for the payment poller + on-return-from-pay reconciliation flow.

Guarantees renewals happen even if the InfinitePay webhook is slow, dropped,
or blocked — the poller + /check-status/{customer_id} endpoint keep hitting
InfinitePay's /payment_check until confirmed.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "poll.db")
    import importlib
    import database
    importlib.reload(database)
    from routers import painel_users, payments
    importlib.reload(painel_users)
    importlib.reload(payments)
    from services import payment_poller
    importlib.reload(payment_poller)
    return database


def test_check_pending_once_processes_paid_payments(monkeypatch, tmp_path):
    """Poller sweep finds a pending payment, InfinitePay says paid=true,
    → processes as if webhook had fired."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from datetime import datetime, timezone
    from services import payment_poller, infinitepay
    from routers import payments as payments_mod

    now_iso = datetime.now(timezone.utc).isoformat()
    processed = []

    async def fake_check_payment(order_nsu):
        if "228116806" in order_nsu:
            return {"paid": True, "success": True, "amount": 3500}
        return {"paid": False}

    async def fake_process(order_nsu, paid, source, raw):
        processed.append({"order_nsu": order_nsu, "paid": paid, "source": source})
        return {"ok": True, "status": "renewed", "payment_id": "x"}

    async def go():
        await database.init_db()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
                " package_id, status, order_nsu, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("p-1", "228116806", 1, 3500, 17, "pending",
                 "renew-228116806-1m", now_iso),
            )
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
                " package_id, status, order_nsu, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("p-2", "222", 1, 3500, 17, "paid",
                 "renew-222-1m", now_iso),
            )
            await db.commit()

        with patch.object(infinitepay, "check_payment", new=fake_check_payment), \
             patch.object(payments_mod, "_process_payment_confirmation", new=fake_process):
            return await payment_poller.check_pending_once()

    result = _run(go())
    assert result["checked"] == 1  # only the pending one
    assert result["paid"] == 1
    assert len(processed) == 1
    assert processed[0]["order_nsu"] == "renew-228116806-1m"
    assert processed[0]["source"] == "poller"


def test_check_pending_once_ignores_old_payments(monkeypatch, tmp_path):
    """Payments older than MAX_AGE_HOURS (48h) should NOT be polled forever."""
    from datetime import datetime, timezone, timedelta
    database = _fresh_env(tmp_path)
    import aiosqlite
    from services import payment_poller

    old_ts = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()

    async def go():
        await database.init_db()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
                " package_id, status, order_nsu, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("old-1", "111", 1, 3500, 17, "pending", "renew-111-1m", old_ts),
            )
            await db.commit()
        return await payment_poller._pending_payments(48)

    pendings = _run(go())
    assert pendings == []


def test_check_status_endpoint_public_and_processes_paid(monkeypatch, tmp_path):
    """POST /api/payments/check-status/{customer_id} — public endpoint used
    by /pay/{id}?ok=1 page. Queries InfinitePay + triggers renewal if paid."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from services import infinitepay
    from routers import payments as payments_mod

    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    async def fake_check_payment(order_nsu):
        return {"paid": True, "success": True}

    processed_ref = {}

    async def fake_process(order_nsu, paid, source, raw):
        processed_ref["order_nsu"] = order_nsu
        processed_ref["source"] = source
        return {"ok": True, "status": "renewed", "payment_id": "abc"}

    async def go():
        await database.init_db()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
                " package_id, status, order_nsu, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("pay-1", "228116806", 1, 3500, 17, "pending",
                 "renew-228116806-1m", now_iso),
            )
            await db.commit()
        with patch.object(infinitepay, "check_payment", new=fake_check_payment), \
             patch.object(payments_mod, "_process_payment_confirmation", new=fake_process):
            return await payments_mod.check_status_by_customer("228116806")

    result = _run(go())
    assert result["status"] == "renewed"
    assert result["payment_id"] == "pay-1"
    assert processed_ref["source"] == "pay_page_return"


def test_check_status_endpoint_returns_no_pending_when_empty(monkeypatch, tmp_path):
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod

    async def go():
        await database.init_db()
        return await payments_mod.check_status_by_customer("999-never-existed")

    result = _run(go())
    assert result["status"] == "no_pending"
    assert result["checked"] == 0


def test_is_public_allows_check_status_endpoint():
    from services.auth import is_public
    assert is_public("/api/payments/check-status/228116806", "POST") is True
    assert is_public("/api/payments/check-status/228116806", "GET") is False


def test_check_status_still_pending_when_infinitepay_says_not_paid(monkeypatch, tmp_path):
    database = _fresh_env(tmp_path)
    import aiosqlite
    from services import infinitepay
    from routers import payments as payments_mod

    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    async def fake_check_payment(order_nsu):
        return {"paid": False, "success": False}

    async def go():
        await database.init_db()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
                " package_id, status, order_nsu, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("pay-2", "228116806", 3, 9950, 43, "pending",
                 "renew-228116806-3m", now_iso),
            )
            await db.commit()
        with patch.object(infinitepay, "check_payment", new=fake_check_payment):
            return await payments_mod.check_status_by_customer("228116806")

    result = _run(go())
    assert result["status"] == "still_pending"
    assert result["checked"] == 1
