"""Preview of the WhatsApp notifications a painel user will receive (and what
was already sent), for the Clientes page. Read-only — never sends anything."""
import json
from datetime import datetime, timedelta, timezone

import aiosqlite

import database
from database import get_setting
from services.expiration import compute_expiration_info
from services.notifier import get_template, render
from services.phone_extractor import extract_whatsapp

TITLES = {
    "expiration_7d": "Vence em 7 dias", "expiration_3d": "Vence em 3 dias",
    "expiration_1d": "Vence amanhã", "expiration_0d": "Vence hoje",
    "expired_1d": "Vencido há 1 dia", "expired_3d": "Vencido há 3 dias",
    "expired_7d": "Vencido há 7 dias", "auto_recovery_coupon": "Cupom de recuperação",
    "trial_ready": "Teste criado", "trial_1h_reminder": "Lembrete 1h do teste",
    "trial_expired": "Teste acabou (3h)", "manual_expired_alert": "Aviso manual de vencido",
}
REMINDER_STATUS = {0: "scheduled", 1: "sent", 2: "queued", 3: "cancelled"}


async def _settings():
    from services.scheduler import _get_display_tz
    days_raw = await get_setting("notification_days", "3,1,0") or ""
    return {
        "tz": await _get_display_tz(),
        "days": sorted({int(d) for d in days_raw.split(",") if d.strip().lstrip("-").isdigit()}, reverse=True),
        "public_base": (await get_setting("public_base_url", "") or "").rstrip("/"),
        "trial_pkg": int(await get_setting("trial_package_id", "61") or 61),
        "coupon_on": (await get_setting("auto_coupon_enabled") or "true").strip().lower() in ("true", "1", "yes", "on"),
        "coupon_days": int(await get_setting("auto_coupon_expired_days") or 3),
    }


def is_trial_user(u: dict, trial_pkg: int) -> bool:
    pkg = u.get("package_id") or u.get("current_package_id")
    return (
        (pkg is not None and str(pkg).isdigit() and int(pkg) == trial_pkg)
        or bool(u.get("is_trial"))
        or "trial" in str(u.get("type") or "").lower()
    )


def _event_for_days(d: int):
    from services.scheduler import _event_for_days as f
    return f(d)


def _expiration_plan(u: dict, cfg: dict) -> list:
    """Planned expiration notices as [(event_key, local_date, days)]."""
    info = compute_expiration_info(u, tz=cfg["tz"])
    if not info["expires_at_iso"]:
        return []
    exp_date = datetime.fromisoformat(info["expires_at_iso"]).astimezone(cfg["tz"]).date()
    plan = []
    for d in cfg["days"]:
        ev = _event_for_days(d)
        if ev:
            plan.append((ev, exp_date - timedelta(days=d), d))
    if cfg["coupon_on"]:
        plan.append(("auto_recovery_coupon", exp_date + timedelta(days=cfg["coupon_days"]), -cfg["coupon_days"]))
    return sorted(plan, key=lambda p: p[1])


async def next_notification_map(users: list) -> dict:
    """{user_id: {event_key, title, date, kind}} — next pending notice per user (cheap)."""
    cfg = await _settings()
    today = datetime.now(timezone.utc).astimezone(cfg["tz"]).date()
    pending = {}
    async with aiosqlite.connect(database.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT event_key, phone, context, send_at FROM scheduled_reminders WHERE sent = 0 ORDER BY send_at"
        )
        for r in await cur.fetchall():
            try:
                login = (json.loads(r["context"] or "{}").get("user") or "").lower()
            except Exception:
                login = ""
            for k in (login, r["phone"]):
                if k and k not in pending:
                    pending[k] = r
    out = {}
    for u in users:
        uid = str(u.get("id") or u.get("user_id") or u.get("username") or "")
        if not uid:
            continue
        if is_trial_user(u, cfg["trial_pkg"]):
            r = pending.get((u.get("username") or "").lower()) or pending.get(extract_whatsapp(u) or "")
            if r:
                out[uid] = {"event_key": r["event_key"], "title": TITLES.get(r["event_key"], r["event_key"]),
                            "date": r["send_at"], "kind": "trial"}
            continue
        nxt = next((p for p in _expiration_plan(u, cfg) if p[1] >= today), None)
        if nxt:
            out[uid] = {"event_key": nxt[0], "title": TITLES.get(nxt[0], nxt[0]),
                        "date": nxt[1].isoformat(), "kind": "expiration"}
    return out


async def _deliveries_for(phone: str, limit: int = 30) -> list:
    if not phone:
        return []
    async with aiosqlite.connect(database.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, event_key, status, attempts, body, image_url, created_at, sent_at, last_error "
            "FROM notification_deliveries WHERE phone = ? ORDER BY created_at DESC LIMIT ?",
            (phone, limit),
        )
        return [dict(r) for r in await cur.fetchall()]


async def _preview(event_key: str, ctx: dict) -> dict:
    tpl = await get_template(event_key)
    if not tpl:
        return {"body": None, "image_url": None, "template_enabled": False}
    return {"body": render(tpl["body"], ctx), "image_url": tpl.get("image_url") or None, "template_enabled": True}


async def user_notifications(u: dict) -> dict:
    cfg = await _settings()
    tz = cfg["tz"]
    today = datetime.now(timezone.utc).astimezone(tz).date()
    uid = str(u.get("id") or u.get("user_id") or u.get("username") or "")
    login = u.get("username") or u.get("login") or uid
    name = (u.get("full_name") or u.get("name") or login or "cliente").strip()
    phone = extract_whatsapp(u) or ""
    trial = is_trial_user(u, cfg["trial_pkg"])
    info = compute_expiration_info(u, tz=tz)
    deliveries = await _deliveries_for(phone)

    def _local_date(iso):
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(tz).date()
        except Exception:
            return None

    upcoming = []
    if trial:
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM scheduled_reminders WHERE phone = ? OR context LIKE ? ORDER BY send_at",
                (phone or "__none__", f'%"user": "{login}"%'),
            )
            rows = [dict(r) for r in await cur.fetchall()]
        for r in rows:
            try:
                ctx = json.loads(r["context"] or "{}")
            except Exception:
                ctx = {}
            upcoming.append({
                "event_key": r["event_key"], "title": TITLES.get(r["event_key"], r["event_key"]),
                "when": r["send_at"], "status": REMINDER_STATUS.get(r["sent"], "scheduled"),
                **(await _preview(r["event_key"], ctx)),
            })
    else:
        exp_txt = ""
        if info["expires_at_iso"]:
            exp_txt = datetime.fromisoformat(info["expires_at_iso"]).astimezone(tz).strftime("%d/%m/%Y")
        for ev, day, d in _expiration_plan(u, cfg):
            sent = [x for x in deliveries if x["event_key"] == ev and x["status"] in ("sent", "sending", "pending")
                    and (_local_date(x["created_at"]) or today) >= day]
            if sent:
                status = "sent" if sent[0]["status"] == "sent" else "queued"
            elif day < today:
                status = "missed"
            elif day == today:
                status = "today"
            else:
                status = "scheduled"
            ctx = {
                "name": name, "user": login, "user_id": uid, "expires_at": exp_txt,
                "pay_link": f"{cfg['public_base']}/pay/{uid}?ref={ev}" if cfg["public_base"] else "",
                "days": abs(d), "days_expired": str(abs(d)), "discount_line": "", "discount_percent": "",
                "coupon_code": "VOLTA••••••", "expires_in_hours": "24",
            }
            upcoming.append({
                "event_key": ev, "title": TITLES.get(ev, ev), "when": day.isoformat(),
                "status": status, **(await _preview(ev, ctx)),
            })

    # Duplicate detector: same event to the same phone more than once on the same day.
    seen = {}
    for x in deliveries:
        if x["status"] == "sent":
            k = (x["event_key"], _local_date(x["created_at"]))
            seen[k] = seen.get(k, 0) + 1
    dups = sum(c - 1 for c in seen.values() if c > 1)

    return {
        "user_id": uid, "username": login, "name": name, "whatsapp": phone, "is_trial": trial,
        "expires_at": info["expires_at_iso"], "days_until_expiry": info["days_until_expiry"],
        "status": info["status"], "upcoming": upcoming,
        "history": [{**x, "title": TITLES.get(x["event_key"], x["event_key"])} for x in deliveries],
        "duplicate_sends": dups,
    }
