"""Compute normalized expiration and status for a painel.fun user."""
from datetime import datetime, timezone, tzinfo
from typing import Optional
from zoneinfo import ZoneInfo


EXPIRATION_KEYS = (
    "exp_date",           # painel.fun (UNIX SECONDS)
    "expires_at", "expiration", "expiry_date", "expire_date",
    "expiration_date", "expires", "valid_until", "vencimento", "expira_em",
)
STATUS_KEYS = (
    "enabled",  # painel.fun (0/1)
    "active", "is_active", "status", "state", "situacao",
)


def _parse_dt(value) -> Optional[datetime]:
    if value in (None, "", 0):
        return None
    # UNIX timestamps (int or numeric string) — painel.fun uses seconds
    if isinstance(value, (int, float)):
        try:
            # Values > ~10^12 are likely milliseconds
            ts = value / 1000 if value > 10**12 else value
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        try:
            n = int(s)
            ts = n / 1000 if n > 10**12 else n
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
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


def compute_expiration_info(user: dict, tz: Optional[tzinfo] = None) -> dict:
    """Return dict with: expires_at_iso, days_until_expiry, status.

    status is one of: active | expiring_soon | expired | unknown
    days_until_expiry may be negative (past-due). None if no date.

    IMPORTANT: `days_until_expiry` compares CALENDAR DATES in the admin's
    display timezone (default America/Sao_Paulo). Using UTC dates caused
    reminders to fire ~3h early every night between 21:00-23:59 SP, when
    UTC already rolled to the next calendar day.

    Pass `tz` to control the timezone; defaults to America/Sao_Paulo.
    """
    if not isinstance(user, dict):
        return {"expires_at_iso": None, "days_until_expiry": None, "status": "unknown"}

    if tz is None:
        tz = ZoneInfo("America/Sao_Paulo")

    raw = _pick(user, EXPIRATION_KEYS)
    exp_dt = _parse_dt(raw) if raw is not None else None

    now = datetime.now(timezone.utc)
    days = None
    if exp_dt:
        # Compare dates in the ADMIN'S timezone, not UTC. Otherwise the day
        # boundary rolls at 21:00 SP and reminders fire 3h too early.
        days = (exp_dt.astimezone(tz).date() - now.astimezone(tz).date()).days

    # Determine status — painel.fun uses `enabled` as 0/1
    enabled_raw = user.get("enabled")
    if enabled_raw is not None:
        forced_active = enabled_raw in (1, "1", True, "true")
        forced_inactive = enabled_raw in (0, "0", False, "false")
    else:
        raw_status = str(_pick(user, ("active", "is_active", "status", "state", "situacao")) or "").lower()
        forced_active = raw_status in ("active", "ativo", "1", "true", "enabled", "on")
        forced_inactive = raw_status in ("inactive", "inativo", "disabled", "0", "false", "blocked", "banned", "off")

    if days is not None:
        if days < 0:
            status = "expired"
        elif days <= 3:
            status = "expiring_soon"
        else:
            status = "active"
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
