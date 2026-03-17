from __future__ import annotations

import io

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_fracture_preview_noop(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
) -> None:
    response = await client.post(
        "/api/fracture/preview",
        headers=auth_headers,
        files={
            "image": ("input.png", io.BytesIO(png_bytes), "image/png"),
            "overlay": ("overlay.png", io.BytesIO(png_bytes), "image/png"),
        },
        data={"x": "5", "y": "5", "scale": "1.2", "noise": "3"},
    )
    assert response.status_code == 200
    assert response.content == png_bytes


@pytest.mark.anyio
async def test_fracture_apply_noop(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/fracture/cases/12/results/0", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json() == {"status": "noop_applied"}
