"""Notification templates CRUD (vencimento, renovação, teste)."""
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import aiosqlite

from database import DB_PATH
from models import now_iso

router = APIRouter(prefix="/api/notifications", tags=["notifications"])
logger = logging.getLogger(__name__)


class NotifTemplate(BaseModel):
    id: str
    event_key: str
    title: str
    body: str
    image_url: Optional[str] = ""
    enabled: bool = True
    updated_at: str


class NotifUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    image_url: Optional[str] = None
    enabled: Optional[bool] = None


def _row(r) -> NotifTemplate:
    d = dict(r)
    d["enabled"] = bool(d["enabled"])
    d["image_url"] = d.get("image_url") or ""
    return NotifTemplate(**d)


@router.get("", response_model=List[NotifTemplate])
async def list_notifications():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM notification_templates ORDER BY event_key")
        return [_row(r) for r in await cur.fetchall()]


# ---------------------------------------------------------------------------
# Delivery-tracking endpoints (per-message send status + manual retry)
# MUST be declared BEFORE /{event_key} — FastAPI matches routes in order,
# so /deliveries would otherwise be captured as event_key="deliveries".
# ---------------------------------------------------------------------------

@router.get("/deliveries")
async def list_deliveries(limit: int = 50, customer_id: Optional[str] = None,
                          status: Optional[str] = None, phone: Optional[str] = None,
                          event_key: Optional[str] = None):
    """List recent notification deliveries (most-recent first)."""
    limit = max(1, min(int(limit), 200))
    where: List[str] = []
    params: list = []
    if customer_id:
        where.append("customer_id = ?")
        params.append(customer_id)
    if status:
        where.append("status = ?")
        params.append(status)
    if phone:
        where.append("phone LIKE ?")
        params.append(f"%{phone}%")
    if event_key:
        where.append("event_key = ?")
        params.append(event_key)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            f"SELECT * FROM notification_deliveries {where_sql} "
            f"ORDER BY created_at DESC LIMIT ?",
            params,
        )
        rows = [dict(r) for r in await cur.fetchall()]

        cur = await db.execute(
            "SELECT status, COUNT(*) as c FROM notification_deliveries GROUP BY status"
        )
        counts = {r["status"]: r["c"] for r in await cur.fetchall()}

        cur = await db.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN blocked_at >= datetime('now', '-24 hours') THEN 1 ELSE 0 END) as last_24h "
            "FROM notification_dedup_log"
        )
        dedup_stats = dict(await cur.fetchone() or {"total": 0, "last_24h": 0})
    return {
        "deliveries": rows,
        "counts_by_status": counts,
        "dedup_stats": {
            "total_blocked": int(dedup_stats.get("total") or 0),
            "blocked_24h": int(dedup_stats.get("last_24h") or 0),
        },
    }


@router.get("/dedup-log")
async def list_dedup_log(limit: int = 100, phone: Optional[str] = None,
                         reason: Optional[str] = None):
    """List duplicate-notification blocks (anti-spam system activity)."""
    limit = max(1, min(int(limit), 500))
    where: List[str] = []
    params: list = []
    if phone:
        where.append("phone LIKE ?")
        params.append(f"%{phone}%")
    if reason:
        where.append("reason = ?")
        params.append(reason)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            f"SELECT * FROM notification_dedup_log {where_sql} "
            f"ORDER BY blocked_at DESC LIMIT ?",
            params,
        )
        rows = [dict(r) for r in await cur.fetchall()]

        cur = await db.execute(
            "SELECT reason, COUNT(*) as c FROM notification_dedup_log GROUP BY reason"
        )
        by_reason = {r["reason"]: r["c"] for r in await cur.fetchall()}

    return {"blocks": rows, "counts_by_reason": by_reason}


@router.post("/deliveries/{delivery_id}/retry")
async def retry_delivery(delivery_id: str):
    """Force an immediate retry of a delivery."""
    from services.delivery_queue import _attempt

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM notification_deliveries WHERE id = ?", (delivery_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, f"Delivery {delivery_id} not found")

    ok = await _attempt(delivery_id)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT status, attempts, last_error, sent_at, next_retry_at "
            "FROM notification_deliveries WHERE id = ?",
            (delivery_id,),
        )
        updated = dict(await cur.fetchone())
    return {"ok": ok, "delivery": updated}


@router.get("/{event_key}", response_model=NotifTemplate)
async def get_notification(event_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM notification_templates WHERE event_key = ?", (event_key,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Notification template not found")
        return _row(row)


@router.put("/{event_key}", response_model=NotifTemplate)
async def update_notification(event_key: str, payload: NotifUpdate):
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])
    if not fields:
        raise HTTPException(400, "No fields to update")
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [event_key]

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(f"UPDATE notification_templates SET {sets} WHERE event_key = ?", values)
        if cur.rowcount == 0:
            raise HTTPException(404, "Notification template not found")
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM notification_templates WHERE event_key = ?", (event_key,))
        result = _row(await cur.fetchone())

    # Mirror to Atlas so multi-instance deployments share the same templates.
    try:
        from services import mongo_store
        await mongo_store.upsert_template(result.model_dump())
        from services import config_sync
        await config_sync.save_notification(result.model_dump())
    except Exception:
        logger.exception("mongo template sync failed (non-fatal)")
    return result


@router.post("/{event_key}/restore-defaults")
async def restore_default_template(event_key: str):
    """Restore this notification template to the shipping default (from
    services.default_templates.DEFAULT_TEMPLATES). Useful when the admin
    wants to pick up new `{user}` variables or other improvements.

    Note: OVERWRITES the current body/title/image_url. `enabled` is preserved.
    """
    from services.default_templates import DEFAULT_TEMPLATES_BY_EVENT
    default = DEFAULT_TEMPLATES_BY_EVENT.get(event_key)
    if not default:
        raise HTTPException(404, f"No default template registered for '{event_key}'")

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE notification_templates SET title = ?, body = ?, image_url = ? "
            "WHERE event_key = ?",
            (default["title"], default["body"], default["image_url"], event_key),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, f"Template '{event_key}' not found in DB")
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM notification_templates WHERE event_key = ?", (event_key,)
        )
        result = _row(await cur.fetchone())

    try:
        from services import mongo_store
        await mongo_store.upsert_template(result.model_dump())
        from services import config_sync
        await config_sync.save_notification(result.model_dump())
    except Exception:
        logger.exception("mongo template sync (restore) failed (non-fatal)")

    return result




