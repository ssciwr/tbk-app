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
    file: Annotated[UploadFile, File(...)],
    child_name: Annotated[str, Form(...)],
    animal_name: Annotated[str, Form(...)],
    qr_content: Annotated[str, Form(...)],
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
    broken_bone: Annotated[bool, Form()] = False,
) -> dict[str, int | str]:
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded image is empty")

    try:
        png_bytes = ensure_png(raw_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    metadata = CaseMetadata(
        child_name=child_name.strip(),
        animal_name=animal_name.strip(),
    )

    case = services.queue.enqueue_case(
        original_bytes=png_bytes,
        owner_ref=qr_content.strip(),
        metadata=metadata,
        broken_bone=broken_bone,
    )

    return {
        "case_id": case.case_id,
        "status": "queued",
        "queue_depth": services.queue.queue_depth,
        "expected_results": services.settings.RESULTS_PER_IMAGE,
    }
