from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..auth import require_auth
from ..state import Services, get_services
from ..utils import apply_no_cache_headers

router = APIRouter(prefix="/review", tags=["review"])


class ReviewDecisionRequest(BaseModel):
    action: Literal["confirm", "retry", "cancel"]
    choice_index: int | None = None


@router.get("/pending")
async def review_pending(
    request: Request,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, list[dict]]:
    payload: list[dict] = []
    for case in services.queue.pending_review():
        payload.append(
            {
                "case_id": case.case_id,
                "status": case.state.value,
                "received_results": len(case.results),
                "ready_for_review": case.state.value == "awaiting_review",
                "metadata": {
                    "child_name": case.metadata.child_name,
                    "animal_name": case.metadata.animal_name,
                    "broken_bone": case.broken_bone,
                },
                "original_url": str(
                    request.url_for("review_original", case_id=case.case_id)
                ),
                "result_urls": [
                    str(
                        request.url_for(
                            "review_result", case_id=case.case_id, index=index
                        )
                    )
                    for index in range(len(case.results))
                ],
                "results_per_image": case.expected_results,
            }
        )

    return {"cases": payload}


@router.get("/{case_id}/original", name="review_original")
async def review_original(
    case_id: int,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    try:
        image = services.queue.get_review_original(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    response = Response(content=image, media_type="image/png")
    apply_no_cache_headers(response)
    return response


@router.get("/{case_id}/results/{index}", name="review_result")
async def review_result(
    case_id: int,
    index: int,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    try:
        image = services.queue.get_review_result(case_id, index)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IndexError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = Response(content=image, media_type="image/png")
    apply_no_cache_headers(response)
    return response


@router.post("/{case_id}/decision")
async def review_decision(
    case_id: int,
    payload: ReviewDecisionRequest,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, str]:
    try:
        if payload.action == "confirm":
            if payload.choice_index is None:
                raise HTTPException(
                    status_code=400, detail="choice_index is required for confirm"
                )
            services.queue.confirm_case(case_id, payload.choice_index, services.storage)
        elif payload.action == "retry":
            services.queue.retry_case(case_id)
        else:
            services.queue.cancel_case(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IndexError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success"}
