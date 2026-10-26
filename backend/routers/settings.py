"""Settings CRUD + per-event discount config."""
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field

from database import get_all_settings, set_setting, get_setting
from models import SettingsUpdate
from services.discount import DISCOUNT_EVENTS

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings():
    settings = await get_all_settings()
    # Mask sensitive values
    masked = dict(settings)
    for key in ("painel_password", "twocaptcha_key"):
        val = masked.get(key, "")
        if val and len(val) > 6:
            masked[key + "_masked"] = val[:3] + "***" + val[-3:]
    return masked


@router.put("")
async def update_settings(payload: SettingsUpdate):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    for k, v in updates.items():
        await set_setting(k, v)
    return {"success": True, "updated": list(updates.keys())}


# ---------------------------------------------------------------------------
# Discount config: one on/off + percentage per event_key (expiration_7d,
# expired_1d, etc). When enabled, the `{discount_line}` / `{discount_percent}`
# variables auto-populate in that event's notification template, and the
# checkout link applies the discount automatically for the same calendar day.
# ---------------------------------------------------------------------------

class DiscountConfig(BaseModel):
    enabled: bool = False
    percent: int = Field(0, ge=0, le=50)


@router.get("/discounts")
async def list_discounts():
    """Return every supported event with its current discount config."""
    out = []
    for ev in DISCOUNT_EVENTS:
        enabled_raw = (await get_setting(f"discount_{ev['key']}_enabled") or "").strip().lower()
        percent_raw = await get_setting(f"discount_{ev['key']}_percent") or "0"
        try:
            percent = int(float(percent_raw))
        except (ValueError, TypeError):
            percent = 0
        # Legacy fallback for the old 7d-only setting
        if ev["key"] == "expiration_7d" and not enabled_raw:
            enabled_raw = (await get_setting("discount_7d_enabled") or "").strip().lower()
            if percent == 0:
                try:
                    percent = int(float(await get_setting("discount_7d_percent") or "0"))
                except (ValueError, TypeError):
                    percent = 0
        out.append({
            "event_key": ev["key"],
            "label": ev["label"],
            "kind": ev["kind"],
            "enabled": enabled_raw in ("true", "1", "yes", "on"),
            "percent": percent,
        })
    return {"events": out}


@router.put("/discounts/{event_key}")
async def update_discount(event_key: str, payload: DiscountConfig):
    """Turn a discount on/off and set its % for a specific event."""
    valid_keys = {ev["key"] for ev in DISCOUNT_EVENTS}
    if event_key not in valid_keys:
        return {"error": f"Unknown event_key '{event_key}'"}, 400
    await set_setting(f"discount_{event_key}_enabled", "true" if payload.enabled else "false")
    await set_setting(f"discount_{event_key}_percent", str(payload.percent))
    # Mirror to legacy 7d setting so old code paths still work
    if event_key == "expiration_7d":
        await set_setting("discount_7d_enabled", "true" if payload.enabled else "false")
        await set_setting("discount_7d_percent", str(payload.percent))
    return {"success": True, "event_key": event_key, "enabled": payload.enabled, "percent": payload.percent}
