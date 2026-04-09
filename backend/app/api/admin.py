from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..auth import require_auth
from ..state import Services, get_services

router = APIRouter(prefix="/admin", tags=["admin"])


class QRJobCreateRequest(BaseModel):
    count: int = Field(ge=1, le=1000)


@router.post("/qr-jobs", status_code=202)
async def create_qr_job(
    payload: QRJobCreateRequest,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, str]:
    job = services.qr_jobs.create_job(payload.count)
    return {"job_id": job.job_id, "status": job.status}


@router.get("/qr-jobs/{job_id}")
async def get_qr_job(
    job_id: str,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, int | str | None]:
    job = services.qr_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="QR job not found")
    return {"status": job.status, "progress": job.progress, "error": job.error}


@router.get("/qr-jobs/{job_id}/pdf")
async def download_qr_pdf(
    job_id: str,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    job = services.qr_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="QR job not found")
    if job.status != "done" or job.pdf_bytes is None:
        raise HTTPException(status_code=409, detail="PDF not ready")

    return Response(
        content=job.pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="qr-{job_id}.pdf"'},
    )
