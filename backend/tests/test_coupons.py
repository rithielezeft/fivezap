"""Tests for the coupons feature — validation, cooldown, discount cap."""
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "coupons.db")
    import importlib
    import database
    importlib.reload(database)
    from services import coupon
    importlib.reload(coupon)
    return database, coupon


# ---------- clamp_percent (pure math) ----------

def test_clamp_percent_caps_at_50():
    from services.coupon import clamp_percent
    assert clamp_percent(99) == 50
    assert clamp_percent(50) == 50
    assert clamp_percent(51) == 50
    assert clamp_percent(30) == 30
    assert clamp_percent(1) == 1


def test_clamp_percent_floors_at_1_for_valid_input():
    from services.coupon import clamp_percent
    # 0 and negatives now return 0.0 (caller decides whether to reject).
    # This is a behavior change from the int version — decimals now allowed.
    assert clamp_percent(0) == 0.0
    assert clamp_percent(-5) == 0.0
    # Decimals preserved
    assert clamp_percent(12.3) == 12.3
    assert clamp_percent(0.5) == 0.5


def test_normalize_code_uppercases_and_strips():
    from services.coupon import normalize_code
    assert normalize_code("  promo10  ") == "PROMO10"
    assert normalize_code("") == ""
    assert normalize_code(None) == ""


# ---------- validate_coupon ----------

def test_validate_nonexistent(tmp_path):
    database, coupon = _fresh_env(tmp_path)

    async def go():
        await database.init_db()
        res = await coupon.validate_coupon("NOPE", "cust1")
        assert res["valid"] is False
        assert "não encontrado" in res["reason"].lower()
    _run(go())


def test_validate_inactive(tmp_path):
    database, coupon = _fresh_env(tmp_path)
    import aiosqlite

    async def go():
        await database.init_db()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO coupons (id, code, discount_percent, active, created_at, updated_at) "
                "VALUES ('c1', 'OFF', 20, 0, '2026-01-01', '2026-01-01')"
            )
            await db.commit()
        res = await coupon.validate_coupon("off", "cust1")
        assert res["valid"] is False
        assert "inativo" in res["reason"].lower()
    _run(go())


def test_validate_active_returns_percent(tmp_path):
    database, coupon = _fresh_env(tmp_path)
    import aiosqlite

    async def go():
        await database.init_db()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO coupons (id, code, discount_percent, active, created_at, updated_at) "
                "VALUES ('c1', 'PROMO', 25, 1, '2026-01-01', '2026-01-01')"
            )
            await db.commit()
        res = await coupon.validate_coupon("promo", "cust1")
        assert res["valid"] is True
        assert res["discount_percent"] == 25
        assert res["code"] == "PROMO"
        assert res["coupon_id"] == "c1"
    _run(go())


# ---------- 28-day cooldown rule ----------

def test_cooldown_blocks_when_recently_used(tmp_path):
    database, coupon = _fresh_env(tmp_path)
    import aiosqlite

    async def go():
        await database.init_db()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO coupons (id, code, discount_percent, active, created_at, updated_at) "
                "VALUES ('c1', 'PROMO', 25, 1, '2026-01-01', '2026-01-01')"
            )
            # Usage 5 days ago (within 28-day window)
            recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
            await db.execute(
                "INSERT INTO coupon_usages (id, coupon_id, coupon_code, customer_id, "
                "payment_id, phone, discount_percent, receipt_url, painel_username, used_at) "
                "VALUES ('u1', 'c1', 'PROMO', 'cust1', 'p1', '', 25, '', '', ?)",
                (recent,),
            )
            await db.commit()
        res = await coupon.validate_coupon("PROMO", "cust1")
        assert res["valid"] is False
        assert "28" in res["reason"]
    _run(go())


def test_cooldown_allows_after_28_days(tmp_path):
    database, coupon = _fresh_env(tmp_path)
    import aiosqlite

    async def go():
        await database.init_db()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO coupons (id, code, discount_percent, active, created_at, updated_at) "
                "VALUES ('c1', 'PROMO', 25, 1, '2026-01-01', '2026-01-01')"
            )
            # Usage 30 days ago (outside 28-day window)
            old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            await db.execute(
                "INSERT INTO coupon_usages (id, coupon_id, coupon_code, customer_id, "
                "payment_id, phone, discount_percent, receipt_url, painel_username, used_at) "
                "VALUES ('u1', 'c1', 'PROMO', 'cust1', 'p1', '', 25, '', '', ?)",
                (old,),
            )
            await db.commit()
        res = await coupon.validate_coupon("PROMO", "cust1")
        assert res["valid"] is True
    _run(go())


def test_cooldown_is_per_customer_any_coupon(tmp_path):
    """Rule: cooldown blocks a customer from using ANY coupon within 28 days,
    even a different code. Same customer + different coupon => blocked."""
    database, coupon = _fresh_env(tmp_path)
    import aiosqlite

    async def go():
        await database.init_db()
        async with aiosqlite.connect(database.DB_PATH) as db:
            # Two active coupons
            await db.execute(
                "INSERT INTO coupons (id, code, discount_percent, active, created_at, updated_at) "
                "VALUES ('c1', 'FIRST', 20, 1, '2026-01-01', '2026-01-01')"
            )
            await db.execute(
                "INSERT INTO coupons (id, code, discount_percent, active, created_at, updated_at) "
                "VALUES ('c2', 'SECOND', 15, 1, '2026-01-01', '2026-01-01')"
            )
            # Customer used c1 recently
            recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
            await db.execute(
                "INSERT INTO coupon_usages (id, coupon_id, coupon_code, customer_id, "
                "payment_id, phone, discount_percent, receipt_url, painel_username, used_at) "
                "VALUES ('u1', 'c1', 'FIRST', 'cust1', 'p1', '', 20, '', '', ?)",
                (recent,),
            )
            await db.commit()
        # Attempting to use c2 (different code) — should also be blocked
        res = await coupon.validate_coupon("SECOND", "cust1")
        assert res["valid"] is False
        assert "28" in res["reason"]
        # But a different customer should still be able to use it
        res2 = await coupon.validate_coupon("SECOND", "cust_other")
        assert res2["valid"] is True
    _run(go())


# ---------- record_usage idempotency ----------

def test_record_usage_and_already_recorded(tmp_path):
    database, coupon = _fresh_env(tmp_path)

    async def go():
        await database.init_db()
        assert await coupon.already_recorded_for_payment("p999") is False
        await coupon.record_usage(
            coupon_id="c1", coupon_code="PROMO", customer_id="cust1",
            payment_id="p999", phone="+5511999", discount_percent=25,
        )
        assert await coupon.already_recorded_for_payment("p999") is True
    _run(go())
