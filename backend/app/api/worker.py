from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse

from ..auth import require_auth
from ..models import CaseState
from ..state import Services, get_services
from ..utils import apply_no_cache_headers, ensure_png

router = APIRouter(prefix="/worker", tags=["worker"])
RUNNER_HEARTBEAT_STALE_AFTER_SECONDS = 30.0


@router.get("/jobs/next")
async def worker_next_job(
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    services.runner_heartbeat.record_poll()
    case = services.queue.get_next_job()
    if case is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    response = Response(content=case.original_bytes, media_type="image/png")
    response.headers["X-Case-Id"] = str(case.case_id)
    response.headers["X-Child-Name"] = case.metadata.child_name
    response.headers["X-Animal-Name"] = case.metadata.animal_name
    if case.metadata.animal_type:
        response.headers["X-Animal-Type"] = case.metadata.animal_type
    response.headers["X-Requested-Images"] = str(case.expected_results)
    response.headers["X-Expected-Results"] = str(case.expected_results)
    apply_no_cache_headers(response)
    return response


@router.get("/status")
async def worker_status(
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    last_poll_at = services.runner_heartbeat.last_poll_at()
    payload = {
        "runner_connected": services.runner_heartbeat.is_connected(
            stale_after_seconds=RUNNER_HEARTBEAT_STALE_AFTER_SECONDS
        ),
        "last_poll_at": last_poll_at.isoformat() if last_poll_at else None,
        "stale_after_seconds": int(RUNNER_HEARTBEAT_STALE_AFTER_SECONDS),
    }
    response = JSONResponse(content=payload)
    apply_no_cache_headers(response)
    return response


@router.post("/heartbeat")
async def worker_heartbeat(
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, str]:
    services.runner_heartbeat.record_poll()
    return {"status": "ok"}


@router.post("/jobs/{case_id}/results")
async def worker_submit_result(
    case_id: int,
    result: Annotated[UploadFile, File(...)],
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, int | bool | str]:
    raw_bytes = await result.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded result image is empty")

    try:
        png_bytes = ensure_png(raw_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        received, expected, ready_for_review, ignored = services.queue.submit_result(
            case_id, png_bytes
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "ignored" if ignored else "accepted",
        "received_results": received,
        "expected_results": expected,
        "ready_for_review": ready_for_review,
    }


@router.post("/jobs/{case_id}/failed")
async def worker_report_job_failed(
    case_id: int,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, str | int]:
    case = services.queue.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    # Late failure reports are harmless no-ops once a case has moved on.
    if case.state in {
        CaseState.PENDING_FRACTURE,
        CaseState.CONFIRMED,
        CaseState.CANCELED,
        CaseState.AWAITING_REVIEW,
    }:
        return {"status": "ignored", "case_id": case_id}

    try:
        services.queue.retry_case(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "requeued", "case_id": case_id}
