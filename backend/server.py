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
from routers import customers, trials, templates, whatsapp, settings, payments, public, dashboard, messages, painel_users, notifications, auth, uploads, reminders

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
    logger.info("Starting WhatsApp Node service from %s", wa_dir)
    _wa_process = subprocess.Popen(
        ["node", "index.js"],
        cwd=str(wa_dir),
        stdout=open("/var/log/whatsapp-service.out.log", "a"),
        stderr=open("/var/log/whatsapp-service.err.log", "a"),
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
    yield
    task_exp.cancel()
    task_rem.cancel()
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
    if not path.startswith("/api/") or is_public(path):
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


@app.get("/api/")
async def root():
    return {"service": "WhatsFlow", "status": "ok"}


@app.get("/api/health")
async def health():
    return {"status": "healthy"}
