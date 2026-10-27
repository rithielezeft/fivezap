"""Analytics — geographic distribution of customers by phone number."""
import logging
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Query
import aiosqlite

from database import DB_PATH
from services.geography import resolve_country, resolve_br_state
from services.expiration import compute_expiration_info

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
logger = logging.getLogger(__name__)


@router.get("/geography")
async def geography(
    scope: Literal["all", "active", "expired"] = Query("all"),
):
    """Aggregate customers by country (DDI) and by BR state (DDD).

    Data source: local painel cache (routers.painel_users._read_cache).
    Falls back to local `customers` table when painel cache is empty.

    Returns:
      {
        total: int,
        by_country: [{code, name, ddi, lat, lng, flag, count}, ...],
        by_br_state: [{uf, region, ddd, lat, lng, count}, ...],
        unresolved: int,   # phones that didn't match any DDI
        no_phone: int,     # customers without a whatsapp field
        top_country: {...},  # country with the most clients (or null)
      }
    """
    # Prefer painel cache — that's the source-of-truth.
    try:
        from routers.painel_users import _read_cache
        painel_users, _ = await _read_cache()
    except Exception:
        painel_users = []

    # Extract iterable of {phone, is_active} from either source.
    records = []
    if painel_users:
        for u in painel_users:
            info = compute_expiration_info(u)
            status = info.get("status")
            # Phones on painel: whatsapp, as_number, reseller_notes (fallback)
            from services.phone_extractor import extract_whatsapp
            phone = extract_whatsapp(u) or (u.get("whatsapp") or "")
            records.append({
                "phone": str(phone or "").strip(),
                "status": status,
            })
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT whatsapp, expires_at, status FROM customers"
            )
            for r in await cur.fetchall():
                info = compute_expiration_info({"expires_at": r["expires_at"]})
                records.append({
                    "phone": (r["whatsapp"] or "").strip(),
                    "status": info.get("status"),
                })

    country_agg = defaultdict(lambda: {"count": 0, "meta": None})
    br_state_agg = defaultdict(lambda: {"count": 0, "meta": None})
    no_phone = 0
    unresolved = 0
    kept = 0

    for rec in records:
        phone = rec["phone"]
        status = rec["status"]

        # Apply scope filter
        if scope == "active" and status not in ("active", "expiring_soon"):
            continue
        if scope == "expired" and status != "expired":
            continue

        if not phone:
            no_phone += 1
            continue

        digits = "".join(c for c in phone if c.isdigit())
        # Phones stored with @lid suffix have already been stripped of letters
        # via isdigit() filter. If we're left with a plausible-length number,
        # try to resolve.
        if len(digits) < 8:
            unresolved += 1
            continue

        country = resolve_country(digits)
        if not country:
            unresolved += 1
            continue

        kept += 1
        key = country["code"]
        country_agg[key]["count"] += 1
        if country_agg[key]["meta"] is None:
            country_agg[key]["meta"] = country

        # BR drill-down
        br = resolve_br_state(digits)
        if br:
            k2 = br["ddd"]
            br_state_agg[k2]["count"] += 1
            if br_state_agg[k2]["meta"] is None:
                br_state_agg[k2]["meta"] = br

    countries_out = [
        {**v["meta"], "count": v["count"]}
        for v in country_agg.values() if v["meta"]
    ]
    countries_out.sort(key=lambda x: x["count"], reverse=True)

    br_out = [
        {**v["meta"], "count": v["count"]}
        for v in br_state_agg.values() if v["meta"]
    ]
    br_out.sort(key=lambda x: x["count"], reverse=True)

    return {
        "total": kept,
        "by_country": countries_out,
        "by_br_state": br_out,
        "unresolved": unresolved,
        "no_phone": no_phone,
        "top_country": countries_out[0] if countries_out else None,
        "scope": scope,
    }


def _recent(iso, days: int = 3) -> bool:
    from datetime import datetime, timedelta, timezone
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - d < timedelta(days=days)
    except Exception:
        return False


def _region_of(phone: str):
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) < 8:
        return None
    br = resolve_br_state(digits)
    if br:
        return {"key": f"BR-{br['ddd']}", "label": f"{br.get('uf', '')} · DDD {br['ddd']}", "kind": "br",
                "uf": br.get("uf"), "region": br.get("region")}
    country = resolve_country(digits)
    if country:
        return {"key": country["code"], "label": country.get("name") or country["code"], "kind": "country",
                "flag": country.get("flag")}
    return None


@router.get("/geography/customers")
async def geography_customers():
    """Customers per location: current painel users (ativos/vencidos) plus
    'cancelados' — clients we knew (MongoDB/SQLite history) that are no longer
    on the painel."""
    from routers.painel_users import _read_cache
    from services.phone_extractor import extract_whatsapp
    from services import mongo_store

    painel_users, _ = await _read_cache()
    out, seen = [], set()
    for u in painel_users or []:
        uid = str(u.get("id") or u.get("user_id") or u.get("username") or "")
        seen.add(uid)
        phone = extract_whatsapp(u) or (u.get("whatsapp") or "")
        info = compute_expiration_info(u)
        out.append({"id": uid, "login": u.get("username"), "name": u.get("full_name") or u.get("name"),
                    "phone": str(phone or ""), "status": "expired" if info.get("status") == "expired" else "active",
                    "expires_at": info.get("expires_at_iso"), "system_type": u.get("system_type"),
                    "is_trial": bool(u.get("is_trial"))})

    known = []
    try:
        db = mongo_store._get_db()
        async for d in db.customers.find({}, {"painel_password": 0}):
            known.append({"id": str(d.get("_id")), "login": d.get("username") or d.get("painel_username"),
                          "name": d.get("full_name") or d.get("name"), "phone": d.get("whatsapp") or "",
                          "expires_at": d.get("exp_date_iso"), "system_type": d.get("system_type"),
                          "is_trial": bool(d.get("is_trial")), "last_seen": d.get("last_synced_at")})
    except Exception:
        logger.exception("mongo customers lookup failed")
    async with aiosqlite.connect(DB_PATH) as sdb:
        sdb.row_factory = aiosqlite.Row
        cur = await sdb.execute("SELECT id, painel_username, name, whatsapp, expires_at, system_type FROM customers")
        for r in await cur.fetchall():
            known.append({"id": str(r["id"]), "login": r["painel_username"], "name": r["name"], "phone": r["whatsapp"] or "",
                          "expires_at": r["expires_at"], "system_type": r["system_type"], "is_trial": False, "last_seen": None})
    def norm_phone(v):
        d = "".join(c for c in str(v or "") if c.isdigit())
        return d[-10:] if len(d) >= 10 else None

    seen_logins = {(c["login"] or "").strip().lower() for c in out if c.get("login")}
    seen_phones = {norm_phone(c["phone"]) for c in out} - {None}
    # Newest record first so a re-created customer keeps its latest data.
    known.sort(key=lambda k: str(k.get("last_seen") or ""), reverse=True)
    for k in known:
        login = (k["login"] or "").strip().lower()
        ph = norm_phone(k["phone"])
        if k["id"] in seen or k["is_trial"] or (login and login in seen_logins) or (ph and ph in seen_phones):
            continue
        seen.add(k["id"])
        if login:
            seen_logins.add(login)
        if ph:
            seen_phones.add(ph)
        # Still being synced to Atlas (e.g. by the Raspberry's painel refresh) → still on a painel.
        if _recent(k.get("last_seen")):
            info = compute_expiration_info({"exp_date_iso": k.get("expires_at"), "expires_at": k.get("expires_at")})
            out.append({**k, "status": "expired" if info.get("status") == "expired" else "active"})
            continue
        out.append({**k, "status": "cancelled"})

    regions = {}
    for c in out:
        reg = _region_of(c["phone"])
        c["region_key"] = reg["key"] if reg else "unknown"
        c["region_label"] = reg["label"] if reg else "Sem telefone / desconhecido"
        r = regions.setdefault(c["region_key"], {**(reg or {"key": "unknown", "label": c["region_label"], "kind": "unknown"}),
                                                 "active": 0, "expired": 0, "cancelled": 0})
        r[c["status"]] += 1
    reg_list = sorted(regions.values(), key=lambda r: -(r["active"] + r["expired"] + r["cancelled"]))
    return {
        "regions": reg_list,
        "customers": out,
        "totals": {s: sum(1 for c in out if c["status"] == s) for s in ("active", "expired", "cancelled")},
    }
