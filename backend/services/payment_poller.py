"""Background poller that reconciles pending payments with InfinitePay.

Motivation: sometimes the InfinitePay webhook is slow, drops, or fires from
an IP we haven't whitelisted. Rather than rely on webhooks alone, this
poller actively queries InfinitePay every N seconds for every pending
payment and — if paid — triggers the same renewal flow as the webhook.

Design:
- Idempotent: `_process_payment_confirmation` short-circuits when a payment
  is already "paid"/"renewed", so overlapping webhook+poller is safe.
- Bounded: only checks payments created in the last `MAX_AGE_HOURS` hours
  (older pending payments are considered abandoned).
- Non-blocking: runs as an asyncio task launched from server.py startup.
- Graceful: any exception is logged and the loop continues.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

import aiosqlite

from database import DB_PATH
from services import infinitepay

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 20   # every 20s — snappy but respectful
MAX_AGE_HOURS = 48           # ignore payments older than 2 days
_poller_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


async def _pending_payments(max_age_hours: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, order_nsu, created_at FROM payments "
            "WHERE status = 'pending' AND created_at >= ? "
            "ORDER BY created_at DESC LIMIT 100",
            (cutoff,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def check_pending_once() -> dict:
    """One sweep: check every pending payment on InfinitePay; process paid ones.

    Returns a summary dict, useful for the /api/payments/poll endpoint and
    for tests.
    """
    from routers.payments import _process_payment_confirmation

    pending = await _pending_payments(MAX_AGE_HOURS)
    result = {"checked": len(pending), "paid": 0, "errors": 0, "processed": []}

    for pmt in pending:
        try:
            check = await infinitepay.check_payment(pmt["order_nsu"])
            # STRICT: only accept when InfinitePay explicitly says paid=true.
            # `success:true` alone from /payment_check means "found the record",
            # not paid — we would falsely renew clients otherwise.
            is_paid = check.get("paid") is True
            if is_paid:
                proc = await _process_payment_confirmation(
                    pmt["order_nsu"], paid=True, source="poller", raw=check,
                )
                result["paid"] += 1
                result["processed"].append({"payment_id": pmt["id"], "result": proc.get("status")})
                logger.info("Poller confirmed paid %s → %s", pmt["order_nsu"], proc.get("status"))
        except Exception as e:
            result["errors"] += 1
            logger.exception("Poller check failed for %s: %s", pmt["order_nsu"], e)

    return result


async def _loop():
    logger.info("Payment poller started (interval=%ss, max_age=%sh)",
                POLL_INTERVAL_SECONDS, MAX_AGE_HOURS)
    while _stop_event and not _stop_event.is_set():
        try:
            await check_pending_once()
        except Exception:
            logger.exception("Poller loop iteration failed (keeping loop alive)")
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("Payment poller stopped")


def start_poller():
    global _poller_task, _stop_event
    if _poller_task and not _poller_task.done():
        return _poller_task
    _stop_event = asyncio.Event()
    _poller_task = asyncio.create_task(_loop(), name="payment_poller")
    return _poller_task


def stop_poller():
    if _stop_event:
        _stop_event.set()
