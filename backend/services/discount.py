"""Same-day discount for 7-day expiration reminders.

Rule:
- Admin enables `discount_7d_enabled=true` and sets `discount_7d_percent`.
- When the 7-day reminder is fired for a client (scheduler writes
  `notified_{customer_id}_7_{today}` to settings), the client has UNTIL
  the end of THAT SAME calendar day to pay and receive the discount.
- Next day, the key doesn't match `today` anymore → no discount, even
  though the client is now 6 days away from expiring.

This helper reads that state and returns the applicable discount, if any.
"""
from datetime import datetime, timezone
from typing import Optional

from database import get_setting


async def get_active_discount(customer_id: str) -> Optional[dict]:
    """Return {'percent': int, 'source': str} when a same-day 7d discount
    applies for this customer, else None.

    Never returns 0%. Always returns None when disabled/expired/absent.
    """
    if not customer_id:
        return None
    enabled_raw = (await get_setting("discount_7d_enabled") or "").strip().lower()
    if enabled_raw not in ("true", "1", "yes", "on"):
        return None
    try:
        percent = int(await get_setting("discount_7d_percent", "5"))
    except (ValueError, TypeError):
        percent = 5
    if percent <= 0:
        return None
    # Use UTC date to match the scheduler's key. The scheduler writes:
    #   notified_{customer_id}_7_{now.date().isoformat()}   with now=UTC.
    today = datetime.now(timezone.utc).date().isoformat()
    key = f"notified_{customer_id}_7_{today}"
    marked = await get_setting(key, "")
    if not marked:
        return None
    return {"percent": percent, "source": "7d_reminder_same_day"}


def apply_discount(amount_cents: int, percent: int) -> int:
    """Apply percentage discount, floored to the nearest cent.
    Never returns negative. Percent capped between 0 and 100."""
    percent = max(0, min(100, int(percent)))
    discounted = int(amount_cents * (100 - percent) / 100)
    return max(0, discounted)
