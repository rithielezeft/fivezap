"""Trials endpoint — creates a real trial in painel.fun."""
import json
import logging
from fastapi import APIRouter, HTTPException
from typing import List
import aiosqlite

from database import DB_PATH
from models import Trial, TrialCreate, new_id, now_iso
from services import painel
from services.bot import log_activity

router = APIRouter(prefix="/api/trials", tags=["trials"])
logger = logging.getLogger(__name__)


@router.get("", response_model=List[Trial])
async def list_trials():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM trials ORDER BY created_at DESC LIMIT 200")
        rows = await cur.fetchall()
        return [Trial(**{k: v for k, v in dict(r).items() if k != "raw_response"}) for r in rows]


@router.post("", response_model=dict)
async def create_trial(payload: TrialCreate):
    """Create a trial via painel.fun. Returns painel data + saved trial."""
    try:
        result = await painel.create_trial(
            system_type=payload.system_type,
            mac=payload.mac,
            name=payload.name,
            whatsapp=payload.whatsapp,
        )
    except Exception as e:
        logger.exception("Trial creation failed")
        await log_activity("trial_error", str(e), payload.customer_id, "error")
        raise HTTPException(502, f"Painel error: {e}")

    trial_id = new_id()
    painel_user = result.get("username") or result.get("user") or result.get("login")
    painel_pass = result.get("password") or result.get("pass")
    expires = result.get("expires_at") or result.get("expiration")
    trial_user_id = str(result.get("id") or result.get("user_id") or "")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO trials (id, customer_id, system_type, mac, painel_user, painel_pass, trial_user_id, expires_at, created_at, raw_response) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trial_id, payload.customer_id, payload.system_type, payload.mac,
             painel_user, painel_pass, trial_user_id, expires, now_iso(),
             json.dumps(result)),
        )
        if payload.customer_id:
            await db.execute(
                "UPDATE customers SET system_type = ?, mac = COALESCE(?, mac), painel_username = ?, painel_password = ?, expires_at = ?, updated_at = ? WHERE id = ?",
                (payload.system_type, payload.mac, painel_user, painel_pass, expires, now_iso(), payload.customer_id),
            )
        await db.commit()

    await log_activity("trial_created", f"Teste {payload.system_type} criado manualmente", payload.customer_id, "success", result)

    # Refresh the painel users cache so the /customers page shows the new trial
    try:
        import asyncio as _asyncio
        from routers.painel_users import refresh_cache_task
        _asyncio.create_task(refresh_cache_task())
    except Exception:
        logger.exception("Failed to schedule painel users cache refresh")

    # Fire trial_ready + schedule 1h/3h reminders (only if we have a phone)
    phone = payload.whatsapp
    if not phone and payload.customer_id:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute("SELECT whatsapp, name FROM customers WHERE id = ?", (payload.customer_id,))
                row = await cur.fetchone()
                if row:
                    phone = row["whatsapp"]
                    payload_name = payload.name or row["name"]
                else:
                    payload_name = payload.name
        except Exception:
            payload_name = payload.name
    else:
        payload_name = payload.name

    if phone:
        try:
            from services.trial_flow import post_trial_flow
            await post_trial_flow(
                phone=phone,
                name=payload_name or "",
                system_type=payload.system_type,
                painel_user=painel_user or "",
                painel_pass=painel_pass or "",
                expires_at=expires or "",
                mac=payload.mac,
                painel_user_id=trial_user_id,
            )
        except Exception:
            logger.exception("post_trial_flow failed")

    return {
        "id": trial_id,
        "painel_user": painel_user,
        "painel_pass": painel_pass,
        "expires_at": expires,
        "raw": result,
    }


@router.post("/test-login")
async def test_login():
    """Test painel.fun login (solves Turnstile + login)."""
    try:
        token = await painel.login(force=True)
        return {"success": True, "token_preview": token[:20] + "..."}
    except Exception as e:
        logger.exception("Login test failed")
        return {"success": False, "error": str(e)}
