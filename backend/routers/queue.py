"""Fila de envio — live view of everything about to be sent on WhatsApp,
with cancel-all / cancel-selected."""
import json
from typing import List, Optional

import aiosqlite
from fastapi import APIRouter
from pydantic import BaseModel

from database import DB_PATH
from services import scheduler
from services.upcoming import TITLES

router = APIRouter(prefix="/api/queue", tags=["queue"])


def _title(ev: str) -> str:
    if ev.startswith("admin_alert"):
        return "Alerta para o admin"
    return TITLES.get(ev, ev)


async def _names_by_customer() -> dict:
    try:
        from routers.painel_users import _read_cache
        users, _ = await _read_cache()
    except Exception:
        return {}
    out = {}
    for u in users or []:
        uid = str(u.get("id") or u.get("user_id") or u.get("username") or "")
        out[uid] = {"name": u.get("full_name") or u.get("name") or u.get("username"), "login": u.get("username")}
    return out


@router.get("")
async def get_queue(history_limit: int = 30):
    names = await _names_by_customer()
    run = scheduler.RUN_STATE
    run_items = [
        {k: v for k, v in it.items() if k not in ("ctx", "key")} | {"kind": "run", "title": _title(it["event_key"])}
        for it in run.get("items", [])
    ]

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, event_key, phone, body, image_url, customer_id, status, attempts, max_attempts, "
            "next_retry_at, last_error, created_at, sent_at FROM notification_deliveries "
            "WHERE status IN ('pending', 'sending') ORDER BY created_at"
        )
        deliveries = [dict(r) for r in await cur.fetchall()]
        cur = await db.execute(
            "SELECT id, event_key, phone, body, image_url, customer_id, status, attempts, max_attempts, "
            "next_retry_at, last_error, created_at, sent_at FROM notification_deliveries "
            "WHERE status NOT IN ('pending', 'sending') ORDER BY COALESCE(sent_at, created_at) DESC LIMIT ?",
            (max(1, min(history_limit, 200)),),
        )
        history = [dict(r) for r in await cur.fetchall()]
        cur = await db.execute("SELECT * FROM scheduled_reminders WHERE sent = 0 ORDER BY send_at")
        reminders = [dict(r) for r in await cur.fetchall()]
        cur = await db.execute(
            "SELECT status, COUNT(*) c FROM notification_deliveries "
            "WHERE created_at >= datetime('now', '-1 day') GROUP BY status"
        )
        counts_24h = {r["status"]: r["c"] for r in await cur.fetchall()}

    for d in deliveries + history:
        d["kind"] = "delivery"
        d["title"] = _title(d["event_key"])
        if (d.get("last_error") or "").startswith("__"):
            d["last_error"] = None
        n = names.get(str(d.get("customer_id") or ""), {})
        d["name"], d["login"] = n.get("name"), n.get("login")

    from services.notifier import get_template, render
    rem_items = []
    for r in reminders:
        try:
            ctx = json.loads(r["context"] or "{}")
        except Exception:
            ctx = {}
        tpl = await get_template(r["event_key"])
        rem_items.append({
            "id": r["id"], "kind": "reminder", "event_key": r["event_key"], "title": _title(r["event_key"]),
            "phone": r["phone"], "name": ctx.get("name"), "login": ctx.get("user"),
            "eta": r["send_at"], "status": "scheduled" if tpl else "disabled",
            "body": render(tpl["body"], ctx) if tpl else None,
            "image_url": (tpl or {}).get("image_url") or None,
        })

    waiting_run = sum(1 for i in run_items if i["status"] == "waiting")
    return {
        "run": {k: v for k, v in run.items() if k != "items"} | {"items": run_items},
        "deliveries": deliveries,
        "reminders": rem_items,
        "history": history,
        "stats": {
            "waiting_run": waiting_run,
            "in_queue": len(deliveries),
            "retrying": sum(1 for d in deliveries if d["status"] == "pending" and d["attempts"] > 0),
            "scheduled_reminders": len(rem_items),
            "total_pending": waiting_run + len(deliveries) + len(rem_items),
            "last_24h": counts_24h,
        },
    }


class CancelItem(BaseModel):
    kind: str  # run | delivery | reminder
    id: str


class CancelRequest(BaseModel):
    all: bool = False
    items: Optional[List[CancelItem]] = None


@router.post("/cancel")
async def cancel(req: CancelRequest):
    items = req.items or []
    by_kind = {k: [i.id for i in items if i.kind == k] for k in ("run", "delivery", "reminder")}
    result = {"run": 0, "delivery": 0, "reminder": 0}

    result["run"] = scheduler.cancel_run_items(None if req.all else set(by_kind["run"]))

    async with aiosqlite.connect(DB_PATH) as db:
        if req.all:
            cur = await db.execute(
                "UPDATE notification_deliveries SET status = 'cancelled', last_error = 'cancelado pelo admin', "
                "next_retry_at = NULL WHERE status IN ('pending', 'sending')"
            )
            result["delivery"] = cur.rowcount
            cur = await db.execute("UPDATE scheduled_reminders SET sent = 3 WHERE sent = 0")
            result["reminder"] = cur.rowcount
        else:
            for did in by_kind["delivery"]:
                cur = await db.execute(
                    "UPDATE notification_deliveries SET status = 'cancelled', last_error = 'cancelado pelo admin', "
                    "next_retry_at = NULL WHERE id = ? AND status IN ('pending', 'sending')",
                    (did,),
                )
                result["delivery"] += cur.rowcount
            for rid in by_kind["reminder"]:
                cur = await db.execute(
                    "UPDATE scheduled_reminders SET sent = 3 WHERE id = ? AND sent = 0", (rid,)
                )
                result["reminder"] += cur.rowcount
        await db.commit()
    return {"cancelled": result, "total": sum(result.values())}
