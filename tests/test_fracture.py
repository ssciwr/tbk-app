from __future__ import annotations

import io
from pathlib import Path

import pytest
from httpx import AsyncClient


async def _create_case_pending_fracture(
    client: AsyncClient, auth_headers: dict[str, str], image_bytes: bytes
) -> int:
    created = await client.post(
        "/api/cases",
        headers=auth_headers,
        data={
            "child_name": "Mia",
            "animal_name": "Fox",
            "qr_content": "1",
            "broken_bone": "false",
        },
    )
    assert created.status_code == 200
    case_id = int(created.json()["case_id"])

    uploaded = await client.post(
        f"/api/cases/{case_id}/image",
        headers=auth_headers,
        files={"file": ("case.png", io.BytesIO(image_bytes), "image/png")},
    )
    assert uploaded.status_code == 200

    dispatched = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert dispatched.status_code == 200
    requested_images = int(dispatched.headers["X-Requested-Images"])
    for _ in range(requested_images):
        submitted = await client.post(
            f"/api/worker/jobs/{case_id}/results",
            headers=auth_headers,
            files={"result": ("result.png", io.BytesIO(image_bytes), "image/png")},
        )
        assert submitted.status_code == 200

    confirmed = await client.post(
        f"/api/review/{case_id}/decision",
        headers=auth_headers,
        json={"action": "confirm", "choice_index": 0},
    )
    assert confirmed.status_code == 200
    return case_id


@pytest.mark.anyio
async def test_fracture_preview_applies_effect(
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
    assert response.headers["content-type"].startswith("image/png")
    assert response.content.startswith(b"\x89PNG")
    assert response.content != png_bytes


@pytest.mark.anyio
async def test_fracture_preview_scale_and_noise_change_result(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
) -> None:
    low = await client.post(
        "/api/fracture/preview",
        headers=auth_headers,
        files={
            "image": ("input.png", io.BytesIO(png_bytes), "image/png"),
            "overlay": ("overlay.png", io.BytesIO(png_bytes), "image/png"),
        },
        data={"x": "5", "y": "5", "scale": "0.6", "noise": "0"},
    )
    assert low.status_code == 200

    high = await client.post(
        "/api/fracture/preview",
        headers=auth_headers,
        files={
            "image": ("input.png", io.BytesIO(png_bytes), "image/png"),
            "overlay": ("overlay.png", io.BytesIO(png_bytes), "image/png"),
        },
        data={"x": "5", "y": "5", "scale": "1.8", "noise": "35"},
    )
    assert high.status_code == 200

    assert low.content != high.content


@pytest.mark.anyio
async def test_fracture_apply_noop(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/fracture/cases/12/results/0", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json() == {"status": "noop_applied"}


@pytest.mark.anyio
async def test_fracture_pending_and_finalize(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
    settings,
) -> None:
    case_id = await _create_case_pending_fracture(client, auth_headers, png_bytes)

    pending = await client.get("/api/fracture/pending", headers=auth_headers)
    assert pending.status_code == 200
    pending_cases = pending.json()["cases"]
    assert pending_cases and pending_cases[0]["case_id"] == case_id

    selected_url = pending_cases[0]["selected_url"]
    selected = await client.get(selected_url, headers=auth_headers)
    assert selected.status_code == 200
    assert selected.headers["content-type"].startswith("image/png")
    assert selected.content.startswith(b"\x89PNG")

    finalized = await client.post(
        f"/api/fracture/{case_id}/decision",
        headers=auth_headers,
        json={"action": "apply_bone_breaking"},
    )
    assert finalized.status_code == 200
    assert finalized.json() == {"status": "submitted"}

    pending_after = await client.get("/api/fracture/pending", headers=auth_headers)
    assert pending_after.status_code == 200
    assert pending_after.json()["cases"] == []

    carousel = await client.get("/api/carousel", headers=auth_headers)
    assert carousel.status_code == 200
    assert len(carousel.json()["items"]) == 1

    storage_root = Path(settings.LOCAL_STORAGE_ROOT)
    assert (storage_root / "1" / "Fox_1_original.png").exists()
    assert (storage_root / "1" / "Fox_1_xray.png").exists()
    assert (storage_root / "1" / "Fox_1_combined.png").exists()
