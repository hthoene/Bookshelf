"""Cover thumbnails: any image Pillow can read is normalized to a small JPEG."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

COVER_MAX_SIZE = (600, 900)


def save_cover(data: bytes, target: Path) -> bool:
    """Write a JPEG thumbnail of ``data`` to ``target``. Returns False for unreadable images."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.draft("RGB", COVER_MAX_SIZE)  # fast JPEG downscaling while decoding
            image.thumbnail(COVER_MAX_SIZE)
            image = image.convert("RGB")
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, "JPEG", quality=85, optimize=True, progressive=True)
        return True
    except (OSError, ValueError, Image.DecompressionBombError):
        log.info("Could not process cover image for %s", target.name, exc_info=True)
        return False
