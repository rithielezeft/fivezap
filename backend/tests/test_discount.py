"""Tests for the same-day 7-day discount feature.

Business rules to enforce:
1. Discount only applies when `discount_7d_enabled = true`.
2. Discount only applies when a `notified_{customer_id}_7_{today}` key
   exists in settings (proving the 7d reminder was fired TODAY).
3. If the reminder was fired YESTERDAY (client is now 6d away), no discount.
4. Discount percentage is configurable via `discount_7d_percent`.
5. Amount is floored to nearest cent, never negative.
6. Payment row stores both `discount_percent` and `original_amount_cents`
   for auditability.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run(coro):
    return asyncio.run(coro)


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "disc.db")
    import importlib
    import database
    importlib.reload(database)
    from services import discount
    importlib.reload(discount)
    return database


# ---------- apply_discount (pure math) ----------

def test_apply_discount_5_percent():
    from services.discount import apply_discount
    assert apply_discount(10000, 5) == 9500
    assert apply_discount(3500, 5) == 3325
    assert apply_discount(9000, 10) == 8100


def test_apply_discount_zero_returns_original():
    from services.discount import apply_discount
    assert apply_discount(9000, 0) == 9000


def test_apply_discount_floors_cents():
    from services.discount import apply_discount
    # 3500 * 0.95 = 3325 exact → 3325
    # 3501 * 0.95 = 3325.95 → floored to 3325
    assert apply_discount(3501, 5) == 3325


def test_apply_discount_clamps_percent():
    from services.discount import apply_discount
    # Over 100% → treat as 100% → amount = 0
    assert apply_discount(9000, 200) == 0
    # Negative → treat as 0
    assert apply_discount(9000, -5) == 9000


def test_apply_discount_never_negative():
    from services.discount import apply_discount
    assert apply_discount(0, 50) == 0


# ---------- get_active_discount (state machine) ----------

def test_disabled_returns_none(tmp_path):
    database = _fresh_env(tmp_path)
    from services.discount import get_active_discount

    async def go():
        await database.init_db()
        await database.set_setting("discount_7d_enabled", "false")
        return await get_active_discount("cust-1")

    assert _run(go()) is None


def test_enabled_but_reminder_not_sent_today_returns_none(tmp_path):
    """Enabled + percent set, BUT the notified_ key for TODAY doesn't
    exist → no discount (client is not within the promo window)."""
    database = _fresh_env(tmp_path)
    from services.discount import get_active_discount

    async def go():
        await database.init_db()
        await database.set_setting("discount_7d_enabled", "true")
        await database.set_setting("discount_7d_percent", "5")
        return await get_active_discount("cust-alone")

    assert _run(go()) is None


def test_enabled_and_reminder_sent_today_returns_discount(tmp_path):
    database = _fresh_env(tmp_path)
    from services.discount import get_active_discount

    async def go():
        await database.init_db()
        await database.set_setting("discount_7d_enabled", "true")
        await database.set_setting("discount_7d_percent", "5")
        today = datetime.now(timezone.utc).date().isoformat()
        await database.set_setting(f"notified_cust-2_7_{today}", "1")
        return await get_active_discount("cust-2")

    result = _run(go())
    assert result == {"percent": 5, "source": "7d_reminder_same_day"}


def test_reminder_sent_yesterday_no_longer_applies(tmp_path):
    """The core business rule: reminder yesterday (6d remaining) → no discount."""
    database = _fresh_env(tmp_path)
    from services.discount import get_active_discount

    async def go():
        await database.init_db()
        await database.set_setting("discount_7d_enabled", "true")
        await database.set_setting("discount_7d_percent", "5")
        # Mark a yesterday's reminder — must NOT trigger discount today.
        yesterday = (datetime.now(timezone.utc).date().toordinal() - 1)
        from datetime import date
        yday_iso = date.fromordinal(yesterday).isoformat()
        await database.set_setting(f"notified_cust-3_7_{yday_iso}", "1")
        return await get_active_discount("cust-3")

    assert _run(go()) is None


def test_percent_configurable(tmp_path):
    database = _fresh_env(tmp_path)
    from services.discount import get_active_discount

    async def go():
        await database.init_db()
        await database.set_setting("discount_7d_enabled", "true")
        await database.set_setting("discount_7d_percent", "12")
        today = datetime.now(timezone.utc).date().isoformat()
        await database.set_setting(f"notified_cust-4_7_{today}", "1")
        return await get_active_discount("cust-4")

    assert _run(go())["percent"] == 12


def test_percent_zero_returns_none(tmp_path):
    """Enabled but percent=0 → no discount to speak of."""
    database = _fresh_env(tmp_path)
    from services.discount import get_active_discount

    async def go():
        await database.init_db()
        await database.set_setting("discount_7d_enabled", "true")
        await database.set_setting("discount_7d_percent", "0")
        today = datetime.now(timezone.utc).date().isoformat()
        await database.set_setting(f"notified_cust-5_7_{today}", "1")
        return await get_active_discount("cust-5")

    assert _run(go()) is None


def test_enabled_various_truthy_values(tmp_path):
    """`discount_7d_enabled` accepts 'true'/'1'/'yes'/'on'."""
    from services.discount import get_active_discount

    async def go(val):
        database = _fresh_env(tmp_path)
        await database.init_db()
        await database.set_setting("discount_7d_enabled", val)
        await database.set_setting("discount_7d_percent", "5")
        today = datetime.now(timezone.utc).date().isoformat()
        await database.set_setting(f"notified_x_7_{today}", "1")
        return await get_active_discount("x")

    for val in ("true", "True", "TRUE", "1", "yes", "on"):
        assert _run(go(val)) is not None, f"failed for '{val}'"


def test_empty_customer_id_returns_none(tmp_path):
    database = _fresh_env(tmp_path)
    from services.discount import get_active_discount

    async def go():
        await database.init_db()
        return await get_active_discount("")

    assert _run(go()) is None
