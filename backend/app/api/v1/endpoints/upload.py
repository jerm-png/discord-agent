import base64
import io
import logging
import mimetypes
import os
import re
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.auth import CurrentUser, get_current_user
from app.core.config import (
    MAX_UPLOAD_BYTES,
    PDF_VISION_MAX_PAGES,
    PDF_VISION_THRESHOLD,
    POPPLER_PATH,
    UPLOAD_DIR,
)
import app.core.state as state

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Allow-list ────────────────────────────────────────────────
# Maps extensions (lowercase, no dot) to the orchestrator's
# content_type bucket. PDFs route through the same handler at upload
# time but the orchestrator branches further on page count.
_DOC_EXTS = {"txt", "csv", "json", "md", "pdf"}
_IMG_EXTS = {"jpg", "jpeg", "png", "webp", "gif"}
_IMG_MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}

# Trim filenames to a stem we can safely write to disk. The original
# filename is preserved in the metadata returned to the client.
_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    name = name.strip().replace("\\", "/").split("/")[-1]
    cleaned = _UNSAFE_NAME_RE.sub("_", name)
    return cleaned[:120] or "file"


def _ext_of(filename: str) -> str:
    _, dot, ext = filename.rpartition(".")
    return ext.lower() if dot else ""


def _classify(ext: str) -> str:
    if ext in _IMG_EXTS:
        return "image"
    if ext == "pdf":
        return "pdf"
    if ext in _DOC_EXTS:
        return "document"
    return ""


def _load_pdf_entry(filename: str, data: bytes) -> dict:
    """
    Build the attached_files entry for a PDF. Short PDFs are extracted
    as text (cheaper); long PDFs are rendered to images and sent to
    Claude as vision input. Falls back to a text-only entry with a
    truncation note when either path fails — we never reject the upload
    on extraction failure.
    """
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
    except Exception as e:
        logger.warning(f"PDF parse failed for {filename}: {e}")
        return {
            "filename": filename,
            "content_type": "document",
            "text_content": "[PDF could not be parsed.]",
        }

    if page_count > PDF_VISION_THRESHOLD:
        try:
            from pdf2image import convert_from_bytes
            kwargs = {"first_page": 1, "last_page": PDF_VISION_MAX_PAGES}
            if POPPLER_PATH:
                kwargs["poppler_path"] = POPPLER_PATH
            images = convert_from_bytes(data, **kwargs)
            pages = []
            for img in images:
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                pages.append({
                    "media_type": "image/png",
                    "base64_data": base64.b64encode(buf.getvalue()).decode(),
                })
            return {
                "filename": filename,
                "content_type": "pdf_vision",
                "pages": pages,
                "page_count": page_count,
            }
        except Exception as e:
            logger.warning(
                f"PDF vision render failed for {filename}: {e}"
            )
            # Fall through to text extraction so the upload is not lost.

    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    text = "\n\n".join(p.strip() for p in parts if p.strip())
    if not text:
        text = "[PDF contains no extractable text.]"
    return {
        "filename": filename,
        "content_type": "document",
        "text_content": text,
    }


def _load_text_entry(filename: str, data: bytes) -> dict:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    return {
        "filename": filename,
        "content_type": "document",
        "text_content": text,
    }


def _load_image_entry(filename: str, data: bytes, ext: str) -> dict:
    media_type = _IMG_MEDIA_TYPES.get(ext) or mimetypes.guess_type(filename)[0]
    if not media_type or not media_type.startswith("image/"):
        media_type = "image/png"
    return {
        "filename": filename,
        "content_type": "image",
        "media_type": media_type,
        "base64_data": base64.b64encode(data).decode(),
    }


@router.post("")
@router.post("/")
async def upload_file(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Accept a single multipart upload, persist it under
    UPLOAD_DIR/{user_id}/{uuid}_{filename}, and register the parsed
    metadata in state.uploaded_files keyed by file_id. The chat WS
    handler turns the returned file_id into an attached_files entry.
    """
    user_id = user["user_id"]
    raw_name = file.filename or "upload.bin"
    filename = _safe_filename(raw_name)
    ext = _ext_of(filename)
    kind = _classify(ext)
    if not kind:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '.{ext}'. "
                "Allowed: pdf, txt, csv, json, md, jpg, jpeg, png, webp, gif."
            ),
        )

    # Read with size check. UploadFile.read() loads into memory; for
    # 10MB this is fine and lets us hash/extract in one pass.
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large ({len(data)} bytes). "
                f"Max is {MAX_UPLOAD_BYTES} bytes."
            ),
        )

    file_id = uuid.uuid4().hex
    user_dir = os.path.join(UPLOAD_DIR, user_id)
    try:
        os.makedirs(user_dir, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to mkdir {user_dir}: {e}")
        raise HTTPException(status_code=500, detail="Storage unavailable.")
    disk_name = f"{file_id}_{filename}"
    disk_path = os.path.join(user_dir, disk_name)
    try:
        with open(disk_path, "wb") as f:
            f.write(data)
    except Exception as e:
        logger.error(f"Write failed at {disk_path}: {e}")
        raise HTTPException(status_code=500, detail="Could not save file.")

    # Build the attached_files-shaped entry. The orchestrator will
    # consume this verbatim when the chat WS forwards the file_id.
    if kind == "pdf":
        entry = _load_pdf_entry(filename, data)
    elif kind == "image":
        entry = _load_image_entry(filename, data, ext)
    else:
        entry = _load_text_entry(filename, data)

    state.uploaded_files[file_id] = {
        "user_id": user_id,
        "filename": filename,
        "disk_path": disk_path,
        "size": len(data),
        "file_type": kind,
        "ext": ext,
        "entry": entry,
    }

    return {
        "file_id": file_id,
        "filename": filename,
        "file_type": kind,
        "file_path": disk_path,
        "size": len(data),
    }
