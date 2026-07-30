"""Regression tests for reminder dedup + renewal retry.

Bug reports (2026-02-28):
1. Duplicate 1h/3h trial reminders → same customer receives 2x each.
2. ERROR_NO_SLOT_AVAILABLE on renewal → payment paid but never renewed;
   requires manual admin action.

Fix 1: `reminders.schedule()` now upserts by (phone, event_key, sent=0)
       — only one pending row per key.
Fix 2: `paid_renewal_failed` payments with `renewal_next_retry_at <= now`
       are picked up by a background loop.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fresh_env(tmp_path):
    os.environ["SQLITE_PATH"] = str(tmp_path / "retry.db")
    import importlib
    import database
    importlib.reload(database)
    from services import reminders, renewal_retry
    importlib.reload(reminders)
    importlib.reload(renewal_retry)
    return database, reminders, renewal_retry


def _run(coro):
    return asyncio.run(coro)


# ---------- Fix 1: reminder dedup ----------

def test_schedule_same_event_key_dedupes(tmp_path):
    """Calling schedule() twice for the same (phone, event_key) must NOT
    create two pending rows."""
    database, reminders, _ = _fresh_env(tmp_path)
    import aiosqlite

    async def go():
        await database.init_db()
        await reminders.schedule("trial_1h_reminder", "5511999", 3600, {"a": 1})
        await reminders.schedule("trial_1h_reminder", "5511999", 3600, {"a": 2})
        await reminders.schedule("trial_1h_reminder", "5511999", 3600, {"a": 3})

        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, context FROM scheduled_reminders "
                "WHERE phone = ? AND event_key = ? AND sent = 0",
                ("5511999", "trial_1h_reminder"),
            )
            rows = [dict(r) for r in await cur.fetchall()]
        return rows

    rows = _run(go())
    assert len(rows) == 1, f"expected 1 row (deduped), got {len(rows)}: {rows}"
    # Latest context wins
    assert json.loads(rows[0]["context"]) == {"a": 3}


def test_schedule_different_event_keys_do_not_dedupe(tmp_path):
    """Two different event_keys for the same phone → separate rows."""
    database, reminders, _ = _fresh_env(tmp_path)
    import aiosqlite

    async def go():
        await database.init_db()
        await reminders.schedule("trial_1h_reminder", "5511999", 3600, {})
        await reminders.schedule("trial_expired", "5511999", 10800, {})
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT event_key FROM scheduled_reminders WHERE phone = ? AND sent = 0",
                ("5511999",),
            )
            return [r["event_key"] for r in await cur.fetchall()]

    keys = _run(go())
    assert sorted(keys) == ["trial_1h_reminder", "trial_expired"], keys


def test_schedule_different_phones_do_not_dedupe(tmp_path):
    """Same event_key for two different phones → separate rows."""
    database, reminders, _ = _fresh_env(tmp_path)
    import aiosqlite

    async def go():
        await database.init_db()
        await reminders.schedule("trial_1h_reminder", "5511111", 3600, {})
        await reminders.schedule("trial_1h_reminder", "5522222", 3600, {})
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT phone FROM scheduled_reminders WHERE sent = 0")
            return sorted(r["phone"] for r in await cur.fetchall())

    phones = _run(go())
    assert phones == ["5511111", "5522222"], phones


def test_schedule_after_sent_creates_new_row(tmp_path):
    """Once a reminder is marked sent (or cancelled), scheduling again
    should INSERT a fresh row (edge case: same client renews, gets
    another trial next week — must not skip the new reminder)."""
    database, reminders, _ = _fresh_env(tmp_path)
    import aiosqlite

    async def go():
        await database.init_db()
        await reminders.schedule("trial_1h_reminder", "5511999", 3600, {})
        # Mark as sent
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "UPDATE scheduled_reminders SET sent = 1 "
                "WHERE phone = ? AND event_key = ?",
                ("5511999", "trial_1h_reminder"),
            )
            await db.commit()
        # New schedule
        await reminders.schedule("trial_1h_reminder", "5511999", 3600, {})
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT COUNT(*) AS c FROM scheduled_reminders "
                "WHERE phone = ? AND event_key = ?",
                ("5511999", "trial_1h_reminder"),
            )
            row = await cur.fetchone()
        return row["c"]

    count = _run(go())
    assert count == 2, f"expected 2 rows (1 sent + 1 new pending), got {count}"


# ---------- Fix 2: renewal retry loop ----------

def test_renewal_retry_recovers_on_success(tmp_path, monkeypatch):
    """Payment in paid_renewal_failed with next_retry_at in the past is
    picked up by the sweep. If painel.renew_user succeeds, status flips
    to 'paid' and the client gets renewal_success notification."""
    database, _, renewal_retry = _fresh_env(tmp_path)
    import aiosqlite

    # Stub external effects
    from services import painel, notifier, mongo_store
    renew_calls = []
    async def fake_renew(**kwargs):
        renew_calls.append(kwargs)
        return {"expires_at": "2026-04-01T00:00:00Z"}
    monkeypatch.setattr(painel, "renew_user", fake_renew)

    notif_calls = []
    async def fake_send_notification(event_key, phone, ctx, **_):
        notif_calls.append({"event_key": event_key, "phone": phone})
        return True
    monkeypatch.setattr(notifier, "send_notification", fake_send_notification)
    async def _noop(*a, **k): return True
    monkeypatch.setattr(notifier, "send_admin_alert", _noop)
    monkeypatch.setattr(notifier, "send_hardcoded", _noop)
    async def _mongo_noop(*a, **k): pass
    monkeypatch.setattr(mongo_store, "upsert_payment", _mongo_noop)

    async def go():
        await database.init_db()
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, "
                " painel_username, status, created_at, updated_at) "
                "VALUES ('c1', 'João', '5511999', 'iptv', 'joao01', 'active', "
                "'2026-01-01', '2026-01-01')",
            )
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents, "
                " package_id, status, order_nsu, package_id, "
                " renewal_attempts, renewal_next_retry_at, renewal_last_error, "
                " created_at) VALUES "
                "('p1', 'c1', 1, 1700, 17, 'paid_renewal_failed', 'renew-228116806-1m', "
                " 17, 1, ?, 'ERROR_NO_SLOT_AVAILABLE', '2026-01-01T00:00:00+00:00')",
                (past,),
            )
            await db.commit()

        await renewal_retry._sweep_once()

        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT status, renewal_next_retry_at FROM payments WHERE id = 'p1'")
            row = dict(await cur.fetchone())
        return row

    row = _run(go())
    assert row["status"] == "paid", f"expected status=paid after successful retry, got {row}"
    assert row["renewal_next_retry_at"] is None, "next_retry_at should be cleared"
    assert len(renew_calls) == 1
    # Client got the notification that was missed
    assert any(n["event_key"] == "renewal_success" for n in notif_calls), notif_calls


def test_renewal_retry_reschedules_on_continued_failure(tmp_path, monkeypatch):
    """If painel.renew_user still fails, renewal_attempts is bumped and
    next_retry_at is pushed to +15min (second backoff step)."""
    database, _, renewal_retry = _fresh_env(tmp_path)
    import aiosqlite
    from services import painel, notifier

    async def fake_renew_fail(**kwargs):
        raise RuntimeError("ERROR_NO_SLOT_AVAILABLE")
    monkeypatch.setattr(painel, "renew_user", fake_renew_fail)
    async def _noop(*a, **k): return True
    monkeypatch.setattr(notifier, "send_admin_alert", _noop)

    async def go():
        await database.init_db()
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, "
                " painel_username, status, created_at, updated_at) "
                "VALUES ('c1', 'Ana', '5511888', 'iptv', 'ana01', 'active', "
                "'2026-01-01', '2026-01-01')",
            )
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents, "
                " package_id, status, order_nsu, "
                " renewal_attempts, renewal_next_retry_at, created_at) VALUES "
                "('p2', 'c1', 1, 1700, 17, 'paid_renewal_failed', 'renew-999-1m', "
                " 1, ?, '2026-01-01T00:00:00+00:00')",
                (past,),
            )
            await db.commit()

        await renewal_retry._sweep_once()

        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT status, renewal_attempts, renewal_next_retry_at FROM payments WHERE id = 'p2'"
            )
            return dict(await cur.fetchone())

    row = _run(go())
    assert row["status"] == "paid_renewal_failed"
    assert row["renewal_attempts"] == 2  # was 1, bumped to 2
    # next_retry_at should be roughly 15 min from now (second backoff step)
    assert row["renewal_next_retry_at"] is not None
    ts = datetime.fromisoformat(row["renewal_next_retry_at"])
    delta_min = (ts - datetime.now(timezone.utc)).total_seconds() / 60
    assert 10 <= delta_min <= 20, f"expected next_retry in ~15min, got {delta_min:.1f}"


def test_renewal_retry_gives_up_after_max_attempts(tmp_path, monkeypatch):
    """After 6 failed attempts, we stop retrying (renewal_next_retry_at
    cleared) and alert admin."""
    database, _, renewal_retry = _fresh_env(tmp_path)
    import aiosqlite
    from services import painel, notifier

    async def fake_renew_fail(**kwargs):
        raise RuntimeError("ERROR_NO_SLOT_AVAILABLE")
    monkeypatch.setattr(painel, "renew_user", fake_renew_fail)

    admin_alerts = []
    async def fake_admin(msg):
        admin_alerts.append(msg)
        return True
    monkeypatch.setattr(notifier, "send_admin_alert", fake_admin)

    async def go():
        await database.init_db()
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, "
                " painel_username, status, created_at, updated_at) "
                "VALUES ('c1', 'X', '5511', 'iptv', 'x', 'active', '2026', '2026')",
            )
            await db.execute(
                "INSERT INTO payments (id, customer_id, plan_months, amount_cents, "
                " package_id, status, order_nsu, "
                " renewal_attempts, renewal_next_retry_at, created_at) VALUES "
                "('p3', 'c1', 1, 1700, 17, 'paid_renewal_failed', 'renew-111-1m', "
                " 6, ?, '2026')",  # already at max attempts
                (past,),
            )
            await db.commit()

        await renewal_retry._sweep_once()

        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT renewal_next_retry_at FROM payments WHERE id = 'p3'"
            )
            return dict(await cur.fetchone())

    row = _run(go())
    assert row["renewal_next_retry_at"] is None, "should stop retrying after max"
    assert any("DESISTIDA" in m for m in admin_alerts), admin_alerts
