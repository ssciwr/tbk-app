from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


def _clamp(value: int, lower: int = 0, upper: int = 255) -> int:
    return max(lower, min(upper, value))


def _load_rgba(image_bytes: bytes) -> Image.Image:
    with Image.open(BytesIO(image_bytes)) as image:
        return image.convert("RGBA")


def _default_fracture_mask(
    size: tuple[int, int],
    *,
    x: int | None,
    y: int | None,
    scale: float,
) -> Image.Image:
    width, height = size
    center_x = x if x is not None and x > 0 else width // 2
    center_y = y if y is not None and y > 0 else height // 2
    center_x = max(0, min(width - 1, center_x))
    center_y = max(0, min(height - 1, center_y))

    span = int(min(width, height) * 0.42 * max(0.55, min(scale, 2.2)))
    span = max(8, span)
    crack_width = max(2, int(round(2 + scale * 5)))

    mask = Image.new("L", size, color=0)
    draw = ImageDraw.Draw(mask)

    points: list[tuple[int, int]] = []
    for idx in range(7):
        px = center_x - span + int((2 * span) * idx / 6)
        direction = -1 if idx % 2 == 0 else 1
        py = center_y + int(direction * span * 0.16)
        points.append((px, py))
    draw.line(points, fill=255, width=crack_width)

    branch_start = points[3]
    draw.line(
        [branch_start, (branch_start[0] + span // 2, branch_start[1] - span // 3)],
        fill=220,
        width=max(1, crack_width - 1),
    )
    draw.line(
        [branch_start, (branch_start[0] - span // 3, branch_start[1] + span // 3)],
        fill=220,
        width=max(1, crack_width - 1),
    )

    return mask


def _overlay_mask(
    overlay_bytes: bytes | None,
    *,
    size: tuple[int, int],
) -> Image.Image | None:
    if not overlay_bytes:
        return None

    with Image.open(BytesIO(overlay_bytes)) as overlay:
        alpha = overlay.convert("RGBA").resize(size).split()[3]
    if alpha.getbbox() is None:
        return None
    return alpha


def _prepare_mask(
    mask: Image.Image,
    *,
    scale: float,
) -> Image.Image:
    if scale > 1.0:
        passes = min(4, max(0, int(round((scale - 1.0) * 4))))
        for _ in range(passes):
            mask = mask.filter(ImageFilter.MaxFilter(3))
    elif scale < 1.0:
        passes = min(2, max(0, int(round((1.0 - scale) * 3))))
        for _ in range(passes):
            mask = mask.filter(ImageFilter.MinFilter(3))

    blur_radius = max(0.8, scale * 1.1)
    return mask.filter(ImageFilter.GaussianBlur(blur_radius))


def _deterministic_texture(
    size: tuple[int, int],
    *,
    noise: int,
) -> Image.Image:
    width, height = size
    texture = Image.new("L", size, color=128)
    draw = ImageDraw.Draw(texture)

    spacing = max(3, 24 - noise)
    strength = _clamp(14 + noise * 3, 0, 115)

    for offset in range(-height, width + height, spacing):
        draw.line(
            [(offset, 0), (offset - height, height)], fill=128 + strength, width=1
        )
        draw.line(
            [(offset - spacing // 2, 0), (offset - spacing // 2 + height, height)],
            fill=128 - strength,
            width=1,
        )

    return Image.merge("RGB", (texture, texture, texture))


def fracture_preview_passthrough(
    image_bytes: bytes,
    *,
    overlay_bytes: bytes | None = None,
    x: int | None = None,
    y: int | None = None,
    scale: float | None = None,
    noise: int | None = None,
) -> bytes:
    """Apply a simple deterministic fracture effect for preview/finalize paths."""
    scale_value = 1.0 if scale is None else max(0.5, min(scale, 2.0))
    noise_value = 10 if noise is None else max(0, min(noise, 40))

    base_rgba = _load_rgba(image_bytes)
    base_rgb = base_rgba.convert("RGB")
    size = base_rgb.size

    mask = _overlay_mask(overlay_bytes, size=size)
    if mask is None:
        mask = _default_fracture_mask(size, x=x, y=y, scale=scale_value)
    mask = _prepare_mask(mask, scale=scale_value)

    offset_main = max(1, int(round(2 + scale_value * 6)))
    offset_minor = max(1, int(round(1 + scale_value * 3)))

    shifted_a = ImageChops.offset(base_rgb, offset_main, 0)
    shifted_b = ImageChops.offset(base_rgb, -offset_minor, 0)
    grayscale = ImageOps.grayscale(base_rgb).convert("RGB")

    fractured = Image.blend(shifted_a, shifted_b, 0.45)
    fractured = Image.blend(fractured, grayscale, min(0.82, 0.33 + noise_value / 90.0))

    texture = _deterministic_texture(size, noise=noise_value)
    fractured = ImageChops.add(fractured, texture, scale=1.0, offset=-128)

    core_mask = mask.point(
        lambda value: _clamp(int(value * min(1.0, 0.5 + noise_value / 70.0)))
    )
    dark_layer = Image.new("RGB", size, color=(18, 18, 22))
    fractured = Image.composite(dark_layer, fractured, core_mask)

    result = Image.composite(fractured, base_rgb, mask)
    output = BytesIO()
    result.save(output, format="PNG")
    return output.getvalue()
