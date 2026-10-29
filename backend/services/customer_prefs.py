"""Per-customer preferences (keyed by painel id), stored in MongoDB Atlas.

{_id, prices: {"1": cents, ...}, fixed_plan: int|None, no_discount: bool,
 notify_events: [event_key, ...] | None (None = every reminder)}"""
import logging
import time

from database import get_setting

logger = logging.getLogger(__name__)
PLANS = (1, 3, 6, 12)
EVENTS = ("expiration_7d", "expiration_3d", "expiration_1d", "expiration_0d",
          "expired_1d", "expired_3d", "expired_7d")
_cache: dict = {}
_TTL = 60


def _default() -> dict:
    return {"prices": {}, "fixed_plan": None, "no_discount": False, "notify_events": None}


async def get_prefs(painel_id) -> dict:
    key = str(painel_id or "")
    if not key:
        return _default()
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    prefs = _default()
    try:
        from services.mongo_store import _get_db
        doc = await _get_db().customer_prefs.find_one({"_id": key})
        if doc:
            prefs.update({k: doc.get(k, prefs[k]) for k in prefs})
    except Exception:
        logger.exception("customer_prefs read failed for %s", key)
    _cache[key] = (time.time() + _TTL, prefs)
    return prefs


async def set_prefs(painel_id, body: dict) -> dict:
    from services.mongo_store import _get_db
    prices = {}
    for m in PLANS:
        v = (body.get("prices") or {}).get(str(m))
        if v in (None, ""):
            continue
        cents = int(v) if isinstance(v, int) else int(round(float(str(v).replace("R$", "").replace(".", "").replace(",", ".").strip()) * 100))
        if cents > 0:
            prices[str(m)] = cents
    fixed = body.get("fixed_plan")
    events = body.get("notify_events")
    doc = {
        "prices": prices,
        "fixed_plan": int(fixed) if fixed and int(fixed) in PLANS else None,
        "no_discount": bool(body.get("no_discount")),
        "notify_events": None if events is None else [e for e in events if e in EVENTS],
    }
    await _get_db().customer_prefs.update_one({"_id": str(painel_id)}, {"$set": doc}, upsert=True)
    _cache.pop(str(painel_id), None)
    return doc


async def default_price(months: int) -> int:
    v = await get_setting(f"plan_price_{months}m", "35,00")
    try:
        return int(round(float(v.replace(",", ".").strip()) * 100))
    except ValueError:
        return 3500


async def price_for(painel_id, months: int) -> int:
    custom = (await get_prefs(painel_id))["prices"].get(str(months))
    return int(custom) if custom else await default_price(months)


async def discount_blocked(painel_id) -> bool:
    return bool((await get_prefs(painel_id))["no_discount"])


async def wants_event(painel_id, event_key: str) -> bool:
    events = (await get_prefs(painel_id))["notify_events"]
    return events is None or event_key in events
