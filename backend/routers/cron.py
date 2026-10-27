"""Platform cron webhooks."""
import asyncio
import hmac
import logging
import os

from fastapi import APIRouter, HTTPException, Request

from database import get_setting, set_setting

router = APIRouter(prefix="/api/cron", tags=["cron"])
logger = logging.getLogger(__name__)


@router.post("/monthly-report")
async def monthly_report(request: Request):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    secret = os.environ.get("WEBHOOK_CRON_SECRET") or ""
    auth = request.headers.get("authorization") or ""
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    if not secret or not token or not hmac.compare_digest(token, secret):
        raise HTTPException(401, "unauthorized")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid body")
    run_id = request.headers.get("x-webhook-id") or (body or {}).get("run_id") or ""
    if run_id and await get_setting(f"cron_run_{run_id}"):
        return {"accepted": True, "duplicate": True}
    if run_id:
        await set_setting(f"cron_run_{run_id}", "1")

    from services.finance_report import maybe_send_previous_month
    asyncio.create_task(maybe_send_previous_month())
    return {"accepted": True}
