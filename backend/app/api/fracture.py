from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..auth import require_auth
from ..fracture import fracture_preview_passthrough
from ..state import Services, get_services
from ..utils import apply_no_cache_headers

router = APIRouter(prefix="/fracture", tags=["fracture"])


class FractureDecisionRequest(BaseModel):
    action: Literal["proceed_without_breaking", "apply_bone_breaking"]


@router.get("/pending")
async def fracture_pending(
    request: Request,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, list[dict]]:
    payload: list[dict] = []
    for case in services.queue.pending_fracture():
        payload.append(
            {
                "case_id": case.case_id,
                "metadata": {
                    "child_name": case.metadata.child_name,
                    "animal_name": case.metadata.animal_name,
                },
                "selected_url": str(
                    request.url_for("fracture_selected_result", case_id=case.case_id)
                ),
            }
        )
    return {"cases": payload}


@router.post("/preview")
async def fracture_preview(
    image: Annotated[UploadFile, File(...)],
    overlay: Annotated[UploadFile | None, File()] = None,
    x: Annotated[int | None, Form()] = None,
    y: Annotated[int | None, Form()] = None,
    scale: Annotated[float | None, Form()] = None,
    noise: Annotated[int | None, Form()] = None,
    _: Annotated[dict, Depends(require_auth)] = None,
) -> Response:
    image_bytes = await image.read()
    overlay_bytes = await overlay.read() if overlay is not None else None
    result = fracture_preview_passthrough(
        image_bytes,
        overlay_bytes=overlay_bytes,
        x=x,
        y=y,
        scale=scale,
        noise=noise,
    )
    response = Response(content=result, media_type="image/png")
    apply_no_cache_headers(response)
    return response


@router.get("/{case_id}/selected", name="fracture_selected_result")
async def fracture_selected_result(
    case_id: int,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    try:
        image = services.queue.get_selected_result(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = Response(content=image, media_type="image/png")
    apply_no_cache_headers(response)
    return response


@router.post("/{case_id}/decision")
async def fracture_decision(
    case_id: int,
    payload: FractureDecisionRequest,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, str]:
    try:
        selected = services.queue.get_selected_result(case_id)
        output = (
            fracture_preview_passthrough(selected)
            if payload.action == "apply_bone_breaking"
            else selected
        )
        services.queue.finalize_case(
            case_id,
            output_xray=output,
            storage=services.storage,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "submitted"}


@router.post("/{case_id}/submit")
async def fracture_submit(
    case_id: int,
    image: Annotated[UploadFile, File(...)],
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, str]:
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Submitted fracture image is empty")

    try:
        services.queue.finalize_case(
            case_id,
            output_xray=image_bytes,
            storage=services.storage,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "submitted"}


@router.post("/cases/{case_id}/results/{index}")
async def fracture_apply_noop(
    case_id: int,
    index: int,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, str]:
    _ = (case_id, index, services)
    return {"status": "noop_applied"}
