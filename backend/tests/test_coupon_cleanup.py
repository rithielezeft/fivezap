"""Regression: expired coupons get deleted (or deactivated) hourly."""
import asyncio, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "cleanup.db")
    import importlib, database
    importlib.reload(database)
    from services import coupon_cleanup
    importlib.reload(coupon_cleanup)
    return database, coupon_cleanup


def _run(coro): return asyncio.run(coro)


def test_expired_unused_coupon_is_deleted(tmp_path):
    database, cleanup = _fresh_env(tmp_path)
    import aiosqlite

    async def go():
        await database.init_db()
        past = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        async with aiosqlite.connect(database.DB_PATH) as db:
            # 3 coupons: expired-unused, expired-used, still-valid
            for i, (exp, uses) in enumerate([(past, 0), (past, 1), (future, 0)]):
                await db.execute(
                    "INSERT INTO coupons (id, code, discount_percent, active, "
                    "expires_at, max_uses, created_at, updated_at) "
                    "VALUES (?, ?, 10, 1, ?, NULL, ?, ?)",
                    (f"c{i}", f"CODE{i}", exp, "2026-01-01", "2026-01-01"),
                )
            # Give c1 a usage row
            await db.execute(
                "INSERT INTO coupon_usages (id, coupon_id, coupon_code, customer_id, "
                "payment_id, phone, discount_percent, receipt_url, painel_username, used_at) "
                "VALUES ('u1', 'c1', 'CODE1', 'cust1', '', '', 10, '', '', ?)",
                (past,),
            )
            await db.commit()
        return await cleanup.sweep_once()

    result = _run(go())
    assert result["deleted"] == 1, result   # c0 (expired, unused) deleted
    assert result["deactivated"] == 1, result  # c1 (expired, used) deactivated

    async def verify():
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT id, active FROM coupons ORDER BY id")
            return [dict(r) for r in await cur.fetchall()]
    remaining = _run(verify())
    ids = {r["id"] for r in remaining}
    assert "c0" not in ids, "expired-unused should have been DELETED"
    assert "c1" in ids, "expired-used must be kept for audit trail"
    assert "c2" in ids, "still-valid must remain"
    c1 = next(r for r in remaining if r["id"] == "c1")
    c2 = next(r for r in remaining if r["id"] == "c2")
    assert c1["active"] == 0, "expired-used must be marked inactive"
    assert c2["active"] == 1, "still-valid must remain active"
