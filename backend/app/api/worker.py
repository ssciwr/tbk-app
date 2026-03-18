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

from ..auth import require_auth
from ..state import Services, get_services
from ..utils import apply_no_cache_headers, ensure_png

router = APIRouter(prefix="/worker", tags=["worker"])


@router.get("/jobs/next")
async def worker_next_job(
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    case = services.queue.get_next_job()
    if case is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    response = Response(content=case.original_bytes, media_type="image/png")
    response.headers["X-Case-Id"] = str(case.case_id)
    response.headers["X-Child-Name"] = case.metadata.child_name
    response.headers["X-Animal-Name"] = case.metadata.animal_name
    apply_no_cache_headers(response)
    return response


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
