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
