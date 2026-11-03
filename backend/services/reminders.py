"""Reminder scheduler — persists scheduled WhatsApp messages in SQLite and
fires them at the right time (survives backend restarts).

Used for: trial 1h reminder, trial 3h expiration, and any other future
time-based one-off notification.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta

import aiosqlite

from database import DB_PATH
from services.notifier import send_notification

logger = logging.getLogger(__name__)


async def schedule(event_key: str, phone: str, delay_seconds: int, context: dict):
    """Schedule a notification to be sent after `delay_seconds`.

    Dedup: if there's ALREADY a pending (sent=0) reminder for the same
    (phone, event_key), we UPDATE its send_at + context in place instead
    of inserting a new row. This prevents duplicate messages when the same
    trial gets created twice (e.g., client sent the command again, or
    both the bot flow and the public /teste form fired for the same phone).
    """
    send_at = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()
    ctx_json = json.dumps(context)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id FROM scheduled_reminders "
            "WHERE phone = ? AND event_key = ? AND sent = 0 "
            "ORDER BY created_at DESC LIMIT 1",
            (phone, event_key),
        )
        existing = await cur.fetchone()
        if existing:
            await db.execute(
                "UPDATE scheduled_reminders SET send_at = ?, context = ? "
                "WHERE id = ?",
                (send_at, ctx_json, existing["id"]),
            )
            await db.commit()
            logger.info(
                "Reminder dedup: updating existing pending %s for %s (id=%s) "
                "instead of inserting duplicate",
                event_key, phone, existing["id"],
            )
            return

        await db.execute(
            "INSERT INTO scheduled_reminders (id, event_key, phone, context, send_at, sent, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (
                str(uuid.uuid4()),
                event_key,
                phone,
                ctx_json,
                send_at,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
    logger.info("Scheduled reminder %s for %s at %s", event_key, phone, send_at)


async def process_due():
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM scheduled_reminders WHERE sent = 0 AND send_at <= ? ORDER BY send_at",
            (now,),
        )
        rows = [dict(r) for r in await cur.fetchall()]

    for r in rows:
        try:
            ctx = json.loads(r["context"])
            ok = await send_notification(r["event_key"], r["phone"], ctx)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE scheduled_reminders SET sent = ? WHERE id = ?",
                    (1 if ok else 2, r["id"]),
                )
                await db.commit()
            if ok:
                logger.info("Reminder sent: %s -> %s", r["event_key"], r["phone"])
        except Exception:
            logger.exception("Failed to send reminder %s", r["id"])


async def reminder_loop():
    """Runs forever, checking for due reminders every 30 seconds."""
    while True:
        try:
            await process_due()
        except Exception:
            logger.exception("reminder_loop error")
        await asyncio.sleep(30)



async def cancel_pending_for_phone(phone: str, event_keys: list[str] | None = None) -> int:
    """Cancel any pending reminders + queued deliveries for the given phone.

    Called when a trial user successfully pays — we don't want to keep firing
    `trial_1h_reminder` / `trial_expired` messages telling them the test is
    about to end when they've already renewed.

    Cancels TWO layers:
      1. `scheduled_reminders` (sent=0) — the scheduler won't pick them up
      2. `notification_deliveries` (status='pending') — the queue won't send them

    Returns the total number of rows cancelled across both tables.
    """
    if not phone:
        return 0
    total = 0
    async with aiosqlite.connect(DB_PATH) as db:
        # Layer 1: scheduled_reminders (before they enter the queue)
        if event_keys:
            placeholders = ",".join("?" for _ in event_keys)
            query = (
                f"UPDATE scheduled_reminders SET sent = 3 "
                f"WHERE sent = 0 AND phone = ? AND event_key IN ({placeholders})"
            )
            params = (phone, *event_keys)
        else:
            query = (
                "UPDATE scheduled_reminders SET sent = 3 "
                "WHERE sent = 0 AND phone = ?"
            )
            params = (phone,)
        cur = await db.execute(query, params)
        total += cur.rowcount

        # Layer 2: notification_deliveries pending (already in the queue but
        # not yet sent) — mark as cancelled so the queue loop skips them.
        # We reuse status='failed_permanent' + last_error='cancelled_by_pay'
        # so the audit trail stays clean.
        if event_keys:
            placeholders = ",".join("?" for _ in event_keys)
            query = (
                f"UPDATE notification_deliveries "
                f"SET status='failed_permanent', last_error='cancelled_by_payment', "
                f"    next_retry_at=NULL "
                f"WHERE status='pending' AND phone = ? AND event_key IN ({placeholders})"
            )
            params = (phone, *event_keys)
        else:
            query = (
                "UPDATE notification_deliveries "
                "SET status='failed_permanent', last_error='cancelled_by_payment', "
                "    next_retry_at=NULL "
                "WHERE status='pending' AND phone = ?"
            )
            params = (phone,)
        cur = await db.execute(query, params)
        total += cur.rowcount
        await db.commit()

    if total > 0:
        logger.info(
            "Cancelled %d pending reminder(s)+deliverie(s) for %s (event_keys=%s)",
            total, phone, event_keys,
        )
    return total
