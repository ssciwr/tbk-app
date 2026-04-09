import pytest
from httpx import AsyncClient

from app.qr import QRJob


@pytest.mark.anyio
async def test_get_qr_job_includes_error_details(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    services = client._transport.app.state.services
    services.qr_jobs._jobs["job-1"] = QRJob(
        job_id="job-1",
        status="failed",
        progress=80,
        error="Seafile request failed (503): upstream unavailable",
    )

    response = await client.get("/api/admin/qr-jobs/job-1", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {
        "status": "failed",
        "progress": 80,
        "error": "Seafile request failed (503): upstream unavailable",
    }
