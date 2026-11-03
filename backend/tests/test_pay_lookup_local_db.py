"""Test that /api/payments/customer/{painel_id} works from local DB alone.

This is the fix for "Link inválido" in anonymous browsers: even if the
painel.fun cache is empty (fresh boot, transient error, etc.), the endpoint
must find the customer via the local `trials` table (which persists every
trial creation).
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _reload_with_fresh_db():
    """Isolated DB + reload modules that cache DB_PATH at import time."""
    tmpdb = tempfile.NamedTemporaryFile(delete=False, suffix=".db").name
    os.environ["SQLITE_PATH"] = tmpdb
    import importlib
    import database
    importlib.reload(database)
    from routers import painel_users, payments
    importlib.reload(painel_users)
    importlib.reload(payments)
    return tmpdb


def _run(coro):
    return asyncio.run(coro)


def test_pay_endpoint_finds_customer_via_trials_table_no_cache():
    """Given: a trial was created for a customer.
    When: /pay/{painel_id} is opened from a fresh anonymous browser.
    Then: the endpoint returns customer info from LOCAL DB (trials + customers),
          without depending on painel.fun cache at all.
    """
    async def go():
        _reload_with_fresh_db()

        import database
        import aiosqlite
        await database.init_db()

        for m, v in [(1, "35,00"), (3, "90,00"), (6, "160,00"), (12, "280,00")]:
            await database.set_setting(f"plan_price_{m}m", v)

        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, 'active', ?, ?)",
                ("local-uuid-1", "Guilherme TV", "5511999999999", "p2p", "2026-01-01", "2026-01-01"),
            )
            await db.execute(
                "INSERT INTO trials (id, customer_id, system_type, mac, painel_user, painel_pass, "
                "trial_user_id, expires_at, created_at, raw_response) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("trial-uuid-1", "local-uuid-1", "p2p", None, "5zl9nl", "7n8ii26k",
                 "999888", "2026-03-01T00:00:00Z", "2026-01-01T00:00:00Z", "{}"),
            )
            # Ensure painel cache is EMPTY (fresh boot scenario)
            await db.execute(
                "INSERT OR REPLACE INTO painel_users_cache (id, data, updated_at) VALUES (?, ?, ?)",
                ("all", json.dumps([]), "2026-01-01T00:00:00Z"),
            )
            await db.commit()

        from routers.payments import get_customer_payment_info
        return await get_customer_payment_info("999888")

    result = _run(go())
    assert result["customer"]["id"] == "999888"
    assert result["customer"]["name"] == "Guilherme TV"
    assert result["customer"]["system_type"] == "p2p"
    assert result["customer"]["expires_at"] == "2026-03-01T00:00:00Z"
    assert result["prices_cents"][3] == 9000


def test_pay_endpoint_still_works_by_local_uuid():
    async def go():
        _reload_with_fresh_db()
        import database
        import aiosqlite
        await database.init_db()
        for m, v in [(1, "35,00"), (3, "90,00"), (6, "160,00"), (12, "280,00")]:
            await database.set_setting(f"plan_price_{m}m", v)
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, expires_at, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
                ("uuid-abc", "Ana", "5511888", "iptv", "2026-03-01T00:00:00Z", "2026-01-01", "2026-01-01"),
            )
            await db.commit()
        from routers.payments import get_customer_payment_info
        return await get_customer_payment_info("uuid-abc")

    result = _run(go())
    assert result["customer"]["name"] == "Ana"


def test_pay_endpoint_finds_via_painel_username_fallback():
    async def go():
        _reload_with_fresh_db()
        import database
        import aiosqlite
        await database.init_db()
        for m, v in [(1, "35,00"), (3, "90,00"), (6, "160,00"), (12, "280,00")]:
            await database.set_setting(f"plan_price_{m}m", v)
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, painel_username, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
                ("uuid-x", "Bruno", "5511777", "hybrid", "brunotv", "2026-01-01", "2026-01-01"),
            )
            await db.commit()
        from routers.payments import get_customer_payment_info
        return await get_customer_payment_info("brunotv")

    result = _run(go())
    assert result["customer"]["name"] == "Bruno"


def test_pay_endpoint_404_when_truly_unknown():
    async def go():
        _reload_with_fresh_db()
        import database
        await database.init_db()
        for m, v in [(1, "35,00"), (3, "90,00"), (6, "160,00"), (12, "280,00")]:
            await database.set_setting(f"plan_price_{m}m", v)
        from routers.payments import get_customer_payment_info
        return await get_customer_payment_info("nonexistent-id-xyz")

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        _run(go())
    assert exc_info.value.status_code == 404
