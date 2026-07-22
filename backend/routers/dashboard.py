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


@router.get("/attribution")
async def attribution(days: int = 30):
    """Which message/ref bucket drives the most paid conversions?

    Buckets pagos vs criados no período. Deduzimos "conversion_rate" (paid /
    total). Ordenado por receita descendente.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT COALESCE(NULLIF(ref_bucket, ''), 'direct') as bucket,"
            " COUNT(*) as total,"
            " SUM(CASE WHEN status = 'paid' THEN 1 ELSE 0 END) as paid_count,"
            " COALESCE(SUM(CASE WHEN status = 'paid' THEN amount_cents ELSE 0 END), 0) as revenue_cents"
            " FROM payments WHERE created_at >= ?"
            " GROUP BY bucket ORDER BY revenue_cents DESC",
            (since,),
        )
        rows = [dict(r) for r in await cur.fetchall()]
    for r in rows:
        r["conversion_rate"] = round(r["paid_count"] / r["total"] * 100, 1) if r["total"] else 0.0
    return {"since": since, "buckets": rows}


@router.get("/revenue-by-day")
async def revenue_by_day(days: int = 14):
    """Revenue and paid-count per day for the last N days."""
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT SUBSTR(paid_at, 1, 10) as day,"
            " COUNT(*) as count,"
            " COALESCE(SUM(amount_cents), 0) as revenue_cents"
            " FROM payments WHERE status = 'paid' AND paid_at >= ?"
            " GROUP BY day ORDER BY day",
            (since,),
        )
        rows = [dict(r) for r in await cur.fetchall()]
    return {"days": rows}


@router.get("/balances")
async def balances():
    """External balances: painel.fun credits + 2Captcha wallet.

    Both are best-effort — if a provider is unreachable or misconfigured,
    the field comes back as {'error': '...'} instead of crashing the page.
    """
    from services import painel
    from database import get_setting
    import httpx

    result: dict = {}

    # 2Captcha balance via /res.php?action=getbalance
    try:
        api_key = await get_setting("twocaptcha_key")
        if not api_key:
            result["twocaptcha"] = {"error": "key not configured"}
        else:
            async with httpx.AsyncClient(timeout=8) as c:
                resp = await c.get(
                    "https://2captcha.com/res.php",
                    params={"key": api_key, "action": "getbalance", "json": 1},
                )
                data = resp.json()
                if data.get("status") == 1:
                    result["twocaptcha"] = {
                        "balance_usd": float(data.get("request") or 0),
                        "currency": "USD",
                    }
                else:
                    result["twocaptcha"] = {"error": data.get("request") or "unknown"}
    except Exception as e:
        result["twocaptcha"] = {"error": str(e)[:120]}

    # painel.fun balance — best-effort. Endpoint depends on the panel build;
    # we probe two known variants and give up gracefully.
    try:
        balance = await painel.get_reseller_balance()
        result["painel"] = balance if isinstance(balance, dict) else {"balance": balance}
    except Exception as e:
        result["painel"] = {"error": str(e)[:120]}

    return result
