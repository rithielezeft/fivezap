"""Delivery-queue for outbound WhatsApp messages with automatic retry.

Every notification (template + hardcoded fallback + admin alert) is recorded
here so we always know whether the client received the message. Failed
deliveries are retried every 10s until `max_attempts` is reached.

Design principles:
- Fire-and-forget from callers: they see `pending` immediately and never block.
- Idempotent retries: same delivery row is updated in-place.
- Persistent: survives backend restarts (unlike in-memory queues).
- Observable: each delivery has a status + attempts + last_error visible via
  the /api/notifications/deliveries endpoint.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiosqlite

import database
from models import new_id, now_iso
from services import whatsapp_client

logger = logging.getLogger(__name__)

RETRY_INTERVAL_SECONDS = 10
LOOP_TICK_SECONDS = 5   # scan the queue every 5s → up to +5s of latency
DEFAULT_MAX_ATTEMPTS = 5


async def enqueue(
    event_key: str,
    phone: str,
    body: str,
    image_url: Optional[str] = None,
    customer_id: Optional[str] = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    typing_ms: int = 0,
) -> str:
    """Record a new delivery and attempt to send it immediately.

    Returns the delivery id. If the immediate send succeeds, status='sent'.
    If it fails, status='pending' and the retry loop will pick it up.

    `typing_ms` is stored in `last_error` field prefixed with `__typing_ms__:`
    so retries also honour the typing indicator without changing the schema.
    Actual meaningful `last_error` is written on failure, overwriting this.
    """
    did = new_id()
    created_at = now_iso()
    # Encode typing_ms into a lightweight side-channel: we keep a "hint" in
    # last_error until first send happens; overwritten on real error.
    hint = f"__typing_ms__:{int(typing_ms)}" if typing_ms and typing_ms > 0 else None
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "INSERT INTO notification_deliveries "
            "(id, event_key, phone, body, image_url, customer_id, status, "
            " attempts, max_attempts, next_retry_at, last_error, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?)",
            (did, event_key, phone, body, image_url, customer_id, max_attempts,
             created_at, hint, created_at),
        )
        await db.commit()

    # Fast path: attempt immediately so happy-case latency is unchanged.
    await _attempt(did)
    return did


async def _attempt(delivery_id: str) -> bool:
    """Try to send this delivery once. Update its row accordingly."""
    async with aiosqlite.connect(database.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM notification_deliveries WHERE id = ?", (delivery_id,)
        )
        row = await cur.fetchone()
        if not row:
            return False
        d = dict(row)

    if d["status"] == "sent":
        return True
    if d["status"] == "failed_permanent":
        return False

    attempts = int(d["attempts"]) + 1
    # Extract typing_ms hint from last_error (set at enqueue time), if any.
    typing_ms = 0
    le = (d.get("last_error") or "")
    if le.startswith("__typing_ms__:"):
        try:
            typing_ms = int(le.split(":", 1)[1])
        except Exception:
            typing_ms = 0
    try:
        await whatsapp_client.send_message(
            d["phone"], d["body"], image_url=d["image_url"] or None,
            typing_ms=typing_ms,
        )
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "UPDATE notification_deliveries "
                "SET status = 'sent', attempts = ?, sent_at = ?, "
                "    last_error = NULL, next_retry_at = NULL "
                "WHERE id = ?",
                (attempts, now_iso(), delivery_id),
            )
            await db.commit()
        logger.info(
            "delivery id=%s event=%s phone=%s → SENT (attempt %d)",
            delivery_id, d["event_key"], d["phone"], attempts,
        )
        return True
    except Exception as e:
        err = str(e)[:500]
        max_attempts = int(d["max_attempts"])
        if attempts >= max_attempts:
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute(
                    "UPDATE notification_deliveries "
                    "SET status = 'failed_permanent', attempts = ?, "
                    "    last_error = ?, next_retry_at = NULL "
                    "WHERE id = ?",
                    (attempts, err, delivery_id),
                )
                await db.commit()
            logger.error(
                "delivery id=%s event=%s phone=%s → FAILED_PERMANENT after %d attempts: %s",
                delivery_id, d["event_key"], d["phone"], attempts, err,
            )
            # Best-effort admin alert about the permanent failure — don't
            # loop through the queue (that would create infinite recursion
            # on a stuck WA service). Send directly, ignoring failures.
            try:
                from database import get_setting
                admin = (await get_setting("admin_whatsapp") or "").strip()
                if admin and admin != d["phone"]:
                    await whatsapp_client.send_message(
                        admin,
                        "⚠️ *Falha permanente em envio*\n\n"
                        f"Notificação `{d['event_key']}` para {d['phone']} "
                        f"não pôde ser entregue após {attempts} tentativas.\n"
                        f"Motivo: {err[:200]}"
                    )
            except Exception:
                pass
        else:
            next_at = (datetime.now(timezone.utc) + timedelta(seconds=RETRY_INTERVAL_SECONDS)).isoformat()
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute(
                    "UPDATE notification_deliveries "
                    "SET status = 'pending', attempts = ?, last_error = ?, next_retry_at = ? "
                    "WHERE id = ?",
                    (attempts, err, next_at, delivery_id),
                )
                await db.commit()
            logger.warning(
                "delivery id=%s event=%s phone=%s → failed (attempt %d/%d), retrying in %ds: %s",
                delivery_id, d["event_key"], d["phone"], attempts, max_attempts,
                RETRY_INTERVAL_SECONDS, err,
            )
        return False


async def retry_loop_iteration() -> int:
    """Scan for pending deliveries whose next_retry_at has arrived, and try them.

    Returns the count of deliveries attempted.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(database.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id FROM notification_deliveries "
            "WHERE status = 'pending' AND (next_retry_at IS NULL OR next_retry_at <= ?) "
            "ORDER BY created_at ASC LIMIT 50",
            (now,),
        )
        pending = [dict(r)["id"] for r in await cur.fetchall()]

    for did in pending:
        try:
            await _attempt(did)
        except Exception:
            logger.exception("retry_loop_iteration crashed on delivery=%s", did)
    return len(pending)


_stop_event: Optional[asyncio.Event] = None


async def retry_loop():
    """Background task: scan and retry every LOOP_TICK_SECONDS seconds."""
    global _stop_event
    _stop_event = asyncio.Event()
    logger.info("delivery_queue retry_loop started (tick=%ds, retry=%ds)",
                LOOP_TICK_SECONDS, RETRY_INTERVAL_SECONDS)
    while not _stop_event.is_set():
        try:
            await retry_loop_iteration()
        except Exception:
            logger.exception("retry_loop iteration crashed (keeping loop alive)")
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=LOOP_TICK_SECONDS)
        except asyncio.TimeoutError:
            pass


def stop_retry_loop():
    if _stop_event:
        _stop_event.set()
