"""Trevo da Sorte — monthly raffle among customers who bought clovers at renewal.

Each clover bought = 1 coupon. Optional "login coringa" joins as ONE regular
participant (same odds as any single clover). Winner drawn with
secrets.SystemRandom, renewed for `raffle_prize_months` and notified.
The Mongo `raffle_draws` doc (_id = month) is the cross-environment lock, so
the Raspberry and any other env sharing Atlas never draw twice."""
import asyncio
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import aiosqlite

from database import DB_PATH, get_setting

logger = logging.getLogger(__name__)
RECEIVED = ("paid", "paid_renewal_failed")
DRAW_HOUR = 20  # last day of the month, display timezone


def _cents(v: str, default: int = 0) -> int:
    try:
        return int(round(float(str(v).replace(",", ".").strip()) * 100))
    except Exception:
        return default


async def config() -> dict:
    return {
        "enabled": (await get_setting("raffle_enabled") or "false").lower() in ("1", "true", "on", "yes"),
        "clover_cents": _cents(await get_setting("raffle_clover_price") or "2,00", 200),
        "prize_months": int(await get_setting("raffle_prize_months") or 1),
        "joker_login": (await get_setting("raffle_joker_login") or "").strip(),
        "max_clovers": 10,
    }


async def _tz():
    from services.scheduler import _get_display_tz
    return await _get_display_tz()


async def month_bounds(month: str = None):
    tz = await _tz()
    now = datetime.now(tz)
    y, m = (int(x) for x in (month or now.strftime("%Y-%m")).split("-"))
    start = datetime(y, m, 1, tzinfo=tz)
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=tz)
    return f"{y:04d}-{m:02d}", start, end


async def entries(month: str = None) -> dict:
    month, start, end = await month_bounds(month)
    s_utc, e_utc = start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = [dict(r) for r in await (await db.execute(
            "SELECT p.id, p.customer_id, p.clovers, p.paid_at, c.painel_username, c.name, c.whatsapp FROM payments p "
            "LEFT JOIN customers c ON c.id = p.customer_id "
            f"WHERE p.clovers > 0 AND p.status IN ({','.join('?' * len(RECEIVED))}) AND p.paid_at >= ? AND p.paid_at < ? "
            "ORDER BY p.paid_at", (*RECEIVED, s_utc, e_utc))).fetchall()]
    from routers.painel_users import _read_cache
    users, _ = await _read_cache()
    logins = {str(u.get("id")): u.get("username") for u in users or []}
    pool, n = [], 1
    for r in rows:
        r["painel_username"] = logins.get(str(r["customer_id"])) or r["painel_username"]
        for _ in range(int(r["clovers"] or 0)):
            pool.append({"coupon": f"{n:05d}", "customer_id": str(r["customer_id"]),
                         "name": r["painel_username"] or r["name"] or str(r["customer_id"]), "payment_id": r["id"]})
            n += 1
    cfg = await config()
    if cfg["joker_login"]:
        pool.append({"coupon": f"{n:05d}", "customer_id": cfg["joker_login"], "name": cfg["joker_login"], "joker": True})
    participants = len({p["customer_id"] for p in pool if not p.get("joker")})
    return {"month": month, "pool": pool, "participants": participants,
            "clovers": sum(1 for p in pool if not p.get("joker")),
            "draw_at": (end - timedelta(days=1)).replace(hour=DRAW_HOUR).isoformat()}


async def _resolve_joker(login_or_id: str):
    from routers.painel_users import _read_cache
    users, _ = await _read_cache()
    for u in users or []:
        if str(u.get("id")) == login_or_id or (u.get("username") or "").lower() == login_or_id.lower():
            return str(u.get("id")), u.get("username")
    return login_or_id, login_or_id


async def perform_draw(month: str = None) -> dict:
    from services.mongo_store import _get_db
    data = await entries(month)
    pool = data["pool"]
    if not any(not p.get("joker") for p in pool):
        raise ValueError("Nenhum trevo pago neste mês")
    mdb = _get_db()
    draw = {"_id": data["month"], "id": str(uuid.uuid4()), "status": "drawing",
            "created_at": datetime.now(timezone.utc).isoformat()}
    try:
        await mdb.raffle_draws.insert_one(dict(draw))  # cross-environment lock
    except Exception as e:
        raise ValueError(f"Sorteio de {data['month']} já foi realizado") from e

    try:
        return await _draw_locked(data, pool, draw, mdb)
    except Exception:
        await mdb.raffle_draws.delete_one({"_id": data["month"], "status": "drawing"})  # release lock
        raise


async def _draw_locked(data, pool, draw, mdb):
    rng = secrets.SystemRandom()
    winner = rng.choice(pool)
    shuffled = pool[:]
    rng.shuffle(shuffled)
    win_index = 52
    seq = [{"name": s["name"], "coupon": s["coupon"]} for s in (shuffled[i % len(shuffled)] for i in range(win_index + 8))]
    seq[win_index] = {"name": winner["name"], "coupon": winner["coupon"]}
    cfg = await config()
    winner_id = winner["customer_id"]
    if winner.get("joker"):
        winner_id, _login = await _resolve_joker(winner_id)

    renewed, renew_error = False, ""
    try:
        from services import painel
        from services.system_detector import detect_system_type
        from routers.payments import _cache_user
        system = detect_system_type(await _cache_user(winner_id)) or "iptv"
        await painel.renew_user(user_id=winner_id, package_id=painel.get_package_id(system, cfg["prize_months"]),
                                months=cfg["prize_months"])
        renewed = True
    except Exception as e:
        renew_error = str(e)[:200]
        logger.exception("Raffle prize renewal failed for %s", winner_id)

    doc = {"status": "drawn", "month": data["month"], "winner": winner, "winner_painel_id": winner_id,
           "sequence": seq, "win_index": win_index, "participants": data["participants"],
           "total_clovers": data["clovers"], "prize_months": cfg["prize_months"],
           "renewed": renewed, "renew_error": renew_error}
    await mdb.raffle_draws.update_one({"_id": data["month"]}, {"$set": doc})
    await _notify(winner, winner_id, cfg["prize_months"], renewed, data)
    return {**draw, **doc, "id": draw["id"]}


async def _notify(winner, winner_id, months, renewed, data):
    from services.notifier import send_admin_alert, send_hardcoded
    phone = ""
    try:
        from routers.payments import _cache_user
        from services.phone_extractor import extract_whatsapp
        phone = extract_whatsapp(await _cache_user(winner_id)) or ""
    except Exception:
        pass
    if phone and not winner.get("joker"):
        await send_hardcoded(phone, f"🍀 *Você ganhou o Trevo da Sorte!*\n\nParabéns, {winner['name']}! Seu cupom *#{winner['coupon']}* "
                             f"foi sorteado e seu login ganhou *{months} mês(es) grátis*"
                             + (" — já está renovado. 🎉" if renewed else ". Vamos liberar em instantes."),
                             event_key="raffle_winner", customer_id=str(winner_id))
    await send_admin_alert(
        f"🍀 *Trevo da Sorte {data['month']}*\n\nGanhador: {winner['name']} (cupom #{winner['coupon']})"
        f"{' — CORINGA' if winner.get('joker') else ''}\nParticipantes: {data['participants']} · Trevos: {data['clovers']}\n"
        f"Prêmio: {months} mês(es) — {'renovado ✅' if renewed else '❌ renovar manualmente'}")


async def history(limit: int = 12) -> list:
    from services.mongo_store import _get_db
    out = []
    async for d in _get_db().raffle_draws.find({"status": "drawn"}).sort("_id", -1).limit(limit):
        d["month"] = d.pop("_id")
        out.append(d)
    return out


async def auto_draw_loop():
    """Draw automatically on the last day of the month from DRAW_HOUR on."""
    while True:
        try:
            cfg = await config()
            tz = await _tz()
            now = datetime.now(tz)
            last_day = (now + timedelta(days=1)).month != now.month
            if cfg["enabled"] and last_day and now.hour >= DRAW_HOUR:
                from services.mongo_store import _get_db
                if not await _get_db().raffle_draws.find_one({"_id": now.strftime("%Y-%m")}):
                    await perform_draw()
        except ValueError as e:
            logger.info("Raffle auto-draw skipped: %s", e)
        except Exception:
            logger.exception("Raffle auto-draw failed")
        await asyncio.sleep(600)


def clean_settings_payload(body: dict) -> dict:
    out = {}
    if "enabled" in body:
        out["raffle_enabled"] = "true" if body["enabled"] else "false"
    if "clover_price" in body:
        out["raffle_clover_price"] = str(body["clover_price"]).strip()[:10]
    if "prize_months" in body:
        m = int(body["prize_months"] or 1)
        out["raffle_prize_months"] = str(m if m in (1, 3, 6, 12) else 1)
    if "joker_login" in body:
        out["raffle_joker_login"] = str(body["joker_login"] or "").strip()[:60]
    return out

