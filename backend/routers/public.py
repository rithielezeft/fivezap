"""Public endpoints: /teste form + shared."""
import logging
from fastapi import APIRouter, HTTPException
import aiosqlite

from database import DB_PATH
from models import PublicTrialRequest, new_id, now_iso
from services import painel
from services.bot import log_activity, find_or_create_customer

router = APIRouter(prefix="/api/public", tags=["public"])
logger = logging.getLogger(__name__)


@router.post("/trial")
async def public_request_trial(payload: PublicTrialRequest):
    """Public form on /teste page — creates trial and returns credentials."""
    phone_digits = "".join(c for c in payload.whatsapp if c.isdigit())

    # Find or create customer
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM customers WHERE whatsapp = ?", (phone_digits,))
        row = await cur.fetchone()
        if row:
            customer_id = row["id"]
        else:
            customer_id = new_id()
            now = now_iso()
            await db.execute(
                "INSERT INTO customers (id, name, whatsapp, system_type, mac, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'prospect', ?, ?)",
                (customer_id, payload.name, phone_digits, payload.system_type, payload.mac, now, now),
            )
            await db.commit()

    try:
        result = await painel.create_trial(
            system_type=payload.system_type,
            mac=payload.mac,
            name=payload.name,
            whatsapp=phone_digits,
        )
    except Exception as e:
        logger.exception("Public trial creation failed")
        await log_activity("public_trial_error", str(e), customer_id, "error")
        raise HTTPException(502, f"Erro ao criar teste: {e}")

    painel_user = result.get("username") or result.get("user") or result.get("login")
    painel_pass = result.get("password") or result.get("pass")
    expires = result.get("expires_at") or result.get("expiration")

    import json
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO trials (id, customer_id, system_type, mac, painel_user, painel_pass, trial_user_id, expires_at, created_at, raw_response) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), customer_id, payload.system_type, payload.mac,
             painel_user, painel_pass, str(result.get("id") or ""), expires, now_iso(),
             json.dumps(result)),
        )
        await db.execute(
            "UPDATE customers SET system_type = ?, mac = COALESCE(?, mac), painel_username = ?, painel_password = ?, expires_at = ?, updated_at = ? WHERE id = ?",
            (payload.system_type, payload.mac, painel_user, painel_pass, expires, now_iso(), customer_id),
        )
        await db.commit()

    await log_activity("public_trial_created", f"Teste solicitado por {payload.name}", customer_id, "success")

    return {
        "user": painel_user,
        "password": painel_pass,
        "expires_at": expires,
        "system_type": payload.system_type,
    }
