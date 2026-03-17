from __future__ import annotations

from io import BytesIO

from fastapi import Response
from PIL import Image, UnidentifiedImageError


def ensure_png(image_bytes: bytes) -> bytes:
    try:
        image = Image.open(BytesIO(image_bytes))
    except UnidentifiedImageError as exc:
        raise ValueError("Uploaded file is not a valid image") from exc

    output = BytesIO()
    image.convert("RGBA").save(output, format="PNG")
    return output.getvalue()


def apply_no_cache_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
