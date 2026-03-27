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


def combine_images_side_by_side(left_bytes: bytes, right_bytes: bytes) -> bytes:
    try:
        left_image = Image.open(BytesIO(left_bytes)).convert("RGBA")
        right_image = Image.open(BytesIO(right_bytes)).convert("RGBA")
    except UnidentifiedImageError as exc:
        raise ValueError("Cannot combine invalid image data") from exc

    combined_width = left_image.width + right_image.width
    combined_height = max(left_image.height, right_image.height)
    combined = Image.new("RGBA", (combined_width, combined_height))
    combined.paste(left_image, (0, 0))
    combined.paste(right_image, (left_image.width, 0))

    output = BytesIO()
    combined.save(output, format="PNG")
    return output.getvalue()
