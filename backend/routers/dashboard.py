"""Dashboard metrics + activity."""
from fastapi import APIRouter
from datetime import datetime, timezone, timedelta
import aiosqlite

from database import DB_PATH

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
async def stats():
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now - timedelta(days=7)).isoformat()
    soon = (now + timedelta(days=3)).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Trials today
        cur = await db.execute("SELECT COUNT(*) as c FROM trials WHERE created_at >= ?", (today_start,))
        trials_today = (await cur.fetchone())["c"]
        # Total customers
        cur = await db.execute("SELECT COUNT(*) as c FROM customers")
        total_customers = (await cur.fetchone())["c"]
        # Active customers
        cur = await db.execute("SELECT COUNT(*) as c FROM customers WHERE status = 'active'")
        active_customers = (await cur.fetchone())["c"]
        # Expiring in <= 3 days
        cur = await db.execute(
            "SELECT COUNT(*) as c FROM customers WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at != '' AND expires_at <= ?",
            (soon,),
        )
        expiring_soon = (await cur.fetchone())["c"]
        # Revenue this week (paid)
        cur = await db.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) as t FROM payments WHERE status = 'paid' AND paid_at >= ?",
            (week_start,),
        )
        revenue_week_cents = (await cur.fetchone())["t"]
        # By system type
        cur = await db.execute("SELECT system_type, COUNT(*) as c FROM customers GROUP BY system_type")
        by_type = {r["system_type"]: r["c"] for r in await cur.fetchall()}
        # Trials last 7 days daily
        cur = await db.execute(
            "SELECT SUBSTR(created_at, 1, 10) as day, COUNT(*) as c FROM trials WHERE created_at >= ? GROUP BY day ORDER BY day",
            (week_start,),
        )
        trials_by_day = [dict(r) for r in await cur.fetchall()]

    return {
        "trials_today": trials_today,
        "total_customers": total_customers,
        "active_customers": active_customers,
        "expiring_soon": expiring_soon,
        "revenue_week_cents": revenue_week_cents,
        "by_system_type": by_type,
        "trials_by_day": trials_by_day,
    }


@router.get("/activity")
async def activity(limit: int = 50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in await cur.fetchall()]
