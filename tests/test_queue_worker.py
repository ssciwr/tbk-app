from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io

import pytest
from httpx import AsyncClient


async def _upload_case(
    client: AsyncClient,
    auth_headers: dict[str, str],
    image_bytes: bytes,
    *,
    animal_type: str | None = None,
    child_name: str = "Ada",
    animal_name: str = "Teddy",
) -> int:
    payload = {
        "child_name": child_name,
        "animal_name": animal_name,
        "qr_content": "1",
        "broken_bone": "false",
    }
    if animal_type is not None:
        payload["animal_type"] = animal_type

    created = await client.post(
        "/api/cases",
        headers=auth_headers,
        data=payload,
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
async def test_case_animal_type_is_exposed_in_pending_and_worker_headers(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
) -> None:
    created = await client.post(
        "/api/cases",
        headers=auth_headers,
        data={
            "child_name": "Ada",
            "animal_name": "Teddy",
            "animal_type": "fox",
            "qr_content": "1",
        },
    )
    assert created.status_code == 200
    case_id = int(created.json()["case_id"])

    pending = await client.get("/api/cases/pending-image", headers=auth_headers)
    assert pending.status_code == 200
    pending_cases = pending.json()["cases"]
    assert pending_cases and pending_cases[0]["case_id"] == case_id
    assert pending_cases[0]["metadata"]["animal_type"] == "fox"

    upload = await client.post(
        f"/api/cases/{case_id}/image",
        headers=auth_headers,
        files={"file": ("case.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert upload.status_code == 200

    next_job = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert next_job.status_code == 200
    assert int(next_job.headers["X-Case-Id"]) == case_id
    assert next_job.headers["X-Animal-Type"] == "fox"


@pytest.mark.anyio
async def test_case_can_be_fast_tracked_with_qr_only_metadata(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
) -> None:
    created = await client.post(
        "/api/cases",
        headers=auth_headers,
        data={
            "qr_content": "qr-only-1",
        },
    )
    assert created.status_code == 200
    case_id = int(created.json()["case_id"])

    pending = await client.get("/api/cases/pending-image", headers=auth_headers)
    assert pending.status_code == 200
    pending_cases = pending.json()["cases"]
    assert pending_cases and pending_cases[0]["case_id"] == case_id
    assert pending_cases[0]["metadata"]["child_name"] == ""
    assert pending_cases[0]["metadata"]["animal_name"] == ""
    assert pending_cases[0]["metadata"]["qr_content"] == "qr-only-1"

    upload = await client.post(
        f"/api/cases/{case_id}/image",
        headers=auth_headers,
        files={"file": ("case.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert upload.status_code == 200

    next_job = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert next_job.status_code == 200
    assert int(next_job.headers["X-Case-Id"]) == case_id
    assert "X-Child-Name" not in next_job.headers
    assert "X-Animal-Name" not in next_job.headers


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
    assert int(next_job.headers["X-Requested-Images"]) == settings.RESULTS_PER_IMAGE
    assert "X-Last-Name" not in next_job.headers


@pytest.mark.anyio
async def test_worker_next_job_and_204_behavior(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
    settings,
) -> None:
    await _upload_case(client, auth_headers, png_bytes)

    response = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert response.status_code == 200
    assert int(response.headers["X-Requested-Images"]) == settings.RESULTS_PER_IMAGE

    empty = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert empty.status_code == 204


@pytest.mark.anyio
async def test_worker_status_reports_runner_heartbeat(
    app,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    initial_status = await client.get("/api/worker/status", headers=auth_headers)
    assert initial_status.status_code == 200
    initial_payload = initial_status.json()
    assert initial_payload["runner_connected"] is False
    assert initial_payload["last_poll_at"] is None
    assert initial_payload["stale_after_seconds"] == 30

    heartbeat = await client.post("/api/worker/heartbeat", headers=auth_headers)
    assert heartbeat.status_code == 200
    assert heartbeat.json() == {"status": "ok"}

    after_poll_status = await client.get("/api/worker/status", headers=auth_headers)
    assert after_poll_status.status_code == 200
    after_poll_payload = after_poll_status.json()
    assert after_poll_payload["runner_connected"] is True
    assert after_poll_payload["last_poll_at"] is not None
    assert after_poll_payload["stale_after_seconds"] == 30

    app.state.services.runner_heartbeat.record_poll(
        datetime.now(tz=UTC) - timedelta(seconds=31)
    )
    stale_status = await client.get("/api/worker/status", headers=auth_headers)
    assert stale_status.status_code == 200
    stale_payload = stale_status.json()
    assert stale_payload["runner_connected"] is False
    assert stale_payload["last_poll_at"] is not None


@pytest.mark.anyio
async def test_worker_result_submission_until_review_ready(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
) -> None:
    case_id = await _upload_case(client, auth_headers, png_bytes)
    # Dispatch at least once to move state out of queued.
    dispatched = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert dispatched.status_code == 200
    requested_images = int(dispatched.headers["X-Requested-Images"])

    for index in range(requested_images):
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
        assert payload["expected_results"] == requested_images

    assert payload["ready_for_review"] is True

    pending = await client.get("/api/review/pending", headers=auth_headers)
    assert pending.status_code == 200
    cases = pending.json()["cases"]
    assert len(cases) == 1
    assert cases[0]["case_id"] == case_id


@pytest.mark.anyio
async def test_worker_failed_job_requeues_collecting_case(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
) -> None:
    case_id = await _upload_case(client, auth_headers, png_bytes)
    dispatched = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert dispatched.status_code == 200

    first_result = await client.post(
        f"/api/worker/jobs/{case_id}/results",
        headers=auth_headers,
        files={"result": ("result.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert first_result.status_code == 200
    assert first_result.json()["received_results"] == 1

    failed = await client.post(
        f"/api/worker/jobs/{case_id}/failed",
        headers=auth_headers,
    )
    assert failed.status_code == 200
    assert failed.json() == {"status": "requeued", "case_id": case_id}

    pending = await client.get("/api/review/pending", headers=auth_headers)
    assert pending.status_code == 200
    pending_cases = pending.json()["cases"]
    assert pending_cases and pending_cases[0]["case_id"] == case_id
    assert pending_cases[0]["received_results"] == 0
    assert pending_cases[0]["ready_for_review"] is False

    next_job = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert next_job.status_code == 200
    assert int(next_job.headers["X-Case-Id"]) == case_id


@pytest.mark.anyio
async def test_review_retry_requeues_case(
    client: AsyncClient,
    auth_headers: dict[str, str],
    png_bytes: bytes,
) -> None:
    case_id = await _upload_case(client, auth_headers, png_bytes)
    dispatched = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert dispatched.status_code == 200
    requested_images = int(dispatched.headers["X-Requested-Images"])

    for _ in range(requested_images):
        submitted = await client.post(
            f"/api/worker/jobs/{case_id}/results",
            headers=auth_headers,
            files={"result": ("result.png", io.BytesIO(png_bytes), "image/png")},
        )
        assert submitted.status_code == 200

    pending = await client.get("/api/review/pending", headers=auth_headers)
    assert pending.status_code == 200
    pending_cases = pending.json()["cases"]
    assert pending_cases and pending_cases[0]["case_id"] == case_id
    assert "used_model" not in pending_cases[0]
    assert "available_models" not in pending_cases[0]

    retry = await client.post(
        f"/api/review/{case_id}/decision",
        headers=auth_headers,
        json={"action": "retry", "choice_index": None},
    )
    assert retry.status_code == 200

    next_job = await client.get("/api/worker/jobs/next", headers=auth_headers)
    assert next_job.status_code == 200
    assert int(next_job.headers["X-Case-Id"]) == case_id
