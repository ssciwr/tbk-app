from __future__ import annotations

import hashlib
from io import BytesIO

from fastapi import Request, Response, status
from PIL import Image, ImageChops, UnidentifiedImageError


def ensure_png(image_bytes: bytes) -> bytes:
    try:
        image = Image.open(BytesIO(image_bytes))
    except UnidentifiedImageError as exc:
        raise ValueError("Uploaded file is not a valid image") from exc

    image.load()
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        normalized = image.convert("RGBA")
    else:
        normalized = (
            image.convert("L") if _is_grayscale(image) else image.convert("RGB")
        )

    output = BytesIO()
    normalized.save(output, format="PNG", optimize=True)
    return output.getvalue()


def apply_no_cache_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


def etag_for_bytes(content: bytes) -> str:
    return f'"{hashlib.sha256(content).hexdigest()}"'


def apply_private_cache_headers(
    response: Response, *, etag: str, max_age_seconds: int = 3600
) -> None:
    response.headers["Cache-Control"] = f"private, max-age={max_age_seconds}"
    response.headers["ETag"] = etag
    response.headers["Vary"] = "Authorization"


def cached_binary_response(
    content: bytes,
    request: Request,
    *,
    media_type: str,
    max_age_seconds: int = 3600,
) -> Response:
    etag = etag_for_bytes(content)
    if request.headers.get("if-none-match") == etag:
        response = Response(status_code=status.HTTP_304_NOT_MODIFIED)
    else:
        response = Response(content=content, media_type=media_type)
    apply_private_cache_headers(response, etag=etag, max_age_seconds=max_age_seconds)
    return response


def _is_grayscale(image: Image.Image) -> bool:
    if image.mode in {"1", "L"}:
        return True
    rgb_image = image.convert("RGB")
    red, green, blue = rgb_image.split()
    return (
        ImageChops.difference(red, green).getbbox() is None
        and ImageChops.difference(red, blue).getbbox() is None
    )


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
