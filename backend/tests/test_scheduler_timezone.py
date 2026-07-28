"""Regression tests for scheduler timezone bug.

User bug report (2026-02-28): "Agendamento dos lembretes ainda não foi
arrumado". Root cause: `days_until_expiry` compared `.date()` in UTC, so
every night between 21:00-23:59 SP, the UTC calendar day already rolled
to +1 and reminders fired ~3h too early — often on the wrong local day.

Fix: compute the day diff in the admin's display timezone.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.expiration import compute_expiration_info  # noqa: E402


SP = ZoneInfo("America/Sao_Paulo")


def _iso_utc(dt_sp: datetime) -> str:
    """Convert a SP datetime → UTC ISO string (what painel.fun stores)."""
    return dt_sp.astimezone(timezone.utc).isoformat()


def test_days_at_late_evening_sp_uses_local_calendar_day():
    """CRITICAL: at 22:30 SP on Feb 27, expiration on Mar 3 SP must show
    3 days remaining (not 2 like the UTC-based code produced).

    Bug repro: without the fix, `now.date()` in UTC would already be
    Feb 28 (UTC = 01:30 next day), and 28 vs 03 = 3 days looks right...
    but for a plan expiring at 00:00 SP Mar 3 = 03:00 UTC Mar 3, the
    date subtraction was actually right for THAT case. The real bug
    was at date-boundary crossings. Let me test the boundary case:
    23:00 SP Feb 27 (= 02:00 UTC Feb 28), plan expires Feb 29 00:00 SP
    (= 03:00 UTC Feb 29).

    OLD (UTC): (Feb 29 - Feb 28) = 1 day → fires "1d before" prematurely
    NEW (SP):  (Feb 29 - Feb 27) = 2 days → does NOT fire "1d" yet ✅
    """
    # Freeze wall clock at Feb 27 23:00 SP
    fake_now_utc = datetime(2026, 2, 27, 23, 0, tzinfo=SP).astimezone(timezone.utc)

    # Plan expires Feb 29 00:00 SP (a Sunday for example)
    exp_sp = datetime(2026, 3, 1, 0, 0, tzinfo=SP)  # Feb 29 doesn't exist in 2026
    user = {"expires_at": _iso_utc(exp_sp)}

    with patch("services.expiration.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now_utc
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.fromtimestamp = datetime.fromtimestamp
        mock_dt.strptime = datetime.strptime
        # Preserve real datetime class for type checks
        mock_dt.side_effect = datetime

        info = compute_expiration_info(user, tz=SP)

    # In SP: Feb 27 (today) vs Mar 1 (expiration) = 2 days
    assert info["days_until_expiry"] == 2, (
        f"Expected 2 days (SP: 27/02 vs 01/03), got {info['days_until_expiry']}"
    )


def test_days_at_early_morning_sp_is_same_as_utc_day():
    """At 10:00 SP (13:00 UTC), UTC day = SP day, so old and new behavior
    match. Sanity check that we didn't break the normal case."""
    fake_now_utc = datetime(2026, 2, 27, 10, 0, tzinfo=SP).astimezone(timezone.utc)
    exp_sp = datetime(2026, 3, 2, 0, 0, tzinfo=SP)
    user = {"expires_at": _iso_utc(exp_sp)}

    with patch("services.expiration.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now_utc
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.fromtimestamp = datetime.fromtimestamp
        mock_dt.strptime = datetime.strptime

        info = compute_expiration_info(user, tz=SP)

    # SP: Feb 27 → Mar 2 = 3 days
    assert info["days_until_expiry"] == 3


def test_days_exactly_at_midnight_utc_before_midnight_sp():
    """The classic bug case: 22:00 SP Feb 27 = 01:00 UTC Feb 28.
    UTC-based .date() gives Feb 28. SP-based gives Feb 27.

    Plan expires Feb 28 21:00 SP (= 00:00 UTC Mar 1).
    - OLD (UTC): (Mar 1 - Feb 28) = 1 day → fires 1d reminder
    - NEW (SP):  (Feb 28 - Feb 27) = 1 day → same result HERE

    Actually to trigger the divergence we need a plan expiring at a time
    where SP and UTC calendar days differ by 1.

    Real repro: 22:00 SP Feb 27 = 01:00 UTC Feb 28.
    Plan expires Feb 28 22:00 SP = 01:00 UTC Mar 1.
    - OLD (UTC): (Mar 1 - Feb 28) = 1 day
    - NEW (SP):  (Feb 28 - Feb 27) = 1 day → still same 🤔

    The critical case is: the "3d" firing at wrong calendar day.
    At 23:00 SP on day X, the UTC date is X+1. A plan expiring day X+3
    at 21:00 SP (UTC = day X+4 00:00) —
    - OLD (UTC): (X+4 - (X+1)) = 3 days ✅ (accidentally correct)
    - NEW (SP):  (X+3 - X) = 3 days ✅

    They only differ when the expiration itself straddles the UTC/SP
    day boundary. Let me construct that: plan expires day X 22:00 SP
    (= day X+1 01:00 UTC). At 20:00 SP on day X-3 (= 23:00 UTC same day):
    - OLD (UTC): (X+1 - (X-3)) = 4 days
    - NEW (SP):  (X - (X-3)) = 3 days ← DIFFERENT
    """
    # Plan expires 22:00 SP on Feb 28. That's 01:00 UTC Mar 1.
    exp_sp = datetime(2026, 2, 28, 22, 0, tzinfo=SP)
    user = {"expires_at": _iso_utc(exp_sp)}

    # Current time: 20:00 SP Feb 25 (= 23:00 UTC Feb 25)
    fake_now_utc = datetime(2026, 2, 25, 20, 0, tzinfo=SP).astimezone(timezone.utc)

    with patch("services.expiration.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now_utc
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.fromtimestamp = datetime.fromtimestamp
        mock_dt.strptime = datetime.strptime

        info = compute_expiration_info(user, tz=SP)

    # SP calendar: Feb 25 → Feb 28 = 3 days
    # (Old UTC-based code would return 4 here because exp UTC date = Mar 1)
    assert info["days_until_expiry"] == 3, (
        f"Expected 3 days in SP tz, got {info['days_until_expiry']} — "
        "if this returns 4, the UTC-based bug regressed"
    )


def test_days_calculation_symmetric_across_utc_dst_free_zones():
    """Passing an explicit UTC tz should recover the OLD behavior — proves
    the tz param actually controls the calculation."""
    exp_sp = datetime(2026, 2, 28, 22, 0, tzinfo=SP)
    user = {"expires_at": _iso_utc(exp_sp)}

    fake_now_utc = datetime(2026, 2, 25, 20, 0, tzinfo=SP).astimezone(timezone.utc)

    with patch("services.expiration.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now_utc
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.fromtimestamp = datetime.fromtimestamp
        mock_dt.strptime = datetime.strptime

        # With UTC tz explicitly, the old bug reappears (as expected — it's
        # a UTC-vs-SP calendar day mismatch)
        info_utc = compute_expiration_info(user, tz=timezone.utc)

    # UTC: Feb 25 → Mar 1 = 4 days
    assert info_utc["days_until_expiry"] == 4, (
        f"UTC tz should give 4 days, got {info_utc['days_until_expiry']}"
    )
