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
    """Schedule a notification to be sent after `delay_seconds`."""
    send_at = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO scheduled_reminders (id, event_key, phone, context, send_at, sent, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (
                str(uuid.uuid4()),
                event_key,
                phone,
                json.dumps(context),
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
