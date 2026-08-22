"""Remote self-update endpoint — triggers `sudo bash update.sh` from the UI.

Security:
- Requires admin JWT (enforced by middleware).
- ALSO requires the admin password in the request body (double-confirmation
  for a destructive/system-level action).
- Executes in a detached subprocess so the current request returns
  immediately — the backend will restart mid-response.

Frontend polls `GET /api/system/update-status` to know when it's done.
"""
import asyncio
import logging
import os
import shlex
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from services.auth import verify_admin_password

router = APIRouter(prefix="/api/system", tags=["system"])
logger = logging.getLogger(__name__)

UPDATE_SCRIPT = "/app/update.sh"
STATUS_FILE = "/tmp/whatsflow-update-status.json"
LOG_FILE_PATTERN = "/tmp/whatsflow-update-*.log"


class UpdateRequest(BaseModel):
    password: str


def _read_status() -> dict:
    if not Path(STATUS_FILE).exists():
        return {"state": "idle", "started_at": None, "finished_at": None,
                "last_error": None}
    try:
        import json
        return json.loads(Path(STATUS_FILE).read_text())
    except Exception:
        return {"state": "unknown", "last_error": "status file corrupted"}


def _write_status(patch: dict):
    import json
    cur = _read_status()
    cur.update(patch)
    try:
        Path(STATUS_FILE).write_text(json.dumps(cur))
    except Exception:
        logger.exception("failed to write update status")


def _latest_log_path() -> str:
    import glob
    files = sorted(glob.glob(LOG_FILE_PATTERN))
    return files[-1] if files else ""


@router.post("/update")
async def trigger_update(payload: UpdateRequest):
    """Kick off `sudo bash update.sh` in the background. Returns 202 with
    the log path so the client can poll for status/output.

    Password is re-verified here (belt-and-suspenders: JWT already required
    by middleware). Prevents e.g. a stolen JWT from also being able to
    trigger a self-update.
    """
    if not await verify_admin_password(payload.password):
        raise HTTPException(401, "Senha inválida")

    # Don't allow overlapping runs
    cur = _read_status()
    if cur.get("state") == "running":
        since = int(time.time() - (cur.get("started_at") or time.time()))
        raise HTTPException(409, f"Update já em andamento há {since}s. Aguarde.")

    if not Path(UPDATE_SCRIPT).exists():
        raise HTTPException(500, f"Script {UPDATE_SCRIPT} não encontrado neste ambiente")

    # Log file: pre-create so the client can tail immediately.
    ts = int(time.time())
    log_path = f"/tmp/whatsflow-update-{ts}.log"
    Path(log_path).touch()

    _write_status({
        "state": "running", "started_at": ts, "finished_at": None,
        "log_path": log_path, "last_error": None,
    })

    # Detached process — survives the backend restart the script itself
    # will trigger via `supervisorctl restart backend`.
    #
    # `setsid` puts the child in a new session so SIGHUP from the parent
    # dying doesn't propagate. `nohup` + stdout/stderr redirect closes the
    # descriptors so the child truly detaches.
    cmd = f"setsid nohup sudo bash {shlex.quote(UPDATE_SCRIPT)} > {shlex.quote(log_path)} 2>&1 < /dev/null &"
    try:
        subprocess.Popen(
            ["/bin/bash", "-c", cmd],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except Exception as e:
        _write_status({"state": "error", "last_error": str(e),
                       "finished_at": int(time.time())})
        raise HTTPException(500, f"Falha ao iniciar update: {e}")

    logger.warning("SELF-UPDATE triggered — log=%s pid_launcher=detached", log_path)
    return {
        "ok": True,
        "state": "running",
        "log_path": log_path,
        "message": "Update iniciado. Backend vai reiniciar em ~1-2 min.",
    }


@router.get("/update-status")
async def update_status(tail_lines: int = 80):
    """Return the current update state + the last N lines of the log.
    Frontend polls this every 3s during a running update."""
    tail_lines = max(1, min(int(tail_lines), 500))
    cur = _read_status()

    log_path = cur.get("log_path") or _latest_log_path()
    tail_content = ""
    finished_hint = False

    if log_path and Path(log_path).exists():
        try:
            # Simple tail — the file is small (kilobytes typically)
            with open(log_path, "rb") as f:
                data = f.read()
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()
            tail_content = "\n".join(lines[-tail_lines:])
            # The update script writes "✔ update finished" or similar as its
            # last line — heuristic to detect completion since we can't wait
            # on the detached process.
            marker_ok = any(k in tail_content.lower() for k in (
                "update finished", "update complete", "healthcheck passed",
                "concluído", "concluido",
            ))
            marker_err = any(k in tail_content.lower() for k in (
                "healthcheck failed", "rollback", "aborting", "abortando",
                "erro fatal",
            ))
            if marker_ok:
                finished_hint = True
                if cur.get("state") == "running":
                    _write_status({"state": "success", "finished_at": int(time.time())})
                    cur = _read_status()
            elif marker_err:
                if cur.get("state") == "running":
                    _write_status({"state": "error", "finished_at": int(time.time()),
                                   "last_error": "script reported failure — check log"})
                    cur = _read_status()
        except Exception as e:
            tail_content = f"(erro lendo log: {e})"

    return {
        "state": cur.get("state", "idle"),
        "started_at": cur.get("started_at"),
        "finished_at": cur.get("finished_at"),
        "last_error": cur.get("last_error"),
        "log_path": log_path,
        "tail": tail_content,
        "finished_hint": finished_hint,
    }
