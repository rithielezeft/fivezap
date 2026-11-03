"""Tests: /pay/{id} page must always show payment receipts when available.

- Backfill: paid payments without `receipt_url` trigger a background
  InfinitePay `/payment_check` call to fetch and persist it.
- Fallback: when no `receipt_url` is available, the client still sees the
  original InfinitePay checkout URL (`infinitepay_url`) as "Ver pagamento".
- Multiple captures on the same link each get their own row + receipt.
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "receipts.db")
    import importlib
    import database
    importlib.reload(database)
    from routers import painel_users, payments
    importlib.reload(painel_users)
    importlib.reload(payments)
    return database


async def _seed(database, receipt_url=None, ipay_url="https://checkout.infinitepay.io/foo/ORDER123"):
    import aiosqlite
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await database.init_db()
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO customers "
            "(id, name, whatsapp, system_type, created_at, updated_at) "
            "VALUES ('cust-r', 'Maria', '5511900001111', 'iptv', ?, ?)",
            (now, now),
        )
        await db.execute(
            "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
            " package_id, status, order_nsu, infinitepay_url, receipt_url, paid_at, created_at)"
            " VALUES ('p-r', 'cust-r', 3, 9000, 43, 'paid',"
            " 'renew-cust-r-3m', ?, ?, ?, ?)",
            (ipay_url, receipt_url, now, now),
        )
        await db.commit()


def test_receipt_url_returned_in_history_when_stored(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod

    async def go():
        await _seed(database, receipt_url="https://receipt.infinitepay.io/xyz")
        return await payments_mod.get_customer_payment_info("cust-r")

    result = _run(go())
    assert "payments_history" in result
    assert len(result["payments_history"]) == 1
    p = result["payments_history"][0]
    assert p["receipt_url"] == "https://receipt.infinitepay.io/xyz"
    assert p["status"] == "paid"


def test_backfill_fetches_missing_receipt_url_from_infinitepay(tmp_path):
    """Paid payment has no receipt_url → endpoint calls InfinitePay to fetch
    it and persists to DB."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from routers import payments as payments_mod
    from services import infinitepay

    called_with = []

    async def fake_check(order_nsu, transaction_nsu=None, slug=None):
        called_with.append({"order_nsu": order_nsu, "transaction_nsu": transaction_nsu})
        return {
            "success": True, "paid": True, "amount": 9000,
            "receipt_url": "https://checkout.infinitepay.io/receipt/backfilled",
        }

    async def go():
        await _seed(database, receipt_url=None)  # <-- missing on purpose
        with patch.object(infinitepay, "check_payment", new=fake_check):
            return await payments_mod.get_customer_payment_info("cust-r")

    result = _run(go())
    # 1. Backfill was attempted
    assert len(called_with) == 1
    assert called_with[0]["order_nsu"] == "renew-cust-r-3m"
    # 2. The URL is now visible in the response
    p = result["payments_history"][0]
    assert p["receipt_url"] == "https://checkout.infinitepay.io/receipt/backfilled"

    # 3. And persisted to DB
    async def check():
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT receipt_url FROM payments WHERE id = 'p-r'")
            return dict(await cur.fetchone())

    row = _run(check())
    assert row["receipt_url"] == "https://checkout.infinitepay.io/receipt/backfilled"


def test_backfill_survives_infinitepay_failure(tmp_path):
    """If InfinitePay is unreachable during backfill, we still return the
    payment history (with receipt_url=None) — never crash the page."""
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod
    from services import infinitepay

    async def bad_check(*a, **kw):
        raise RuntimeError("InfinitePay 500")

    async def go():
        await _seed(database, receipt_url=None)
        with patch.object(infinitepay, "check_payment", new=bad_check):
            return await payments_mod.get_customer_payment_info("cust-r")

    result = _run(go())
    assert len(result["payments_history"]) == 1
    p = result["payments_history"][0]
    # No receipt yet, but the row must still be there
    assert p["receipt_url"] is None
    # And the fallback link (infinitepay_url) is available for the client
    assert p["infinitepay_url"].startswith("https://checkout.infinitepay.io/")


def test_pending_payment_shows_infinitepay_url_as_fallback(tmp_path):
    """A pending payment (webhook hasn't confirmed yet) must still expose
    the InfinitePay checkout link so the client can retry paying."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from datetime import datetime, timezone
    from routers import payments as payments_mod

    now = datetime.now(timezone.utc).isoformat()

    async def go():
        await database.init_db()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO customers "
                "(id, name, whatsapp, system_type, created_at, updated_at) "
                "VALUES ('cust-p', 'Maria', '5511900001111', 'iptv', ?, ?)",
                (now, now),
            )
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
                " package_id, status, order_nsu, infinitepay_url, created_at)"
                " VALUES ('p-pend', 'cust-p', 1, 3500, 17, 'pending',"
                " 'renew-cust-p-1m', 'https://checkout.infinitepay.io/foo/PENDING123', ?)",
                (now,),
            )
            await db.commit()
        return await payments_mod.get_customer_payment_info("cust-p")

    result = _run(go())
    p = result["payments_history"][0]
    assert p["status"] == "pending"
    assert p["receipt_url"] is None
    assert p["infinitepay_url"] == "https://checkout.infinitepay.io/foo/PENDING123"
