"""WhatsFlow — Main FastAPI application."""
import asyncio
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from database import init_db
from services.scheduler import check_expirations_loop
from services.reminders import reminder_loop
from services.auth import seed_admin_password, is_public, require_admin
from routers import customers, trials, templates, whatsapp, settings, payments, public, dashboard, messages, painel_users, notifications, auth, uploads, reminders, coupons

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("whatsflow")

_wa_process = None


def _start_whatsapp_service():
    """Spawn the Node.js whatsapp service as a child process."""
    global _wa_process
    wa_dir = ROOT_DIR.parent / "whatsapp-service"
    if not (wa_dir / "index.js").exists():
        logger.warning("WhatsApp service dir not found: %s", wa_dir)
        return

    # Write logs to a user-writable directory (works even without root)
    log_dir = Path(os.environ.get("WA_LOG_DIR") or (ROOT_DIR / "logs"))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        log_dir = Path("/tmp")

    logger.info("Starting WhatsApp Node service from %s (logs at %s)", wa_dir, log_dir)
    try:
        stdout_f = open(log_dir / "whatsapp-service.out.log", "a")
        stderr_f = open(log_dir / "whatsapp-service.err.log", "a")
    except Exception:
        # Fallback: inherit parent's stdout/stderr (goes to systemd journal)
        stdout_f = None
        stderr_f = None

    _wa_process = subprocess.Popen(
        ["node", "index.js"],
        cwd=str(wa_dir),
        stdout=stdout_f,
        stderr=stderr_f,
        env={
            **os.environ,
            "PORT": "3001",
            "BACKEND_WEBHOOK_URL": "http://localhost:8001/api/whatsapp/incoming",
        },
    )
    logger.info("WhatsApp Node service PID=%s", _wa_process.pid)


def _stop_whatsapp_service():
    global _wa_process
    if _wa_process:
        logger.info("Stopping WhatsApp Node service PID=%s", _wa_process.pid)
        try:
            _wa_process.terminate()
            _wa_process.wait(timeout=5)
        except Exception:
            try:
                _wa_process.kill()
            except Exception:
                pass
        _wa_process = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_admin_password()
    _start_whatsapp_service()
    task_exp = asyncio.create_task(check_expirations_loop())
    task_rem = asyncio.create_task(reminder_loop())
    # Launch the InfinitePay reconciliation poller. FastAPI ignores
    # @app.on_event("startup") when a `lifespan=` handler is set, so we
    # must start it here — otherwise pending payments never get polled.
    try:
        from services.payment_poller import start_poller, stop_poller
        start_poller()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to start payment poller (non-fatal)")
        stop_poller = None  # type: ignore

    # Background painel.fun cache refresher — keeps the Clientes page in
    # sync with the panel. Interval is read live from the admin-controlled
    # `painel_refresh_interval_seconds` setting so raising it in the UI
    # takes effect on the next tick (no restart needed).
    async def _painel_refresh_loop():
        import logging
        from routers.painel_users import refresh_cache_task
        from database import get_setting
        log = logging.getLogger("painel_refresh_loop")
        log.info("painel_refresh_loop started (interval read from settings)")
        while True:
            try:
                await refresh_cache_task()
            except Exception:
                log.exception("painel_refresh_loop iteration failed (keeping loop alive)")
            # Read interval fresh each cycle so the admin can change it live.
            try:
                interval_raw = (await get_setting("painel_refresh_interval_seconds") or "300").strip()
                interval = max(30, int(interval_raw))
            except Exception:
                interval = 300
            await asyncio.sleep(interval)

    task_painel_refresh = asyncio.create_task(_painel_refresh_loop())

    # Delivery-queue retry loop: retries failed WhatsApp notifications every
    # 10s so no client stays without confirmation.
    from services.delivery_queue import retry_loop as _delivery_retry_loop, stop_retry_loop as _stop_delivery
    task_delivery_retry = asyncio.create_task(_delivery_retry_loop())

    # Renewal retry loop: automatically re-attempts painel.fun renewals
    # that failed with transient errors (e.g. ERROR_NO_SLOT_AVAILABLE).
    # Backoff: 5min, 15min, 30min, 1h, 4h, 12h — 6 attempts over ~19h.
    from services.renewal_retry import renewal_retry_loop as _renewal_retry_loop
    task_renewal_retry = asyncio.create_task(_renewal_retry_loop())

    yield
    task_exp.cancel()
    task_rem.cancel()
    task_painel_refresh.cancel()
    task_delivery_retry.cancel()
    task_renewal_retry.cancel()
    try:
        _stop_delivery()
    except Exception:
        pass
    if stop_poller:
        try:
            stop_poller()
        except Exception:
            pass
    _stop_whatsapp_service()


app = FastAPI(title="WhatsFlow", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# Auth middleware — protects all /api/* endpoints except public ones
@app.middleware("http")
async def auth_middleware(request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or is_public(path, request.method):
        return await call_next(request)
    # Allow OPTIONS (CORS preflight)
    if request.method == "OPTIONS":
        return await call_next(request)
    # Verify token
    from starlette.responses import JSONResponse
    try:
        await require_admin(request)
    except Exception as e:
        detail = getattr(e, "detail", str(e))
        status = getattr(e, "status_code", 401)
        return JSONResponse({"detail": detail}, status_code=status)
    return await call_next(request)


# Include routers
app.include_router(auth.router)
app.include_router(uploads.router)
app.include_router(customers.router)
app.include_router(trials.router)
app.include_router(templates.router)
app.include_router(whatsapp.router)
app.include_router(settings.router)
app.include_router(payments.router)
app.include_router(public.router)
app.include_router(dashboard.router)
app.include_router(messages.router)
app.include_router(painel_users.router)
app.include_router(notifications.router)
app.include_router(reminders.router)
app.include_router(coupons.router)


@app.get("/api/")
async def root():
    return {"service": "WhatsFlow", "status": "ok"}


@app.get("/api/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/health/poller")
async def health_poller():
    """Observability endpoint: is the payment poller task alive?

    Returns 200 with running=true when the background task is scheduled and
    hasn't errored out. Used for smoke tests + monitoring to catch silent
    startup failures (e.g. the earlier @app.on_event vs lifespan= regression).
    """
    from services import payment_poller
    task = payment_poller._poller_task
    return {
        "running": bool(task and not task.done()),
        "task_name": task.get_name() if task else None,
        "task_done": bool(task and task.done()),
    }


# NOTE: startup/shutdown for the payment poller is handled inside the
# `lifespan()` context manager above (see start of file). FastAPI ignores
# @app.on_event decorators when a lifespan= is set — do NOT re-introduce
# them here.
