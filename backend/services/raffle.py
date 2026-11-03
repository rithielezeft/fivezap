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
        "joker_count": max(0, min(50, int(await get_setting("raffle_joker_count") or 0))),
        "joker_phone": "".join(c for c in (await get_setting("raffle_joker_phone") or "") if c.isdigit()),
        "max_clovers": 10,
        "auto_restart": (await get_setting("raffle_auto_restart") or "true").lower() in ("1", "true", "on", "yes"),
        "auto_renew": (await get_setting("raffle_auto_renew") or "true").lower() in ("1", "true", "on", "yes"),
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


def _next_draw_at(after: datetime) -> datetime:
    """Last day of `after`'s month at DRAW_HOUR; next month's if already past."""
    for k in range(2):
        y, m = after.year, after.month + k
        y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        nxt = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=after.tzinfo)
        at = (nxt - timedelta(days=1)).replace(hour=DRAW_HOUR)
        if at > after:
            return at
    return at


async def _new_round_id(mdb, start: datetime) -> str:
    base = start.strftime("%Y-%m")
    rid, n = base, 1
    while await mdb.raffle_draws.find_one({"_id": rid}):
        n += 1
        rid = f"{base}-{n}"
    return rid


async def start_new_round(start_iso: str = None) -> dict:
    """Open a new round. Starts where the last draw ended so no paid clover is lost."""
    from services.mongo_store import _get_db
    mdb = _get_db()
    if not start_iso:
        last = await mdb.raffle_draws.find_one({"status": "drawn"}, sort=[("created_at", -1)])
        start_iso = last["created_at"] if last else None
    tz = await _tz()
    now = datetime.now(tz)
    start = datetime.fromisoformat(start_iso) if start_iso else datetime(now.year, now.month, 1, tzinfo=tz)
    state = {"round_id": await _new_round_id(mdb, now), "start": start.astimezone(timezone.utc).isoformat(),
             "draw_at": _next_draw_at(now).isoformat(), "opened_at": datetime.now(timezone.utc).isoformat()}
    await mdb.raffle_state.update_one({"_id": "current"}, {"$set": state}, upsert=True)
    return state


async def current_round() -> dict:
    from services.mongo_store import _get_db
    mdb = _get_db()
    state = await mdb.raffle_state.find_one({"_id": "current"}) or await start_new_round()
    drawn = await mdb.raffle_draws.find_one({"_id": state["round_id"]}, {"sequence": 0})
    state["drawn"] = bool(drawn and drawn.get("status") == "drawn")
    state["drawn_at"] = drawn.get("created_at") if drawn else None
    return state


async def _manual_entries(round_id: str) -> list:
    from services.mongo_store import _get_db
    return [d async for d in _get_db().raffle_manual_entries.find({"round_id": round_id}).sort("created_at", 1)]


async def entries(month: str = None) -> dict:
    rnd = await current_round()
    s_utc = rnd["start"]
    e_utc = rnd["drawn_at"] or "9999"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = [dict(r) for r in await (await db.execute(
            "SELECT p.id, p.customer_id, p.clovers, p.paid_at, c.painel_username, c.name, c.whatsapp FROM payments p "
            "LEFT JOIN customers c ON c.id = p.customer_id "
            f"WHERE p.clovers > 0 AND p.status IN ({','.join('?' * len(RECEIVED))}) AND p.paid_at >= ? AND p.paid_at < ? "
            "ORDER BY p.paid_at", (*RECEIVED, s_utc, e_utc))).fetchall()]
    for m in await _manual_entries(rnd["round_id"]):
        rows.append({"id": None, "entry_id": m["_id"], "customer_id": m["customer_id"], "clovers": m["clovers"],
                     "paid_at": m["created_at"], "painel_username": m.get("name"), "name": m.get("name")})
    rows.sort(key=lambda r: r["paid_at"] or "")
    from routers.painel_users import _read_cache
    users, _ = await _read_cache()
    logins = {str(u.get("id")): u.get("username") for u in users or []}
    logins.update(await display_names())
    pool, n = [], 1
    for r in rows:
        r["painel_username"] = logins.get(str(r["customer_id"])) or r["painel_username"]
        for _ in range(int(r["clovers"] or 0)):
            item = {"coupon": f"{n:05d}", "customer_id": str(r["customer_id"]),
                    "name": r["painel_username"] or r["name"] or str(r["customer_id"]), "payment_id": r["id"]}
            if r.get("entry_id"):
                item.update(manual=True, entry_id=r["entry_id"])
            pool.append(item)
            n += 1
    cfg = await config()
    # House entries are always labelled "Coringa N" (publicly too): each one
    # has the odds of a single clover.
    jokers = cfg["joker_count"] or (1 if cfg["joker_login"] else 0)
    for i in range(jokers):
        pool.append({"coupon": f"{n:05d}", "customer_id": cfg["joker_login"] or f"coringa-{i + 1}",
                     "name": f"Coringa {i + 1}", "joker": True})
        n += 1
    participants = len({p["customer_id"] for p in pool if not p.get("joker")})
    return {"month": rnd["round_id"], "round_id": rnd["round_id"], "open": not rnd["drawn"], "start": rnd["start"],
            "pool": pool, "participants": participants,
            "clovers": sum(1 for p in pool if not p.get("joker")), "draw_at": rnd["draw_at"]}


async def add_manual_entry(customer: str, clovers: int) -> dict:
    from services.mongo_store import _get_db
    customer = (customer or "").strip()
    if not customer:
        raise ValueError("Informe o login ou ID do cliente")
    clovers = max(1, min(int(clovers or 1), 10))
    from routers.painel_users import _read_cache
    users, _ = await _read_cache()
    user = next((u for u in users or [] if str(u.get("id")) == customer
                 or (u.get("username") or "").lower() == customer.lower()), None)
    if not user:
        raise ValueError("Cliente não encontrado no painel")
    rnd = await current_round()
    if rnd["drawn"]:
        raise ValueError("O sorteio atual já foi realizado. Inicie um novo sorteio primeiro.")
    doc = {"_id": str(uuid.uuid4()), "round_id": rnd["round_id"], "customer_id": str(user["id"]),
           "name": user.get("username") or str(user["id"]), "clovers": clovers,
           "created_at": datetime.now(timezone.utc).isoformat()}
    await _get_db().raffle_manual_entries.insert_one(doc)
    return doc


async def remove_manual_entry(entry_id: str) -> bool:
    from services.mongo_store import _get_db
    rnd = await current_round()
    res = await _get_db().raffle_manual_entries.delete_one({"_id": entry_id, "round_id": rnd["round_id"]})
    return res.deleted_count > 0


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
    if not data["open"]:
        raise ValueError("Este sorteio já foi realizado. Inicie um novo sorteio.")
    if not any(not p.get("joker") for p in pool):
        raise ValueError("Nenhum trevo neste sorteio")
    mdb = _get_db()
    draw = {"_id": data["round_id"], "id": str(uuid.uuid4()), "status": "drawing",
            "created_at": datetime.now(timezone.utc).isoformat()}
    try:
        await mdb.raffle_draws.insert_one(dict(draw))  # cross-environment lock
    except Exception as e:
        raise ValueError(f"Sorteio {data['round_id']} já foi realizado") from e

    try:
        result = await _draw_locked(data, pool, draw, mdb)
    except Exception:
        await mdb.raffle_draws.delete_one({"_id": data["round_id"], "status": "drawing"})  # release lock
        raise
    if (await config())["auto_restart"]:
        await start_new_round(draw["created_at"])
    return result


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
        winner_id, _login = await _resolve_joker(winner_id) if cfg["joker_login"] else (None, None)

    renewed, renew_error = False, ""
    try:
        if not cfg["auto_renew"]:
            raise RuntimeError("renovação automática do prêmio desativada")
        if not winner_id:
            raise RuntimeError("coringa sem login definido — sem renovação")
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

    doc = {"status": "drawn", "month": data["round_id"], "round_id": data["round_id"], "winner": winner, "winner_painel_id": winner_id,
           "sequence": seq, "win_index": win_index, "participants": data["participants"],
           "total_clovers": data["clovers"], "prize_months": cfg["prize_months"],
           "renewed": renewed, "renew_error": renew_error}
    await mdb.raffle_draws.update_one({"_id": data["round_id"]}, {"$set": doc})
    await _notify(winner, winner_id, cfg["prize_months"], renewed, data)
    return {**draw, **doc, "id": draw["id"]}


async def _notify(winner, winner_id, months, renewed, data):
    from services.notifier import send_admin_alert, send_hardcoded
    phone = ""
    if winner.get("joker"):
        cfg = await config()
        if cfg["joker_phone"]:
            await send_hardcoded(cfg["joker_phone"], f"🍀 Trevo da Sorte {data['month']}: {winner['name']} (cupom #{winner['coupon']}) foi sorteado.",
                                 event_key="raffle_winner_joker")
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
        d["round_id"] = d.pop("_id")
        d["month"] = d.get("month") or d["round_id"]
        out.append(d)
    return out


async def auto_draw_loop():
    """Draw automatically at the round's draw_at; reopen a round after a draw when auto_restart is on."""
    while True:
        try:
            cfg = await config()
            rnd = await current_round()
            now = datetime.now(timezone.utc)
            if rnd["drawn"]:
                if cfg["auto_restart"]:
                    await start_new_round(rnd["drawn_at"])
            elif cfg["enabled"] and now >= datetime.fromisoformat(rnd["draw_at"]):
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
    for key in ("auto_restart", "auto_renew"):
        if key in body:
            out[f"raffle_{key}"] = "true" if body[key] else "false"
    if "joker_count" in body:
        out["raffle_joker_count"] = str(max(0, min(50, int(body["joker_count"] or 0))))
    if "joker_phone" in body:
        out["raffle_joker_phone"] = "".join(c for c in str(body["joker_phone"] or "") if c.isdigit())[:15]
    if "joker_login" in body:
        out["raffle_joker_login"] = str(body["joker_login"] or "").strip()[:60]
    return out



async def coupons_for_payment(payment_id: str) -> list:
    data = await entries()
    return [p["coupon"] for p in data["pool"] if p.get("payment_id") == payment_id]


def mask_name(name: str) -> str:
    name = str(name or "")
    if name.startswith("Coringa "):
        return name
    return (name[:3] + "***") if len(name) > 3 else name[:1] + "***"


async def display_names() -> dict:
    """Admin-edited display names for real participants {painel_id: name}."""
    import json
    try:
        return json.loads(await get_setting("raffle_display_names") or "{}")
    except Exception:
        return {}


async def set_display_name(customer_id: str, name: str) -> dict:
    import json
    from database import set_setting
    names = await display_names()
    name = (name or "").strip()[:40]
    if name:
        names[str(customer_id)] = name
    else:
        names.pop(str(customer_id), None)
    await set_setting("raffle_display_names", json.dumps(names))
    return names
