"""Compute normalized expiration and status for a painel.fun user."""
from datetime import datetime, timezone
from typing import Optional


EXPIRATION_KEYS = (
    "expires_at", "expiration", "expiry_date", "expire_date",
    "expiration_date", "expires", "valid_until", "vencimento", "expira_em",
)
STATUS_KEYS = ("active", "is_active", "status", "state", "situacao")


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    # ISO 8601 with Z
    for fmt in None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S":
        try:
            if fmt is None:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            continue
    return None


def _pick(user: dict, keys) -> Optional[str]:
    for k in keys:
        v = user.get(k)
        if v not in (None, ""):
            return v
    return None


def compute_expiration_info(user: dict) -> dict:
    """Return dict with: expires_at_iso, days_until_expiry, status.

    status is one of: active | expiring_soon | expired | unknown
    days_until_expiry may be negative (past-due). None if no date.
    """
    if not isinstance(user, dict):
        return {"expires_at_iso": None, "days_until_expiry": None, "status": "unknown"}

    raw = _pick(user, EXPIRATION_KEYS)
    exp_dt = _parse_dt(raw) if raw else None

    now = datetime.now(timezone.utc)
    days = None
    if exp_dt:
        days = (exp_dt.date() - now.date()).days

    # Determine status
    raw_status = str(_pick(user, STATUS_KEYS) or "").lower()
    forced_active = raw_status in ("active", "ativo", "1", "true", "enabled", "on")
    forced_inactive = raw_status in ("inactive", "inativo", "disabled", "0", "false", "blocked", "banned", "off")

    if days is not None:
        if days < 0:
            status = "expired"
        elif days <= 3:
            status = "expiring_soon"
        else:
            status = "active"
        # Panel-declared inactive overrides date-based active
        if forced_inactive and status == "active":
            status = "expired"
    else:
        if forced_active:
            status = "active"
        elif forced_inactive:
            status = "expired"
        else:
            status = "unknown"

    return {
        "expires_at_iso": exp_dt.isoformat() if exp_dt else None,
        "days_until_expiry": days,
        "status": status,
    }
