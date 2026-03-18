from __future__ import annotations

import io

import pytest
from httpx import AsyncClient


async def _upload_case(
    client: AsyncClient, auth_headers: dict[str, str], image_bytes: bytes
) -> int:
    created = await client.post(
        "/api/cases",
        headers=auth_headers,
        data={
            "child_name": "Ada",
            "animal_name": "Teddy",
            "qr_content": "1",
            "broken_bone": "false",
        },
    )
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["status"] == "metadata_entered"
    case_id = int(created_payload["case_id"])

    response = await client.post(
        f"/api/cases/{case_id}/image",
        headers=auth_headers,
        files={"file": ("case.png", io.BytesIO(image_bytes), "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    return case_id


@pytest.mark.anyio
async def test_case_metadata_pending_image_and_discard(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/cases",
        headers=auth_headers,
        data={
            "child_name": "Ada",
            "animal_name": "Teddy",
            "qr_content": "1",
        },
    )
    assert created.status_code == 200
    case_id = int(created.json()["case_id"])

    pending = await client.get("/api/cases/pending-image", headers=auth_headers)
    assert pending.status_code == 200
    pending_cases = pending.json()["cases"]
    assert len(pending_cases) == 1
    assert pending_cases[0]["case_id"] == case_id
    assert pending_cases[0]["status"] == "metadata_entered"

    discarded = await client.delete(
        f"/api/cases/{case_id}/pending-image",
        headers=auth_headers,
    )
    assert discarded.status_code == 200
    assert discarded.json() == {"status": "discarded"}

    pending_after = await client.get("/api/cases/pending-image", headers=auth_headers)
    assert pending_after.status_code == 200
    assert pending_after.json()["cases"] == []


@pytest.mark.anyio
async def test_case_upload_and_queue_insertion(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
    settings,
) -> None:
    case_id = await _upload_case(client, auth_headers, png_bytes)
    assert case_id > 0

    pending = await client.get("/api/review/pending", headers=auth_headers)
    assert pending.status_code == 200
    pending_cases = pending.json()["cases"]
    assert len(pending_cases) == 1
    assert pending_cases[0]["case_id"] == case_id
    assert pending_cases[0]["received_results"] == 0
    assert pending_cases[0]["ready_for_review"] is False
    assert pending_cases[0]["result_urls"] == []

    next_job = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert next_job.status_code == 200
    assert next_job.headers["content-type"].startswith("image/png")
    assert int(next_job.headers["X-Case-Id"]) == case_id
    assert next_job.headers["X-Child-Name"] == "Ada"
    assert next_job.headers["X-Workflow"] == settings.GENERATION_MODEL
    assert "X-Last-Name" not in next_job.headers


@pytest.mark.anyio
async def test_worker_next_job_and_204_behavior(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
) -> None:
    await _upload_case(client, auth_headers, png_bytes)

    # RESULTS_PER_IMAGE is 3 in test settings, so we expect 3 dispatches then empty.
    for _ in range(3):
        response = await client.get("/api/worker/jobs/next", headers=auth_headers)
        assert response.status_code == 200

    empty = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert empty.status_code == 204


@pytest.mark.anyio
async def test_worker_result_submission_until_review_ready(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
) -> None:
    case_id = await _upload_case(client, auth_headers, png_bytes)
    # Dispatch at least once to move state out of queued.
    assert (
        await client.get("/api/worker/jobs/next", headers=auth_headers)
    ).status_code == 200

    for index in range(3):
        result = await client.post(
            f"/api/worker/jobs/{case_id}/results",
            headers=auth_headers,
            files={
                "result": (f"result-{index}.png", io.BytesIO(png_bytes), "image/png")
            },
        )
        assert result.status_code == 200
        payload = result.json()
        assert payload["status"] == "accepted"
        assert payload["received_results"] == index + 1
        assert payload["expected_results"] == 3

    assert payload["ready_for_review"] is True

    pending = await client.get("/api/review/pending", headers=auth_headers)
    assert pending.status_code == 200
    cases = pending.json()["cases"]
    assert len(cases) == 1
    assert cases[0]["case_id"] == case_id
