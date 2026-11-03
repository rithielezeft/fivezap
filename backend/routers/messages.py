"""Messages history."""
from fastapi import APIRouter
from typing import List
import aiosqlite

from database import DB_PATH
from models import Message

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("", response_model=List[Message])
async def list_messages(phone: str = None, limit: int = 200):
    query = "SELECT * FROM messages"
    params = []
    if phone:
        query += " WHERE phone = ?"
        params.append("".join(c for c in phone if c.isdigit()))
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(query, params)
        return [Message(**dict(r)) for r in await cur.fetchall()]


@router.get("/conversations")
async def list_conversations():
    """Return list of unique phones with last message + counts."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT phone,
                   MAX(timestamp) as last_ts,
                   (SELECT message FROM messages m2 WHERE m2.phone = m.phone ORDER BY timestamp DESC LIMIT 1) as last_msg,
                   COUNT(*) as msg_count
            FROM messages m
            GROUP BY phone
            ORDER BY last_ts DESC
            LIMIT 100
            """
        )
        convos = [dict(r) for r in await cur.fetchall()]
        # attach customer name
        for c in convos:
            cur = await db.execute("SELECT name, id FROM customers WHERE whatsapp = ?", (c["phone"],))
            row = await cur.fetchone()
            if row:
                c["customer_name"] = row["name"]
                c["customer_id"] = row["id"]
        return convos
