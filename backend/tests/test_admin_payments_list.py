"""Tests for admin `GET /api/payments` — must return:
- customer_login (painel_username) with fallback to painel-cache backfill
- customer_name
- receipt_url with backfill from InfinitePay for paid rows missing it
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "adminlist.db")
    import importlib
    import database
    importlib.reload(database)
    from routers import painel_users, payments
    importlib.reload(painel_users)
    importlib.reload(payments)
    return database


async def _seed(database, painel_username=None, name="João",
                receipt_url=None, cust_id="228116806"):
    import aiosqlite
    now = datetime.now(timezone.utc).isoformat()
    await database.init_db()
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO customers "
            "(id, name, whatsapp, system_type, painel_username, created_at, updated_at) "
            "VALUES (?, ?, '5511900001111', 'iptv', ?, ?, ?)",
            (cust_id, name, painel_username, now, now),
        )
        await db.execute(
            "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
            " package_id, status, order_nsu, infinitepay_url, receipt_url, paid_at, created_at)"
            " VALUES ('pmt-1', ?, 3, 9000, 43, 'paid',"
            " 'renew-228116806-3m', 'https://checkout.infinitepay.io/link/xxx', ?, ?, ?)",
            (cust_id, receipt_url, now, now),
        )
        await db.commit()


def test_list_returns_customer_login_when_present(tmp_path):
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod

    async def go():
        await _seed(database, painel_username="joaoiptv44")
        return await payments_mod.list_payments()

    result = _run(go())
    assert len(result) == 1
    p = result[0]
    assert p.customer_login == "joaoiptv44"
    assert p.customer_name == "João"


def test_list_backfills_login_from_painel_cache(tmp_path):
    """No painel_username in local DB → looked up in painel.fun cache and persisted."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from routers import painel_users as painel_mod
    from routers import payments as payments_mod

    async def fake_cache():
        return ([{
            "id": "228116806",
            "username": "found_by_backfill",
            "full_name": "João Painel",
        }], {})

    async def go():
        await _seed(database, painel_username=None)  # missing locally
        with patch.object(painel_mod, "_read_cache", new=fake_cache):
            return await payments_mod.list_payments()

    result = _run(go())
    assert result[0].customer_login == "found_by_backfill"

    # Persisted?
    async def check():
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT painel_username FROM customers WHERE id = '228116806'"
            )
            return dict(await cur.fetchone())

    persisted = _run(check())
    assert persisted["painel_username"] == "found_by_backfill"


def test_list_falls_back_to_id_when_no_login_anywhere(tmp_path):
    """Local DB empty + painel cache doesn't have this id → customer_login=None
    (UI will render customer_id as fallback)."""
    database = _fresh_env(tmp_path)
    from routers import painel_users as painel_mod
    from routers import payments as payments_mod

    async def empty_cache():
        return ([], {})

    async def go():
        await _seed(database, painel_username=None)
        with patch.object(painel_mod, "_read_cache", new=empty_cache):
            return await payments_mod.list_payments()

    result = _run(go())
    assert result[0].customer_login is None
    # customer_id is always present as ultimate fallback
    assert result[0].customer_id == "228116806"


def test_list_backfills_receipt_url_for_paid_row(tmp_path):
    """Paid row missing receipt_url → InfinitePay check_payment fetches it."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from routers import payments as payments_mod
    from services import infinitepay

    async def fake_check(order_nsu, transaction_nsu=None, slug=None):
        return {
            "success": True, "paid": True,
            "receipt_url": "https://checkout.infinitepay.io/receipt/backfilled123",
        }

    async def go():
        await _seed(database, painel_username="ok", receipt_url=None)
        with patch.object(infinitepay, "check_payment", new=fake_check):
            return await payments_mod.list_payments()

    result = _run(go())
    assert result[0].receipt_url == "https://checkout.infinitepay.io/receipt/backfilled123"

    async def check():
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT receipt_url FROM payments WHERE id = 'pmt-1'")
            return dict(await cur.fetchone())

    assert _run(check())["receipt_url"] == "https://checkout.infinitepay.io/receipt/backfilled123"


def test_list_receipt_backfill_survives_infinitepay_failure(tmp_path):
    """InfinitePay down → list still returns rows (receipt_url stays None)."""
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod
    from services import infinitepay

    async def bad_check(*a, **kw):
        raise RuntimeError("network err")

    async def go():
        await _seed(database, painel_username="x", receipt_url=None)
        with patch.object(infinitepay, "check_payment", new=bad_check):
            return await payments_mod.list_payments()

    result = _run(go())
    assert len(result) == 1
    assert result[0].receipt_url is None
    # Row still there, page never crashes
    assert result[0].status == "paid"


def test_list_does_not_touch_pending_rows_for_receipt(tmp_path):
    """Pending rows shouldn't trigger a `check_payment` (they're not paid)."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from routers import payments as payments_mod
    from services import infinitepay

    call_count = [0]

    async def spy_check(*a, **kw):
        call_count[0] += 1
        return {"paid": False}

    async def go():
        await database.init_db()
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO customers "
                "(id, name, whatsapp, system_type, painel_username, created_at, updated_at) "
                "VALUES ('c1', 'X', '', '', 'user1', ?, ?)",
                (now, now),
            )
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
                " package_id, status, order_nsu, created_at)"
                " VALUES ('p1', 'c1', 1, 3500, 17, 'pending', 'x', ?)",
                (now,),
            )
            await db.commit()
        with patch.object(infinitepay, "check_payment", new=spy_check):
            return await payments_mod.list_payments()

    _run(go())
    assert call_count[0] == 0, "check_payment should NOT be called for pending rows"
