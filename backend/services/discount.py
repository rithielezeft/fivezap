"""Automatic per-event discount system.

Rules:
- Admin configures per event_key in Settings:
    discount_{event_key}_enabled  = "true"/"false"
    discount_{event_key}_percent  = int (0-50)

- When the corresponding reminder is fired for a customer, the scheduler
  writes a marker setting `notified_{customer_id}_{event_key}_{today}`.

- If the client opens the checkout link ON THE SAME DAY, the payment
  router calls `get_active_discount(customer_id)` which finds the most
  recent marker and its associated discount config, applying the % to
  the checkout price automatically.

- Next calendar day: marker no longer matches `today` → no more discount.
  This creates urgency ("promo válida só hoje").

- Supported event_keys (any string, but typically):
    expiration_7d, expiration_3d, expiration_1d, expiration_0d,
    expired_1d, expired_3d, expired_7d, expired_15d, expired_30d
"""
from datetime import datetime, timezone
from typing import Optional, List, Dict

import aiosqlite

from database import DB_PATH, get_setting


# Fired events supported for discount config. Keep in sync with scheduler
# and notifier event keys.
DISCOUNT_EVENTS: List[Dict[str, str]] = [
    {"key": "expiration_7d",  "label": "7 dias antes de vencer",   "kind": "before"},
    {"key": "expiration_3d",  "label": "3 dias antes de vencer",   "kind": "before"},
    {"key": "expiration_1d",  "label": "1 dia antes de vencer",    "kind": "before"},
    {"key": "expiration_0d",  "label": "No dia do vencimento",     "kind": "before"},
    {"key": "expired_1d",     "label": "1 dia após vencer",        "kind": "after"},
    {"key": "expired_3d",     "label": "3 dias após vencer",       "kind": "after"},
    {"key": "expired_7d",     "label": "7 dias após vencer",       "kind": "after"},
    {"key": "expired_15d",    "label": "15 dias após vencer",      "kind": "after"},
    {"key": "expired_30d",    "label": "30 dias após vencer",      "kind": "after"},
]


async def get_discount_for_event(event_key: str) -> Optional[dict]:
    """Return {'percent': int} if a discount is enabled for this event,
    else None. Cached lookups are cheap (settings table is small)."""
    if not event_key:
        return None
    enabled_raw = (await get_setting(f"discount_{event_key}_enabled")
                   or await _legacy_lookup(event_key, "enabled") or "").strip().lower()
    if enabled_raw not in ("true", "1", "yes", "on"):
        return None
    try:
        raw_pct = (await get_setting(f"discount_{event_key}_percent")
                   or await _legacy_lookup(event_key, "percent") or "0")
        percent = int(float(str(raw_pct).strip()))
    except (ValueError, TypeError):
        percent = 0
    if percent <= 0:
        return None
    return {"percent": percent}


async def _legacy_lookup(event_key: str, kind: str) -> str:
    """Backward-compat: old settings were named `discount_7d_enabled` and
    `discount_7d_percent` (only worked for the 7-day reminder). If the new
    per-event key isn't set but the legacy one is, honour it for the 7d
    event so admins don't lose their existing config."""
    if event_key != "expiration_7d":
        return ""
    key = f"discount_7d_{kind}"
    return await get_setting(key) or ""


async def get_active_discount(customer_id: str) -> Optional[dict]:
    """Find any event that (a) is enabled with a discount and (b) has a
    notification marker for this customer TODAY. Returns the best (highest)
    percent among matches.

    Returns {'percent': int, 'source': event_key} or None.
    """
    if not customer_id:
        return None
    today = datetime.now(timezone.utc).date().isoformat()

    # Fetch all `notified_{customer_id}_*_{today}` marker keys in one query.
    prefix = f"notified_{customer_id}_"
    suffix = f"_{today}"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT key FROM settings WHERE key LIKE ? AND key LIKE ?",
            (f"{prefix}%", f"%{suffix}"),
        )
        rows = [r["key"] for r in await cur.fetchall()]

    if not rows:
        return None

    best: Optional[dict] = None
    for k in rows:
        # k = notified_<cust>_<event>_<date> — event may contain "_" itself
        # (like expiration_7d). Strip the known prefix/suffix.
        middle = k[len(prefix):-len(suffix)]
        # Legacy scheduler wrote `notified_<cust>_7_<date>` (just the number,
        # positive for pre-expiration, negative for after). Map both:
        if middle.lstrip("-").isdigit():
            n = int(middle)
            event_key = f"expiration_{n}d" if n >= 0 else f"expired_{abs(n)}d"
        else:
            event_key = middle
        cfg = await get_discount_for_event(event_key)
        if cfg and (best is None or cfg["percent"] > best["percent"]):
            best = {"percent": cfg["percent"], "source": event_key}
    return best


def apply_discount(amount_cents: int, percent: int) -> int:
    """Apply percentage discount, floored to the nearest cent.
    Never returns negative. Percent capped between 0 and 50 to prevent
    admin fat-finger errors (e.g., typing 500 instead of 50)."""
    percent = max(0, min(50, int(percent)))
    discounted = int(amount_cents * (100 - percent) / 100)
    return max(0, discounted)
