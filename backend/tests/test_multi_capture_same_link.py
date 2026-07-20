"""Tests: the same InfinitePay checkout link can be paid multiple times,
each capture triggering a fresh renewal.

Real-world scenario reported: client paid the same link twice, expected
2 months added, but only the first renewal fired. Root cause was
`payment["status"] == "paid"` gating on `order_nsu` (same for both captures).
Fix: idempotency now keyed by `transaction_nsu` (unique per capture),
falling back to `order_nsu` only when no transaction_nsu is present.
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
    os.environ["SQLITE_PATH"] = str(tmp_path / "multi_capture.db")
    import importlib
    import database
    importlib.reload(database)
    from routers import painel_users, payments
    importlib.reload(painel_users)
    importlib.reload(payments)
    return database


async def _seed_payment(database, order_nsu="renew-228116806-1m", cust_id="228116806",
                        months=1, amount_cents=3500, package_id=17):
    import aiosqlite
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await database.init_db()
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO customers "
            "(id, name, whatsapp, system_type, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (cust_id, "Cliente Teste", "5511900001111", "iptv", now, now),
        )
        await db.execute(
            "INSERT INTO payments (id, customer_id, plan_months, amount_cents,"
            " package_id, status, order_nsu, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"p-{cust_id}", cust_id, months, amount_cents, package_id, "pending",
             order_nsu, now),
        )
        await db.commit()


def _real_payload(order_nsu, transaction_nsu, paid_amount=3500):
    return {
        "invoice_slug": f"slug-{transaction_nsu[:8]}",
        "amount": paid_amount,
        "paid_amount": paid_amount,
        "installments": 1,
        "capture_method": "credit_card",
        "transaction_nsu": transaction_nsu,
        "order_nsu": order_nsu,
        "receipt_url": "https://checkout.infinitepay.io/receipt/x",
    }


# ---------- The main scenario ----------

def test_two_captures_same_link_both_renew(tmp_path):
    """Client pays link → renew fires. Client pays SAME link again → renew fires again."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    renew_calls = []

    async def fake_renew(user_id, package_id):
        renew_calls.append({"user_id": user_id, "package_id": package_id})
        return {"expires_at": "2027-01-01"}

    async def fake_wa(phone, body, image_url=None, **kw):
        pass  # We don't care about the WA content here; other tests cover that

    async def go():
        await _seed_payment(database)

        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=fake_wa):

            # First capture
            r1 = await payments_mod._process_payment_confirmation(
                "renew-228116806-1m", paid=True, source="webhook",
                raw=_real_payload("renew-228116806-1m", "txn-first-uuid"),
            )
            # Second capture on the SAME link (different transaction_nsu)
            r2 = await payments_mod._process_payment_confirmation(
                "renew-228116806-1m", paid=True, source="webhook",
                raw=_real_payload("renew-228116806-1m", "txn-second-uuid"),
            )
            return r1, r2

    r1, r2 = _run(go())

    # Both must have succeeded and triggered renewal
    assert r1["status"] == "renewed", r1
    assert r2["status"] == "renewed", r2
    # renew_user called TWICE (one per capture)
    assert len(renew_calls) == 2

    # DB must have TWO paid rows for the same order_nsu, with distinct transaction_nsu
    async def check():
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, transaction_nsu, status FROM payments "
                "WHERE order_nsu = 'renew-228116806-1m' ORDER BY created_at ASC"
            )
            return [dict(r) for r in await cur.fetchall()]

    rows = _run(check())
    assert len(rows) == 2
    assert {r["transaction_nsu"] for r in rows} == {"txn-first-uuid", "txn-second-uuid"}
    assert all(r["status"] == "paid" for r in rows)


def test_duplicate_webhook_same_transaction_is_idempotent(tmp_path):
    """InfinitePay retries the webhook with the SAME transaction_nsu → we
    must be idempotent (do NOT renew twice)."""
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    renew_calls = []

    async def fake_renew(user_id, package_id):
        renew_calls.append(1)
        return {"expires_at": "2027-01-01"}

    async def go():
        await _seed_payment(database)

        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=lambda *a, **kw: None):
            r1 = await payments_mod._process_payment_confirmation(
                "renew-228116806-1m", paid=True, source="webhook",
                raw=_real_payload("renew-228116806-1m", "txn-same-uuid"),
            )
            r2 = await payments_mod._process_payment_confirmation(
                "renew-228116806-1m", paid=True, source="webhook",
                raw=_real_payload("renew-228116806-1m", "txn-same-uuid"),
            )
            return r1, r2

    r1, r2 = _run(go())
    assert r1["status"] == "renewed"
    assert r2["status"] == "already_processed"
    assert r2["idempotent_by"] == "transaction_nsu"
    assert len(renew_calls) == 1


def test_no_transaction_nsu_falls_back_to_order_nsu_idempotency(tmp_path):
    """Legacy path: webhook without transaction_nsu → we can't tell if it's
    a new capture, so we DEFAULT to order-based idempotency (safer)."""
    database = _fresh_env(tmp_path)
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    renew_calls = []

    async def fake_renew(user_id, package_id):
        renew_calls.append(1)
        return {"expires_at": "2027-01-01"}

    async def go():
        await _seed_payment(database)

        # No transaction_nsu, use legacy flag `paid=True`
        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=lambda *a, **kw: None):
            r1 = await payments_mod._process_payment_confirmation(
                "renew-228116806-1m", paid=True, source="webhook", raw={"paid": True},
            )
            r2 = await payments_mod._process_payment_confirmation(
                "renew-228116806-1m", paid=True, source="webhook", raw={"paid": True},
            )
            return r1, r2

    r1, r2 = _run(go())
    assert r1["status"] == "renewed"
    assert r2["status"] == "already_processed"
    assert r2["idempotent_by"] == "order_nsu"
    assert len(renew_calls) == 1


def test_first_capture_stores_transaction_nsu(tmp_path):
    """After first successful webhook, the row must have transaction_nsu
    persisted — this is what protects idempotency."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    async def fake_renew(user_id, package_id):
        return {"expires_at": "2027-01-01"}

    async def go():
        await _seed_payment(database)
        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=lambda *a, **kw: None):
            await payments_mod._process_payment_confirmation(
                "renew-228116806-1m", paid=True, source="webhook",
                raw=_real_payload("renew-228116806-1m", "txn-abc-123"),
            )
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT transaction_nsu FROM payments WHERE id = 'p-228116806'"
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    row = _run(go())
    assert row["transaction_nsu"] == "txn-abc-123"


def test_three_captures_produce_three_renewals(tmp_path):
    """Extreme case: same link paid 3 times → 3 renewals + 3 DB rows."""
    database = _fresh_env(tmp_path)
    import aiosqlite
    from routers import payments as payments_mod
    from services import painel, whatsapp_client

    renew_calls = []

    async def fake_renew(user_id, package_id):
        renew_calls.append(1)
        return {"expires_at": "2027-01-01"}

    async def go():
        await _seed_payment(database)
        with patch.object(painel, "renew_user", new=fake_renew), \
             patch.object(whatsapp_client, "send_message", new=lambda *a, **kw: None):
            for i, txn in enumerate(["txn-a", "txn-b", "txn-c"]):
                r = await payments_mod._process_payment_confirmation(
                    "renew-228116806-1m", paid=True, source="webhook",
                    raw=_real_payload("renew-228116806-1m", txn),
                )
                assert r["status"] == "renewed", (i, r)

        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT COUNT(*) as c FROM payments WHERE order_nsu = 'renew-228116806-1m' AND status = 'paid'"
            )
            row = await cur.fetchone()
            return dict(row)["c"]

    total_paid = _run(go())
    assert total_paid == 3
    assert len(renew_calls) == 3
