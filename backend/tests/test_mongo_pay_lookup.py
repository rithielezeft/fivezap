"""Tests for the Mongo Atlas fallback in /api/payments/customer/{id}
+ the auth middleware public-path fix."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def test_is_public_allows_pay_lookup_endpoint():
    from services.auth import is_public
    assert is_public("/api/payments/customer/228116806", "GET") is True
    assert is_public("/api/payments/customer/anything-here", "GET") is True


def test_is_public_still_blocks_payments_list():
    """GET /api/payments (admin-only, lists payment history) must NOT be public."""
    from services.auth import is_public
    assert is_public("/api/payments", "GET") is False


def test_is_public_allows_post_payments_for_checkout():
    """POST /api/payments (checkout from /pay/{id}) must be public."""
    from services.auth import is_public
    assert is_public("/api/payments", "POST") is True


def test_is_public_blocks_customers_list():
    from services.auth import is_public
    assert is_public("/api/customers", "GET") is False
    assert is_public("/api/trials", "GET") is False


def test_pay_endpoint_uses_mongo_first(monkeypatch):
    """When Mongo has the customer, endpoint returns Mongo data (no SQLite hit needed)."""
    from routers import payments as payments_mod
    from services import mongo_store

    async def fake_find(painel_id):
        assert painel_id == "227453827"
        return {
            "_id": "227453827",
            "full_name": "Cliente Global",
            "system_type": "p2p",
            "exp_date_iso": "2026-05-01T00:00:00+00:00",
        }

    async def fake_get_setting(key, default=None):
        return {"plan_price_1m": "35,00", "plan_price_3m": "90,00",
                "plan_price_6m": "160,00", "plan_price_12m": "280,00"}.get(key, default or "")

    monkeypatch.setattr(mongo_store, "find_customer_by_painel_id", fake_find)
    monkeypatch.setattr(payments_mod, "get_setting", fake_get_setting)

    result = _run(payments_mod.get_customer_payment_info("227453827"))
    assert result["customer"]["id"] == "227453827"
    assert result["customer"]["name"] == "Cliente Global"
    assert result["customer"]["system_type"] == "p2p"
    assert result["prices_cents"][1] == 3500


def test_pay_endpoint_falls_back_when_mongo_returns_none(monkeypatch, tmp_path):
    """When Mongo has no record, endpoint continues to SQLite/cache fallback."""
    from routers import payments as payments_mod
    from services import mongo_store
    import database
    import aiosqlite
    import os

    # Set up isolated SQLite
    tmpdb = str(tmp_path / "wf.db")
    os.environ["SQLITE_PATH"] = tmpdb
    import importlib
    importlib.reload(database)
    from routers import painel_users
    importlib.reload(painel_users)
    importlib.reload(payments_mod)

    async def go():
        await database.init_db()
        for m, v in [(1, "35,00"), (3, "90,00"), (6, "160,00"), (12, "280,00")]:
            await database.set_setting(f"plan_price_{m}m", v)
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, painel_username,"
                " status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
                ("uuid-1", "Local Only", "5511", "iptv", "sqlite_user", "2026-01-01", "2026-01-01"),
            )
            await db.commit()

        with patch.object(mongo_store, "find_customer_by_painel_id",
                          new=AsyncMock(return_value=None)):
            return await payments_mod.get_customer_payment_info("sqlite_user")

    result = _run(go())
    assert result["customer"]["name"] == "Local Only"
