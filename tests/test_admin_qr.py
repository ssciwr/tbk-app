import asyncio
import time
from typing import BinaryIO, Literal

import pytest
from httpx import AsyncClient

from app.qr import QRJob, QRJobManager
from app.storage import StorageProvider


class SlowQRStorage(StorageProvider):
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.created_refs = 0

    def qr_pdf_backend_label(self) -> str:
        return "slow test storage"

    def create_storage_for_user(self) -> str:
        time.sleep(self.delay_seconds)
        self.created_refs += 1
        return f"https://storage.example.test/case-{self.created_refs}"

    def next_sequence_for_user(self, _user_ref: int | str) -> int:
        return 1

    def upload_file(
        self,
        _user_ref: int | str,
        _file_type: Literal["normal", "xray", "combined"],
        _file_obj: BinaryIO,
        _filename: str,
    ) -> None:
        return None


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


@pytest.mark.anyio
async def test_qr_job_generation_does_not_block_event_loop() -> None:
    manager = QRJobManager(SlowQRStorage(delay_seconds=0.2))
    try:
        job = manager.create_job(2)

        started = time.perf_counter()
        await asyncio.sleep(0.01)
        elapsed = time.perf_counter() - started

        assert elapsed < 0.1

        for _ in range(50):
            current = manager.get_job(job.job_id)
            if current is not None and current.status == "done":
                break
            await asyncio.sleep(0.02)

        current = manager.get_job(job.job_id)
        assert current is not None
        assert current.status == "done"
        assert current.progress == 100
        assert current.pdf_bytes is not None
    finally:
        manager.close()
