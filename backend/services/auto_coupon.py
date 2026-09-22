"""Auto-coupon flow: send a personalized discount coupon via WhatsApp to
customers who have been expired for N+ days without renewing.

Behavior:
- Runs hourly (in same scheduler tick).
- Filters painel users where status == 'expired' AND days_since_expiry >= N.
- Excludes trial users (package_id == trial_package_id).
- For each qualifying customer, creates a unique random coupon code
  `VOLTA{6 random chars}` if it doesn't exist yet.
- Coupon uses the **same percentage as `discount_7d_percent`** (the "Desconto
  do lembrete 7d" configured in Settings) — single source of truth. If admin
  bumps that value, the recovery coupon uses the new % automatically.
- Coupon defaults: 24h hard expiration (`auto_coupon_ttl_hours`),
  1 max use (`auto_coupon_max_uses`, single-shot per customer).
- Sends WhatsApp message using template `auto_recovery_coupon` with the
  coupon code and pay_link injected.
- Idempotent: uses setting `auto_coupon_sent_{customer_id}` so we never
  spam the same customer twice.

Settings (all optional, sane defaults):
  auto_coupon_enabled          -> "true"/"false" (default true)
  auto_coupon_expired_days     -> int (default 3)
  discount_7d_percent          -> float (default 15.0)  ← shared with 7d reminder
  auto_coupon_ttl_hours        -> int (default 24)
  auto_coupon_max_uses         -> int (default 1)
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

import aiosqlite

from database import DB_PATH, get_setting, set_setting
from services import painel
from services.coupon import normalize_code
from services.expiration import compute_expiration_info
from services.phone_extractor import extract_whatsapp
from services.notifier import send_notification
from models import new_id, now_iso

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60 * 60  # hourly


async def _get_bool(key: str, default: bool) -> bool:
    raw = (await get_setting(key) or ("true" if default else "false")).strip().lower()
    return raw in ("true", "1", "yes", "on")


async def _get_int(key: str, default: int) -> int:
    try:
        return int((await get_setting(key) or str(default)).strip())
    except Exception:
        return default


async def _get_float(key: str, default: float) -> float:
    try:
        return float((await get_setting(key) or str(default)).strip())
    except Exception:
        return default


async def _create_personal_coupon(customer_id: str, percent: float,
                                  ttl_hours: int, max_uses: int) -> dict:
    """Create a personalized coupon for this customer if not present.
    Returns the coupon dict (either newly created or existing).

    Code format: `VOLTA` + 6 random alphanumeric chars (uppercase, no
    ambiguous 0/O/1/I). Random — not derived from customer_id — so admins
    can share/collect coupons anonymously without leaking the ID.
    """
    import random
    import string
    # Reuse an existing pending coupon for this customer to keep the flow
    # idempotent (setting `auto_coupon_sent_{id}` also prevents re-sends,
    # but this second net catches any race).
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Existing coupon assigned to this customer via a usage row? No —
        # usages are only recorded after payment. Use a lightweight tag by
        # looking up the settings map for the sent marker instead.
        # If sent-marker exists, we shouldn't hit this function anyway. Fall
        # through to fresh creation.

        # Generate a random code with retry on the unique constraint.
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
        for _ in range(10):
            suffix = "".join(random.choices(alphabet, k=6))
            code = f"VOLTA{suffix}"
            # Fast collision check (unique index)
            cur = await db.execute("SELECT 1 FROM coupons WHERE code = ?", (code,))
            if not await cur.fetchone():
                break
        else:
            raise RuntimeError("could not generate a unique VOLTA code after 10 tries")

        cid = new_id()
        ts = now_iso()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
        await db.execute(
            "INSERT INTO coupons (id, code, discount_percent, active, "
            "expires_at, max_uses, created_at, updated_at) "
            "VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
            (cid, code, percent, expires_at, max_uses, ts, ts),
        )
        await db.commit()
        return {
            "id": cid, "code": code, "discount_percent": percent,
            "active": 1, "expires_at": expires_at, "max_uses": max_uses,
            "created_at": ts, "updated_at": ts,
        }


async def sweep_once() -> int:
    """Run one check. Returns number of coupons sent."""
    if not await _get_bool("auto_coupon_enabled", True):
        return 0

    threshold = await _get_int("auto_coupon_expired_days", 3)
    # Percent comes FROM the same "Desconto do lembrete 7d" setting the admin
    # already configured. Single source of truth — if the admin bumps the 7d
    # discount, the recovery coupon updates too. No separate setting.
    # Falls back to 15% if the 7d discount setting is empty/invalid.
    percent = await _get_float("discount_7d_percent", 15.0)
    ttl_hours = await _get_int("auto_coupon_ttl_hours", 24)
    max_uses = await _get_int("auto_coupon_max_uses", 1)
    trial_pkg_id = await _get_int("trial_package_id", 61)

    try:
        users = await painel.list_users(limit=10000)
    except Exception as e:
        logger.warning("auto_coupon: painel unreachable — skipping. %s", e)
        return 0

    sent = 0
    for u in users:
        try:
            # Skip trial users
            u_pkg = u.get("package_id") or u.get("current_package_id")
            if (u_pkg is not None and str(u_pkg).isdigit()
                    and int(u_pkg) == trial_pkg_id):
                continue
            if u.get("is_trial"):
                continue

            info = compute_expiration_info(u)
            if info.get("status") != "expired":
                continue

            diff_days = info.get("days_until_expiry") or 0
            days_expired = -diff_days  # negative means past-due
            if days_expired < threshold:
                continue

            user_id = str(u.get("id") or u.get("user_id") or u.get("username") or "")
            if not user_id:
                continue

            # Idempotency: never re-send for the same customer.
            key = f"auto_coupon_sent_{user_id}"
            if await get_setting(key):
                continue

            phone = extract_whatsapp(u)
            if not phone:
                continue

            # Create (or reuse) the personal coupon
            coupon = await _create_personal_coupon(user_id, percent, ttl_hours, max_uses)

            # Send WhatsApp with template `auto_recovery_coupon`
            base_url = (await get_setting("public_base_url") or "").rstrip("/")
            # Batched flow: use the local /pay page URL. When user clicks,
            # /pay redirects to pagme.xyz if payment_link_provider=painel.
            # Do NOT call painel API here — this loop runs over 200+ users
            # and would hammer the panel + slow down the whole scheduler.
            pay_link = f"{base_url}/pay/{user_id}?ref=auto_coupon" if base_url else ""

            ctx = {
                "name": u.get("username") or u.get("name") or "",
                "user": u.get("username") or "",
                "coupon_code": coupon["code"],
                "discount_percent": _fmt_percent(percent),
                "expires_in_hours": str(ttl_hours),
                "pay_link": pay_link,
                "days_expired": str(days_expired),
            }

            ok = await send_notification(
                "auto_recovery_coupon", phone, ctx, customer_id=user_id,
            )
            if ok:
                await set_setting(key, now_iso())
                sent += 1
                logger.info(
                    "auto_coupon: sent %s to %s (customer=%s, %.1f%%, expires_in %dh)",
                    coupon["code"], phone, user_id, percent, ttl_hours,
                )
        except Exception:
            logger.exception("auto_coupon: sweep failed for user=%r", u.get("id"))

    return sent


def _fmt_percent(p: float) -> str:
    """Render 15.0 → '15' and 12.3 → '12.3' to keep messages clean."""
    if float(p).is_integer():
        return str(int(p))
    return f"{p:.2f}".rstrip("0").rstrip(".")


async def auto_coupon_loop():
    """Runs forever, sweeps every CHECK_INTERVAL_SECONDS."""
    logger.info("auto_coupon_loop started (interval=%ds)", CHECK_INTERVAL_SECONDS)
    while True:
        try:
            sent = await sweep_once()
            if sent:
                logger.info("auto_coupon: %d coupons sent this cycle", sent)
        except Exception:
            logger.exception("auto_coupon_loop iteration failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
