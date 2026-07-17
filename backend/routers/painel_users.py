"""Painel.fun proxy endpoints with SQLite cache.

Because painel.fun requires solving a Cloudflare Turnstile via 2Captcha
on every fresh login (which takes 20-60 seconds), we cache the users list
in SQLite and refresh it in the background. The `GET /api/painel/users`
endpoint returns the cached list immediately.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from database import DB_PATH
from services import painel

router = APIRouter(prefix="/api/painel", tags=["painel"])
logger = logging.getLogger(__name__)

_refresh_lock = asyncio.Lock()
_refresh_state = {"running": False, "last_error": None, "last_refresh_at": None}


class RenewPayload(BaseModel):
    user_id: str
    system_type: str  # iptv | p2p | hybrid
    plan_months: int  # 1 | 3 | 6 | 12


async def _read_cache() -> tuple[list[dict], Optional[str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT data, updated_at FROM painel_users_cache WHERE id = 'all'")
        row = await cur.fetchone()
        if not row:
            return [], None
        return json.loads(row["data"]), row["updated_at"]


async def _write_cache(users: list[dict]):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO painel_users_cache (id, data, updated_at) VALUES ('all', ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (json.dumps(users), now),
        )
        await db.commit()


async def refresh_cache_task():
    if _refresh_state["running"]:
        return
    async with _refresh_lock:
        _refresh_state["running"] = True
        _refresh_state["last_error"] = None
        try:
            logger.info("Refreshing painel.fun users cache...")
            users = await painel.list_users(limit=2000)
            await _write_cache(users)
            _refresh_state["last_refresh_at"] = datetime.now(timezone.utc).isoformat()
            logger.info("Painel cache refreshed: %d users", len(users))
        except Exception as e:
            logger.exception("Painel cache refresh failed")
            _refresh_state["last_error"] = str(e)
        finally:
            _refresh_state["running"] = False


@router.get("/users")
async def list_users(search: Optional[str] = None, background_tasks: BackgroundTasks = None):
    """Return cached users. Kick off a refresh in background if the cache is old."""
    users, updated_at = await _read_cache()

    # Trigger background refresh if cache is empty or older than 10 minutes
    should_refresh = False
    if not users:
        should_refresh = True
    elif updated_at:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(updated_at)).total_seconds()
            if age > 600:
                should_refresh = True
        except Exception:
            should_refresh = True

    if should_refresh and background_tasks and not _refresh_state["running"]:
        background_tasks.add_task(refresh_cache_task)

    # Build public pay link for each user
    from database import get_setting
    public_base = await get_setting("public_base_url", "")
    for u in users:
        uid = u.get("id") or u.get("user_id") or u.get("username") or u.get("login")
        if uid and public_base:
            u["_pay_link"] = f"{public_base}/pay/{uid}"

    if search:
        s = search.lower()
        def match(u):
            for k in ("name", "full_name", "username", "login", "whatsapp", "phone"):
                v = u.get(k)
                if v and s in str(v).lower():
                    return True
            return False
        users = [u for u in users if match(u)]

    return {
        "users": users,
        "count": len(users),
        "cache_updated_at": updated_at,
        "refreshing": _refresh_state["running"],
        "last_error": _refresh_state["last_error"],
    }


@router.post("/users/refresh")
async def refresh_now():
    """Trigger an immediate cache refresh. Awaits result (may take up to 90s)."""
    await refresh_cache_task()
    users, updated_at = await _read_cache()
    return {
        "success": _refresh_state["last_error"] is None,
        "count": len(users),
        "cache_updated_at": updated_at,
        "error": _refresh_state["last_error"],
    }


@router.get("/status")
async def status():
    _, updated_at = await _read_cache()
    return {
        "cache_updated_at": updated_at,
        "refreshing": _refresh_state["running"],
        "last_error": _refresh_state["last_error"],
        "last_refresh_at": _refresh_state["last_refresh_at"],
    }


@router.post("/renew")
async def renew(payload: RenewPayload):
    """Manually renew a painel user by ID."""
    package_id = painel.get_package_id(payload.system_type, payload.plan_months)
    try:
        result = await painel.renew_user(user_id=payload.user_id, package_id=package_id)
        return {"success": True, "package_id": package_id, "raw": result}
    except Exception as e:
        logger.exception("renew failed")
        raise HTTPException(502, str(e))


@router.get("/package-ids")
async def package_ids():
    """Return the mapping so the frontend can display."""
    return painel.PACKAGE_IDS
