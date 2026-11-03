"""Shared helper: after a trial is created, notify the client and schedule
1h + 3h reminders. Uses editable notification templates + pay_link.
"""
import logging

from database import get_setting
from services.notifier import send_notification
from services.reminders import schedule

logger = logging.getLogger(__name__)


async def post_trial_flow(
    phone: str,
    name: str,
    system_type: str,
    painel_user: str,
    painel_pass: str,
    expires_at: str,
    mac: str = None,
    painel_user_id: str = None,
):
    """Send trial_ready message + schedule 1h/3h reminders.

    - painel_user_id is used to build pay_link so the customer renews
      directly on their own subscription.
    """
    public_base = await get_setting("public_base_url", "")
    # Use painel user id if we have it; fall back to the username as identifier
    pay_id = painel_user_id or painel_user or ""
    pay_link = f"{public_base}/pay/{pay_id}" if public_base and pay_id else ""
    if pay_id:
        try:
            from services.pay_link import resolve_pay_link
            pay_link = await resolve_pay_link(pay_id, pay_link)
        except Exception:
            pass

    ctx = {
        "name": name or "",
        "user": painel_user or "",
        "pass": painel_pass or "",
        "expires": expires_at or "",
        "system_type": (system_type or "").upper(),
        "mac": mac or "",
        "pay_link": pay_link,
    }

    # Immediate: trial_ready
    try:
        await send_notification("trial_ready", phone, ctx)
    except Exception:
        logger.exception("post_trial_flow trial_ready failed")

    # Schedule 1h reminder + 3h expiration
    try:
        await schedule("trial_1h_reminder", phone, 60 * 60, ctx)
        await schedule("trial_expired", phone, 3 * 60 * 60, ctx)
    except Exception:
        logger.exception("post_trial_flow schedule failed")
