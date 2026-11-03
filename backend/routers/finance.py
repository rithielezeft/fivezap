"""Financeiro — monthly finance summary for the admin Pagamentos page."""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite
from fastapi import APIRouter, HTTPException

from database import DB_PATH
from services.finance_report import credits_for
from services.payment_accounts import RECEIVED_STATUSES as RECEIVED

router = APIRouter(prefix="/api/finance", tags=["finance"])
logger = logging.getLogger(__name__)


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
        if not (2000 <= y <= 2100 and 1 <= m <= 12):
            raise ValueError
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


async def _load_rows(where: str = "", params: tuple = ()) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT p.id, p.customer_id, p.plan_months, p.amount_cents, p.status, p.paid_at, "
            "p.created_at, p.coupon_code, p.discount_percent, p.original_amount_cents, p.receipt_url, "
            "p.infinitepay_url, p.clovers, c.painel_username, c.name FROM payments p "
            "LEFT JOIN customers c ON c.id = p.customer_id " + where + " ORDER BY p.created_at DESC",
            params,
        )
        rows = [dict(r) for r in await cur.fetchall()]
    logins = await _logins()
    for r in rows:
        r["login"] = r.get("painel_username") or logins.get(str(r["customer_id"])) or r["customer_id"]
        r["_paid"] = _parse(r["paid_at"]) or (_parse(r["created_at"]) if r["status"] in RECEIVED else None)
        r["_created"] = _parse(r["created_at"])
    return rows


async def paid_rows_for(month: str) -> list:
    from services.scheduler import _get_display_tz
    tz = await _get_display_tz()
    start, end, _ = _month_bounds(month, tz)
    rows = [r for r in await _load_rows() if r["status"] in RECEIVED and r["_paid"] and start <= r["_paid"].astimezone(tz) < end]
    for r in rows:
        r["_paid"] = r["_paid"].astimezone(tz)
    return sorted(rows, key=lambda r: r["_paid"])


@router.get("/customer/{customer_id}/payments")
async def customer_payments(customer_id: str):
    """All payments + receipts of one customer (Financeiro → Comprovantes)."""
    rows = await _load_rows("WHERE p.customer_id = ?", (customer_id,))
    return {"customer_id": customer_id, "login": rows[0]["login"] if rows else customer_id,
            "payments": [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
            "total_paid_cents": sum(r["amount_cents"] for r in rows if r["status"] in RECEIVED)}


@router.get("/report.pdf")
async def report_pdf(month: str):
    from fastapi.responses import Response
    from services.finance_report import build_pdf
    _month_bounds(month, timezone.utc)
    pdf = await build_pdf(month)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="financeiro-{month}.pdf"'})


@router.post("/report/send")
async def report_send(month: str):
    from services.finance_report import send_report
    _month_bounds(month, timezone.utc)
    return await send_report(month, force=True)


async def _raffle_summary(paid: list, start, end) -> dict:
    """Clover sales in the month vs. painel credits spent on the prizes drawn in the month."""
    from services import raffle
    from services.mongo_store import _get_db
    cfg = await raffle.config()
    clovers = sum(int(r.get("clovers") or 0) for r in paid)
    s_utc, e_utc = start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()
    draws = []
    try:
        async for d in _get_db().raffle_draws.find({"status": "drawn", "created_at": {"$gte": s_utc, "$lt": e_utc}},
                                                   {"sequence": 0}).sort("created_at", 1):
            draws.append({"round_id": d["_id"], "winner": (d.get("winner") or {}).get("name"),
                          "prize_months": int(d.get("prize_months") or 1), "renewed": bool(d.get("renewed")),
                          "drawn_at": d.get("created_at")})
    except Exception:
        logger.exception("raffle draws lookup failed")
    cost = await credits_for([{"plan_months": d["prize_months"], "amount_cents": 0} for d in draws])
    revenue = clovers * cfg["clover_cents"]
    return {"clovers": clovers, "clover_cents": cfg["clover_cents"], "revenue_cents": revenue,
            "draws": draws, "cost_credits": cost["used"], "cost_cents": cost["cost_cents"],
            "unit_cost_cents": cost["unit_cost_cents"], "profit_cents": revenue - cost["cost_cents"]}


@router.get("/summary")
async def summary(month: Optional[str] = None):
    from services.scheduler import _get_display_tz
    tz = await _get_display_tz()
    now = datetime.now(timezone.utc).astimezone(tz)
    month = month or now.strftime("%Y-%m")
    start, end, prev_start = _month_bounds(month, tz)

    rows = await _load_rows()

    def in_range(d, a, b):
        return d is not None and a <= d.astimezone(tz) < b

    paid = [r for r in rows if r["status"] in RECEIVED and in_range(r["_paid"], start, end)]
    prev_paid = [r for r in rows if r["status"] in RECEIVED and in_range(r["_paid"], prev_start, start)]
    created = [r for r in rows if in_range(r["_created"], start, end)]
    pending = [r for r in created if r["status"] == "pending"]
    failed = [r for r in created if r["status"] not in (*RECEIVED, "pending")]
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = [r for r in rows if r["status"] in RECEIVED and in_range(r["_paid"], today0, today0 + timedelta(days=1))]
    week = [r for r in rows if r["status"] in RECEIVED and in_range(r["_paid"], today0 - timedelta(days=6), today0 + timedelta(days=1))]

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
        "conversion_percent": round(sum(1 for r in created if r["status"] in RECEIVED) * 100 / len(created), 1) if created else None,
        "coupons": {"count": sum(1 for r in paid if r.get("coupon_code")),
                    "discount_cents": sum(max(0, (r.get("original_amount_cents") or r["amount_cents"]) - r["amount_cents"]) for r in paid)},
        "credits": await credits_for(paid),
        "raffle": await _raffle_summary(paid, start, end),
        "by_period": by_period,
        "daily": daily,
        "top_clients": top_clients,
        "latest": [clean(r) for r in latest],
    }
