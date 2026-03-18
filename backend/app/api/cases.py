from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..auth import require_auth
from ..models import CaseMetadata
from ..state import Services, get_services
from ..utils import ensure_png

router = APIRouter(tags=["cases"])


@router.post("/cases")
async def create_case(
    child_name: Annotated[str, Form(...)],
    animal_name: Annotated[str, Form(...)],
    qr_content: Annotated[str, Form(...)],
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
    broken_bone: Annotated[bool, Form()] = False,
) -> dict[str, int | str]:
    metadata = CaseMetadata(
        child_name=child_name.strip(),
        animal_name=animal_name.strip(),
    )

    case = services.queue.enqueue_case(
        owner_ref=qr_content.strip(),
        metadata=metadata,
        broken_bone=broken_bone,
    )

    return {
        "case_id": case.case_id,
        "status": "metadata_entered",
    }


@router.get("/cases/pending-image")
async def pending_image_cases(
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, list[dict]]:
    payload: list[dict] = []
    for case in services.queue.pending_image_acquisition():
        payload.append(
            {
                "case_id": case.case_id,
                "status": case.state.value,
                "metadata": {
                    "child_name": case.metadata.child_name,
                    "animal_name": case.metadata.animal_name,
                    "broken_bone": case.broken_bone,
                    "qr_content": case.owner_ref,
                },
            }
        )
    return {"cases": payload}


@router.post("/cases/{case_id}/image")
async def upload_case_image(
    case_id: int,
    file: Annotated[UploadFile, File(...)],
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, int | str]:
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded image is empty")

    try:
        png_bytes = ensure_png(raw_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        case = services.queue.attach_case_image(case_id, png_bytes)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "case_id": case.case_id,
        "status": "queued",
        "queue_depth": services.queue.queue_depth,
        "expected_results": services.settings.RESULTS_PER_IMAGE,
    }


@router.delete("/cases/{case_id}/pending-image")
async def discard_pending_image_case(
    case_id: int,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, str]:
    try:
        services.queue.discard_unimaged_case(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "discarded"}
