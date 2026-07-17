"""Notification templates CRUD (vencimento, renovação, teste)."""
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import aiosqlite

from database import DB_PATH
from models import now_iso

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


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
        return _row(await cur.fetchone())
