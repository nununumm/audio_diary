"""Image helpers: EXIF-correct orientation and thumbnail generation.

Kept deliberately light because the server (an old phone) has limited CPU.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps

THUMB_MAX = (480, 480)
FULL_MAX = (2048, 2048)


def _encode(img: Image.Image, quality: int) -> bytes:
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def process(data: bytes) -> tuple[bytes, bytes]:
    """Return (full_jpeg, thumb_jpeg), both orientation-corrected."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))

    full = img.copy()
    full.thumbnail(FULL_MAX)
    full_bytes = _encode(full, quality=85)

    thumb = img.copy()
    thumb.thumbnail(THUMB_MAX)
    thumb_bytes = _encode(thumb, quality=80)

    return full_bytes, thumb_bytes
