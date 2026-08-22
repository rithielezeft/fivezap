"""Background sweeper: hard-deletes expired coupons that have no usages.

Rules:
- A coupon is `expired` when `expires_at IS NOT NULL AND expires_at < now`.
- Only DELETE coupons with **zero recorded usages** — we keep the audit
  trail intact for coupons that were actually redeemed.
- Expired coupons WITH usages are just marked inactive (`active=0`) so
  the history still shows the code + %, but nobody can redeem again.

Runs once every CHECK_INTERVAL_SECONDS (default 1h).
"""
import asyncio
import logging
from datetime import datetime, timezone

import aiosqlite

from database import DB_PATH

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60 * 60  # hourly


async def sweep_once() -> dict:
    """Delete unused expired coupons; deactivate used expired coupons.
    Returns {"deleted": N, "deactivated": M}."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT c.id, c.code, "
            "(SELECT COUNT(*) FROM coupon_usages u WHERE u.coupon_id = c.id) AS uses "
            "FROM coupons c "
            "WHERE c.expires_at IS NOT NULL AND c.expires_at < ?",
            (now_iso,),
        )
        rows = [dict(r) for r in await cur.fetchall()]

        deleted, deactivated = 0, 0
        for r in rows:
            if int(r["uses"] or 0) == 0:
                await db.execute("DELETE FROM coupons WHERE id = ?", (r["id"],))
                deleted += 1
                logger.info("coupon_cleanup: deleted expired unused %s (id=%s)", r["code"], r["id"])
            else:
                # Only mark inactive if it's still active — avoid noisy updates
                await db.execute(
                    "UPDATE coupons SET active = 0, updated_at = ? WHERE id = ? AND active = 1",
                    (now_iso, r["id"]),
                )
                if db.total_changes:
                    deactivated += 1
                    logger.info("coupon_cleanup: deactivated expired-with-uses %s (id=%s, uses=%d)",
                                r["code"], r["id"], int(r["uses"]))
        await db.commit()

    return {"deleted": deleted, "deactivated": deactivated}


async def coupon_cleanup_loop():
    logger.info("coupon_cleanup_loop started (interval=%ds)", CHECK_INTERVAL_SECONDS)
    while True:
        try:
            r = await sweep_once()
            if r["deleted"] or r["deactivated"]:
                logger.info("coupon_cleanup: %d deleted, %d deactivated",
                            r["deleted"], r["deactivated"])
        except Exception:
            logger.exception("coupon_cleanup_loop iteration failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
