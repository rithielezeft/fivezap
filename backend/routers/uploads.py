"""Uploads router — accepts images and stores them in Emergent object storage."""
import asyncio
import logging
import os
import uuid

import requests
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import Response

from services.auth import require_admin

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
logger = logging.getLogger(__name__)

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
APP_PREFIX = "whatsflow/uploads"

ALLOWED_EXT = {"jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp"}
MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
        "webp": "image/webp", "heic": "image/heic", "heif": "image/heif", "bmp": "image/bmp"}
MAX_SIZE_MB = 15

_storage_key = None


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


def _put(path: str, data: bytes, content_type: str):
    resp = _request("PUT", path, headers={"Content-Type": content_type}, data=data, timeout=120)
    resp.raise_for_status()
    return resp.json()


def _get(path: str):
    return _request("GET", path, timeout=60)


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
        await asyncio.to_thread(_put, f"{APP_PREFIX}/{fname}", data, MIME.get(ext, "application/octet-stream"))
    except Exception:
        logger.exception("Object storage upload failed")
        raise HTTPException(502, "Falha ao salvar a imagem. Tente novamente.")

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
    resp = await asyncio.to_thread(_get, f"{APP_PREFIX}/{safe}")
    if resp.status_code != 200:
        raise HTTPException(404, "Arquivo não encontrado")
    ext = safe.rsplit(".", 1)[-1].lower()
    return Response(content=resp.content, media_type=MIME.get(ext, resp.headers.get("Content-Type", "application/octet-stream")))
