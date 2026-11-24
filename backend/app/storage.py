"""Upload validation (type via magic bytes + extension, size) and content-addressed storage."""
import hashlib
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException, UploadFile

from .config import get_settings

SIGNATURES = [(b"%PDF-", "application/pdf", ".pdf"),
              (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
              (b"\x89PNG\r\n\x1a\n", "image/png", ".png")]
ALLOWED_EXT = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


async def read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    chunks, total = [], 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


def validate_upload(filename: str | None, data: bytes) -> tuple[str, str, str]:
    """Returns (safe_filename, content_type, extension). Never trusts the client's Content-Type."""
    if not data:
        raise HTTPException(400, "File is empty")
    # Browsers on Windows may send backslashes even when the API runs on Linux.
    raw_name = (filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in raw_name if ch >= " " and ch not in "\x7f")[:255].strip() or "upload"
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(415, "Unsupported file type. Allowed: PDF, JPG, PNG")
    for magic, mime, canon_ext in SIGNATURES:
        if data.startswith(magic):
            if mime != ALLOWED_EXT[ext]:
                raise HTTPException(415, "File extension does not match file content")
            return name, mime, canon_ext
    raise HTTPException(415, "File content is not a valid PDF, JPG or PNG")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save(data: bytes, sha: str, ext: str) -> str:
    """Content-addressed path (user-supplied names never touch the filesystem path)."""
    root = Path(get_settings().upload_dir)
    dest = root / sha[:2] / f"{sha}{ext}"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{sha}.", suffix=".tmp", dir=dest.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.replace(tmp_name, dest)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
    return str(dest)
