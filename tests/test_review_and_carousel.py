from __future__ import annotations

import io
from pathlib import Path

import pytest
from httpx import AsyncClient


async def _create_case_ready_for_review(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
    qr_content: str = "1",
) -> int:
    created = await client.post(
        "/api/cases",
        headers=auth_headers,
        data={
            "child_name": "Max",
            "animal_name": "Bunny",
            "qr_content": qr_content,
            "broken_bone": "true",
        },
    )
    assert created.status_code == 200
    case_id = int(created.json()["case_id"])

    uploaded = await client.post(
        f"/api/cases/{case_id}/image",
        headers=auth_headers,
        files={"file": ("case.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert uploaded.status_code == 200

    # Move into collecting state.
    assert (
        await client.get("/api/worker/jobs/next", headers=auth_headers)
    ).status_code == 200

    for _ in range(3):
        submitted = await client.post(
            f"/api/worker/jobs/{case_id}/results",
            headers=auth_headers,
            files={"result": ("result.png", io.BytesIO(png_bytes), "image/png")},
        )
        assert submitted.status_code == 200

    return case_id


@pytest.mark.anyio
async def test_review_confirm_transition(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
    settings,
) -> None:
    case_id = await _create_case_ready_for_review(client, auth_headers, png_bytes)

    pending = await client.get("/api/review/pending", headers=auth_headers)
    assert pending.status_code == 200
    pending_cases = pending.json()["cases"]
    assert pending_cases and pending_cases[0]["case_id"] == case_id

    decision = await client.post(
        f"/api/review/{case_id}/decision",
        headers=auth_headers,
        json={"action": "confirm", "choice_index": 0},
    )
    assert decision.status_code == 200

    pending_fracture = await client.get("/api/fracture/pending", headers=auth_headers)
    assert pending_fracture.status_code == 200
    fracture_cases = pending_fracture.json()["cases"]
    assert fracture_cases and fracture_cases[0]["case_id"] == case_id

    carousel = await client.get("/api/carousel", headers=auth_headers)
    assert carousel.status_code == 200
    assert carousel.json()["items"] == []

    finalized = await client.post(
        f"/api/fracture/{case_id}/decision",
        headers=auth_headers,
        json={"action": "proceed_without_breaking"},
    )
    assert finalized.status_code == 200

    carousel = await client.get("/api/carousel", headers=auth_headers)
    assert carousel.status_code == 200
    items = carousel.json()["items"]
    assert len(items) == 1
    assert items[0]["case_id"] == case_id
    assert items[0]["metadata"]["child_name"] == "Max"
    assert items[0]["metadata"]["animal_name"] == "Bunny"
    assert items[0]["metadata"]["qr_content"] == "1"

    storage_root = Path(settings.LOCAL_STORAGE_ROOT)
    assert (storage_root / "1" / "normal" / f"{case_id}_original.png").exists()
    assert (storage_root / "1" / "xray" / f"{case_id}_result.png").exists()


@pytest.mark.anyio
async def test_review_early_confirm_cleans_queue_and_ignores_late_results(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
) -> None:
    created = await client.post(
        "/api/cases",
        headers=auth_headers,
        data={
            "child_name": "Nora",
            "animal_name": "Otter",
            "qr_content": "42",
            "broken_bone": "false",
        },
    )
    assert created.status_code == 200
    case_id = int(created.json()["case_id"])

    uploaded = await client.post(
        f"/api/cases/{case_id}/image",
        headers=auth_headers,
        files={"file": ("case.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert uploaded.status_code == 200

    first_job = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert first_job.status_code == 200
    assert int(first_job.headers["X-Case-Id"]) == case_id

    first_result = await client.post(
        f"/api/worker/jobs/{case_id}/results",
        headers=auth_headers,
        files={"result": ("result.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert first_result.status_code == 200
    assert first_result.json()["status"] == "accepted"

    confirmed = await client.post(
        f"/api/review/{case_id}/decision",
        headers=auth_headers,
        json={"action": "confirm", "choice_index": 0},
    )
    assert confirmed.status_code == 200

    # Remaining queued worker jobs must be removed after early confirmation.
    next_job = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert next_job.status_code == 204

    pending_fracture = await client.get("/api/fracture/pending", headers=auth_headers)
    assert pending_fracture.status_code == 200
    fracture_cases = pending_fracture.json()["cases"]
    assert fracture_cases and fracture_cases[0]["case_id"] == case_id

    # Late submissions from workers are acknowledged but ignored.
    late_result = await client.post(
        f"/api/worker/jobs/{case_id}/results",
        headers=auth_headers,
        files={"result": ("late.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert late_result.status_code == 200
    late_payload = late_result.json()
    assert late_payload["status"] == "ignored"
    assert late_payload["received_results"] == 1

    finalized = await client.post(
        f"/api/fracture/{case_id}/decision",
        headers=auth_headers,
        json={"action": "proceed_without_breaking"},
    )
    assert finalized.status_code == 200

    late_after_finalize = await client.post(
        f"/api/worker/jobs/{case_id}/results",
        headers=auth_headers,
        files={"result": ("late-final.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert late_after_finalize.status_code == 200
    assert late_after_finalize.json()["status"] == "ignored"


@pytest.mark.anyio
async def test_review_retry_and_cancel_transitions(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
) -> None:
    retry_case_id = await _create_case_ready_for_review(client, auth_headers, png_bytes)
    retry = await client.post(
        f"/api/review/{retry_case_id}/decision",
        headers=auth_headers,
        json={"action": "retry", "choice_index": None},
    )
    assert retry.status_code == 200

    # After retry, case should be dispatchable again.
    job = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert job.status_code == 200
    assert int(job.headers["X-Case-Id"]) == retry_case_id

    cancel_case_id = await _create_case_ready_for_review(
        client, auth_headers, png_bytes
    )
    cancel = await client.post(
        f"/api/review/{cancel_case_id}/decision",
        headers=auth_headers,
        json={"action": "cancel", "choice_index": None},
    )
    assert cancel.status_code == 200

    pending = await client.get("/api/review/pending", headers=auth_headers)
    assert pending.status_code == 200
    pending_ids = {item["case_id"] for item in pending.json()["cases"]}
    assert cancel_case_id not in pending_ids


@pytest.mark.anyio
async def test_carousel_max_size_eviction(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
) -> None:
    for index in range(3):
        case_id = await _create_case_ready_for_review(
            client, auth_headers, png_bytes, qr_content=str(index + 1)
        )
        confirmed = await client.post(
            f"/api/review/{case_id}/decision",
            headers=auth_headers,
            json={"action": "confirm", "choice_index": 0},
        )
        assert confirmed.status_code == 200
        fractured = await client.post(
            f"/api/fracture/{case_id}/decision",
            headers=auth_headers,
            json={"action": "proceed_without_breaking"},
        )
        assert fractured.status_code == 200

    carousel = await client.get("/api/carousel", headers=auth_headers)
    assert carousel.status_code == 200
    items = carousel.json()["items"]
    assert len(items) == 2  # CAROUSEL_SIZE in test settings
