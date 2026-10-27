"""Financeiro — monthly finance summary for the admin Pagamentos page."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite
from fastapi import APIRouter, HTTPException

from database import DB_PATH

router = APIRouter(prefix="/api/finance", tags=["finance"])


def _parse(iso: Optional[str]):
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _month_bounds(month: str, tz):
    try:
        y, m = (int(x) for x in month.split("-"))
        start = datetime(y, m, 1, tzinfo=tz)
    except Exception:
        raise HTTPException(400, "month deve ser YYYY-MM")
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=tz)
    prev = datetime(y - (m == 1), 12 if m == 1 else m - 1, 1, tzinfo=tz)
    return start, end, prev


async def _logins() -> dict:
    try:
        from routers.painel_users import _read_cache
        users, _ = await _read_cache()
    except Exception:
        return {}
    return {
        str(u.get("id") or u.get("user_id") or u.get("username") or ""): u.get("username") or u.get("login")
        for u in users or []
    }


@router.get("/summary")
async def summary(month: Optional[str] = None):
    from services.scheduler import _get_display_tz
    tz = await _get_display_tz()
    now = datetime.now(timezone.utc).astimezone(tz)
    month = month or now.strftime("%Y-%m")
    start, end, prev_start = _month_bounds(month, tz)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT p.id, p.customer_id, p.plan_months, p.amount_cents, p.status, p.paid_at, "
            "p.created_at, p.coupon_code, p.discount_percent, p.original_amount_cents, p.receipt_url, "
            "c.painel_username, c.name FROM payments p LEFT JOIN customers c ON c.id = p.customer_id"
        )
        rows = [dict(r) for r in await cur.fetchall()]

    logins = await _logins()
    for r in rows:
        r["login"] = r.get("painel_username") or logins.get(str(r["customer_id"])) or r["customer_id"]
        r["_paid"] = _parse(r["paid_at"]) or (_parse(r["created_at"]) if r["status"] == "paid" else None)
        r["_created"] = _parse(r["created_at"])

    def in_range(d, a, b):
        return d is not None and a <= d.astimezone(tz) < b

    paid = [r for r in rows if r["status"] == "paid" and in_range(r["_paid"], start, end)]
    prev_paid = [r for r in rows if r["status"] == "paid" and in_range(r["_paid"], prev_start, start)]
    created = [r for r in rows if in_range(r["_created"], start, end)]
    pending = [r for r in created if r["status"] == "pending"]
    failed = [r for r in created if r["status"] not in ("paid", "pending")]
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = [r for r in rows if r["status"] == "paid" and in_range(r["_paid"], today0, today0 + timedelta(days=1))]
    week = [r for r in rows if r["status"] == "paid" and in_range(r["_paid"], today0 - timedelta(days=6), today0 + timedelta(days=1))]

    total = sum(r["amount_cents"] for r in paid)
    prev_total = sum(r["amount_cents"] for r in prev_paid)

    days_in_month = (end - start).days
    daily = [{"day": (start + timedelta(days=i)).strftime("%d/%m"), "revenue_cents": 0, "count": 0}
             for i in range(days_in_month)]
    for r in paid:
        i = (r["_paid"].astimezone(tz).date() - start.date()).days
        if 0 <= i < days_in_month:
            daily[i]["revenue_cents"] += r["amount_cents"]
            daily[i]["count"] += 1

    by_period = {str(m): 0 for m in (1, 3, 6, 12)}
    for r in paid:
        k = str(r["plan_months"])
        by_period[k] = by_period.get(k, 0) + 1

    tops = defaultdict(lambda: {"amount_cents": 0, "count": 0, "login": None})
    for r in paid:
        t = tops[r["customer_id"]]
        t["amount_cents"] += r["amount_cents"]
        t["count"] += 1
        t["login"] = r["login"]
    top_clients = sorted(tops.values(), key=lambda t: -t["amount_cents"])[:6]

    latest = sorted(paid, key=lambda r: r["_paid"], reverse=True)[:10]
    clean = lambda r: {k: v for k, v in r.items() if not k.startswith("_")}  # noqa: E731

    return {
        "month": month,
        "received": {"amount_cents": total, "count": len(paid)},
        "previous_month": {"amount_cents": prev_total,
                           "delta_percent": round((total - prev_total) * 100 / prev_total, 1) if prev_total else None},
        "today": {"amount_cents": sum(r["amount_cents"] for r in today), "count": len(today)},
        "week": {"amount_cents": sum(r["amount_cents"] for r in week), "count": len(week)},
        "pending": {"amount_cents": sum(r["amount_cents"] for r in pending), "count": len(pending)},
        "failed": {"amount_cents": sum(r["amount_cents"] for r in failed), "count": len(failed)},
        "ticket_cents": total // len(paid) if paid else 0,
        "conversion_percent": round(sum(1 for r in created if r["status"] == "paid") * 100 / len(created), 1) if created else None,
        "coupons": {"count": sum(1 for r in paid if r.get("coupon_code")),
                    "discount_cents": sum(max(0, (r.get("original_amount_cents") or r["amount_cents"]) - r["amount_cents"]) for r in paid)},
        "by_period": by_period,
        "daily": daily,
        "top_clients": top_clients,
        "latest": [clean(r) for r in latest],
    }
