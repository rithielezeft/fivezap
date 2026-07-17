"""Settings CRUD."""
from fastapi import APIRouter

from database import get_all_settings, set_setting
from models import SettingsUpdate

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
