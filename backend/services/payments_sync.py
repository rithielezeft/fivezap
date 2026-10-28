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
    "renewal_next_retry_at", "renewal_last_error", "provider", "account_id",
    "extra_customer_ids", "mp_payment_id", "adult_channels", "clovers",
]
REQUIRED = ("customer_id", "plan_months", "amount_cents", "package_id")


RANK = {"pending": 0, "paid_renewal_failed": 1, "paid": 2, "renewed": 3}


def _local_status(st):
    return "paid" if st == "renewed" else (st or "pending")


async def sync_payments() -> dict:
    from pymongo import UpdateOne
    from services.mongo_store import _get_db
    from services.payment_poller import MAX_AGE_HOURS
    mdb = _get_db()
    recent_cutoff = (datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS + 24)).isoformat()
    restored = refreshed = 0
    mongo = {str(d["_id"]): d async for d in mdb.payments.find({})}
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("UPDATE payments SET status = 'paid' WHERE status = 'renewed'")
        local = {r["id"]: dict(r) for r in await (await db.execute(f"SELECT {', '.join(COLS)} FROM payments")).fetchall()}

        for pid, d in mongo.items():
            m_status = _local_status(d.get("status"))
            if pid in local:
                # Mongo advanced (e.g. paid on the other environment) → refresh locally.
                lr = local[pid]
                if RANK.get(m_status, 0) > RANK.get(lr["status"], 0):
                    upd = {c: d.get(c) for c in COLS if c not in ("id", "status", "renewal_next_retry_at") and d.get(c) is not None and lr.get(c) is None}
                    upd["status"] = m_status
                    await db.execute(f"UPDATE payments SET {', '.join(k + ' = ?' for k in upd)} WHERE id = ?", [*upd.values(), pid])
                    lr.update(upd)
                    refreshed += 1
                continue
            if any(d.get(k) is None for k in REQUIRED):
                continue
            row = {c: d.get(c) for c in COLS}
            row.update(id=pid, status=m_status, renewal_next_retry_at=None)
            row["created_at"] = row["created_at"] or d.get("paid_at") or d.get("last_synced_at")
            # Skip recent pending links: another environment may still be polling them.
            if not row["created_at"] or (m_status == "pending" and row["created_at"] >= recent_cutoff):
                continue
            await db.execute(
                f"INSERT OR IGNORE INTO payments ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
                [row[c] for c in COLS],
            )
            restored += 1
        await db.commit()

    ops = []
    for pid, r in local.items():
        m = mongo.get(pid)
        m_rank = RANK.get((m or {}).get("status"), -1)
        if m and RANK.get(r["status"], 0) < min(m_rank, RANK["paid"]):
            continue  # Mongo is ahead: never push a stale local row over it
        doc = {k: r[k] for k in COLS if k not in ("id", "status") and r[k] is not None}
        if m and m_rank >= RANK.get(r["status"], 0):
            doc = {k: v for k, v in doc.items() if m.get(k) is None}  # only fill gaps
        else:
            doc["status"] = r["status"]
        if doc:
            ops.append(UpdateOne({"_id": pid}, {"$set": doc}, upsert=True))
    if ops:
        await mdb.payments.bulk_write(ops, ordered=False)
    logger.info("payments sync: restored %d, refreshed %d, pushed %d", restored, refreshed, len(ops))
    return {"restored": restored, "refreshed": refreshed, "pushed": len(ops)}


async def payments_sync_loop(interval_s: int = 300):
    while True:
        try:
            await sync_payments()
        except Exception:
            logger.exception("payments sync failed (will retry)")
        await asyncio.sleep(interval_s)
