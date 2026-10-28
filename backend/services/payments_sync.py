"""Two-way sync of the `payments` table (SQLite) with MongoDB Atlas.

Mongo is the durable copy: rows missing locally are restored from it, and
every local row is pushed back so all fields (receipt, NSU, coupon…) persist."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import aiosqlite

from database import DB_PATH

logger = logging.getLogger(__name__)

COLS = [
    "id", "customer_id", "plan_months", "amount_cents", "package_id", "status",
    "infinitepay_url", "order_nsu", "confirmation_token", "paid_at", "created_at",
    "transaction_nsu", "receipt_url", "discount_percent", "original_amount_cents",
    "ref_bucket", "coupon_code", "coupon_id", "renewal_attempts",
    "renewal_next_retry_at", "renewal_last_error",
]
REQUIRED = ("customer_id", "plan_months", "amount_cents", "package_id")


async def sync_payments() -> dict:
    from services.mongo_store import _get_db
    from services.payment_poller import MAX_AGE_HOURS
    mdb = _get_db()
    recent_cutoff = (datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS + 24)).isoformat()
    restored = pushed = 0
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        local_ids = {r[0] async for r in await db.execute("SELECT id FROM payments")}

        async for d in mdb.payments.find({}):
            pid = str(d["_id"])
            if pid in local_ids or any(d.get(k) is None for k in REQUIRED):
                continue
            row = {c: d.get(c) for c in COLS}
            row["id"] = pid
            row["status"] = row["status"] or "pending"
            if row["status"] == "renewed":
                row["status"] = "paid"  # locally "paid" means paid + renewed
            row["created_at"] = row["created_at"] or d.get("paid_at") or d.get("last_synced_at")
            if not row["created_at"]:
                continue
            # Never restore retry state, and skip recent pending links: another
            # environment sharing this Atlas may still be polling/renewing them.
            row["renewal_next_retry_at"] = None
            if row["status"] == "pending" and row["created_at"] >= recent_cutoff:
                continue
            await db.execute(
                f"INSERT OR IGNORE INTO payments ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
                [row[c] for c in COLS],
            )
            restored += 1
        await db.execute("UPDATE payments SET status = 'paid' WHERE status = 'renewed'")
        await db.commit()

        rows = await (await db.execute(f"SELECT {', '.join(COLS)} FROM payments")).fetchall()
    for r in rows:
        doc = {k: r[k] for k in COLS if k not in ("id", "status") and r[k] is not None}
        await mdb.payments.update_one({"_id": r["id"]}, {"$set": doc}, upsert=True)
        # Keep Mongo's richer "renewed" status instead of downgrading it to "paid".
        await mdb.payments.update_one(
            {"_id": r["id"], "status": {"$ne": "renewed"}} if r["status"] == "paid" else {"_id": r["id"]},
            {"$set": {"status": r["status"]}},
        )
        pushed += 1
    logger.info("payments sync: restored %d from Mongo, pushed %d to Mongo", restored, pushed)
    return {"restored": restored, "pushed": pushed}


async def payments_sync_loop(interval_s: int = 300):
    while True:
        try:
            await sync_payments()
        except Exception:
            logger.exception("payments sync failed (will retry)")
        await asyncio.sleep(interval_s)
