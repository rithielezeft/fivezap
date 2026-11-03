"""Uploads router — images are saved on the local disk (Raspberry) and, when
EMERGENT_LLM_KEY is set, mirrored to Emergent object storage."""
import asyncio
import logging
import os
import re
import uuid
from pathlib import Path

import requests
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import Response

from services.auth import require_admin

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR") or (Path(__file__).parent.parent / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
APP_PREFIX = "whatsflow/uploads"

ALLOWED_EXT = {"jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp"}
MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
        "webp": "image/webp", "heic": "image/heic", "heif": "image/heif", "bmp": "image/bmp"}
MAX_SIZE_MB = 15
_UPLOAD_RE = re.compile(r"/api/uploads/([A-Za-z0-9_.-]+)")

_storage_key = None


def _cloud_enabled() -> bool:
    return bool(os.environ.get("EMERGENT_LLM_KEY"))


def _init_storage(force: bool = False) -> str:
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": os.environ.get("EMERGENT_LLM_KEY")}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


def _request(method: str, path: str, headers=None, **kw):
    for force in (False, True):
        resp = requests.request(method, f"{STORAGE_URL}/objects/{path}",
                                headers={"X-Storage-Key": _init_storage(force), **(headers or {})}, **kw)
        if resp.status_code != 404 or force:
            return resp
    return resp


def _mime(fname: str) -> str:
    return MIME.get(fname.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def _save(fname: str, data: bytes) -> None:
    (UPLOAD_DIR / fname).write_bytes(data)
    if _cloud_enabled():
        try:
            _request("PUT", f"{APP_PREFIX}/{fname}", headers={"Content-Type": _mime(fname)},
                     data=data, timeout=120).raise_for_status()
        except Exception:
            logger.exception("Object storage mirror failed for %s (local copy kept)", fname)


def _load(fname: str):
    """Return image bytes from local disk, else object storage. None if missing."""
    local = UPLOAD_DIR / fname
    if local.is_file():
        return local.read_bytes()
    if not _cloud_enabled():
        return None
    try:
        resp = _request("GET", f"{APP_PREFIX}/{fname}", timeout=60)
    except Exception:
        logger.exception("Object storage read failed for %s", fname)
        return None
    if resp.status_code != 200:
        return None
    try:
        local.write_bytes(resp.content)
    except Exception:
        pass
    return resp.content


def upload_filename_from_url(url: str):
    """'/api/uploads/x.png' or 'https://any-host/api/uploads/x.png' → 'x.png'."""
    m = _UPLOAD_RE.search(url or "")
    return os.path.basename(m.group(1)) if m else None


async def load_upload_as_data_uri(url: str):
    """Turn one of our upload URLs into a data: URI so WhatsApp sends it without
    fetching the public URL. None if the URL isn't ours or the file is missing."""
    import base64
    fname = upload_filename_from_url(url)
    if not fname:
        return None
    data = await asyncio.to_thread(_load, fname)
    if not data:
        logger.warning("Upload %s not found locally nor in storage", fname)
        return None
    return f"data:{_mime(fname)};base64,{base64.b64encode(data).decode()}"


@router.post("")
async def upload_image(request: Request, file: UploadFile = File(...), _=Depends(require_admin)):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Extensão .{ext} não permitida. Use: {', '.join(sorted(ALLOWED_EXT))}")
    data = await file.read()
    if len(data) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, f"Imagem tem {len(data)/1024/1024:.1f}MB — o limite é {MAX_SIZE_MB}MB. Reduza o tamanho e tente de novo.")
    if len(data) == 0:
        raise HTTPException(400, "Arquivo vazio")

    fname = f"{uuid.uuid4().hex}.{ext}"
    try:
        await asyncio.to_thread(_save, fname, data)
    except Exception:
        logger.exception("Upload save failed")
        raise HTTPException(500, "Falha ao salvar a imagem. Tente novamente.")

    base = request.headers.get("x-forwarded-proto", "https") + "://" + request.headers.get("host", "localhost")
    return {
        "url": f"{base}/api/uploads/{fname}",
        "path": f"/api/uploads/{fname}",
        "filename": fname,
        "size": len(data),
    }


@router.get("/{filename}")
async def get_upload(filename: str):
    safe = os.path.basename(filename)
    data = await asyncio.to_thread(_load, safe)
    if not data:
        raise HTTPException(404, "Arquivo não encontrado")
    return Response(content=data, media_type=_mime(safe))
