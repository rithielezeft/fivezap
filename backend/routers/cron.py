"""Platform cron webhooks."""
import asyncio
import hmac
import logging
import os

from fastapi import APIRouter, HTTPException, Request


router = APIRouter(prefix="/api/cron", tags=["cron"])
logger = logging.getLogger(__name__)
_seen_runs: list = []


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
    # In-memory run-id dedupe; send_report itself is idempotent per month.
    if run_id and run_id in _seen_runs:
        return {"accepted": True, "duplicate": True}
    if run_id:
        _seen_runs.append(run_id)
        del _seen_runs[:-200]

    from services.finance_report import maybe_send_previous_month
    asyncio.create_task(maybe_send_previous_month())
    return {"accepted": True}
