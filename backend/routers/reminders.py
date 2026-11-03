"""View / manage pending scheduled reminders."""
import aiosqlite
import json
from fastapi import APIRouter, HTTPException

from database import DB_PATH

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


@router.get("")
async def list_reminders(limit: int = 200):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM scheduled_reminders ORDER BY send_at DESC LIMIT ?",
            (limit,),
        )
        rows = []
        for r in await cur.fetchall():
            d = dict(r)
            try:
                d["context"] = json.loads(d["context"])
            except Exception:
                pass
            rows.append(d)
        return rows


@router.delete("/{reminder_id}")
async def cancel_reminder(reminder_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE scheduled_reminders SET sent = 3 WHERE id = ? AND sent = 0",
            (reminder_id,),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Reminder not found or already sent")
        await db.commit()
    return {"success": True}
