"""Regression tests for /pay/{customer_id} fallback to painel.fun cache.

Prevents the bug where the /pay page returned 404 because the customer_id
came from painel.fun (not the local customers table).
"""
import asyncio
import json
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_endpoint_falls_back_to_painel_cache(monkeypatch):
    """Given a customer_id that exists ONLY in painel.fun cache (not local table),
    the /customer/{id} endpoint must return the painel data instead of 404."""

    # Isolated DB
    tmpdb = tempfile.NamedTemporaryFile(delete=False, suffix=".db").name

    # Patch DB_PATH before importing anything else
    monkeypatch.setenv("SQLITE_PATH", tmpdb)

    import importlib
    from database import init_db, DB_PATH  # noqa
    import database
    importlib.reload(database)  # re-read env var

    async def _run():
        await database.init_db()

        # Seed the painel cache with a fake user
        painel_user = {
            "id": 228032579,
            "username": "clientex",
            "full_name": "Cliente Exemplo Ltda",
            "system": 2,  # p2p
            "exp_date": 2000000000,
            "enabled": 1,
            "as_number": "+5511987654321",
        }
        import aiosqlite
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO painel_users_cache (id, data, updated_at) "
                "VALUES ('all', ?, ?)",
                (json.dumps([painel_user]), "2026-01-01T00:00:00Z"),
            )
            await db.commit()

        # Also seed prices
        for m, v in [(1, "35,00"), (3, "90,00"), (6, "160,00"), (12, "280,00")]:
            await database.set_setting(f"plan_price_{m}m", v)

        # Now call the endpoint fn directly
        from routers.payments import get_customer_payment_info
        result = await get_customer_payment_info(str(painel_user["id"]))

        assert result["customer"]["id"] == "228032579"
        assert "Cliente" in result["customer"]["name"]
        assert result["customer"]["system_type"] == "p2p"
        assert result["customer"]["expires_at"] is not None
        assert result["prices_cents"][1] == 3500
        assert result["prices_cents"][12] == 28000

    try:
        asyncio.run(_run())
    finally:
        os.unlink(tmpdb)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
