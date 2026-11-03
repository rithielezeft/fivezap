"""Uploads router — accepts images and stores under /app/backend/uploads."""
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import FileResponse

from services.auth import require_admin

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXT = {"jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp"}
MAX_SIZE_MB = 15


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
    fpath = UPLOAD_DIR / fname
    fpath.write_bytes(data)

    # Build public URL
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
    fpath = UPLOAD_DIR / safe
    if not fpath.exists():
        raise HTTPException(404, "Arquivo não encontrado")
    return FileResponse(str(fpath))
