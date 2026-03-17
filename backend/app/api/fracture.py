from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from ..auth import require_auth
from ..fracture import fracture_preview_passthrough
from ..state import Services, get_services
from ..utils import apply_no_cache_headers

router = APIRouter(prefix="/fracture", tags=["fracture"])


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
    _ = (overlay, x, y, scale, noise)  # Explicitly unused in no-op version.
    image_bytes = await image.read()
    result = fracture_preview_passthrough(image_bytes)
    response = Response(content=result, media_type="image/png")
    apply_no_cache_headers(response)
    return response


@router.post("/cases/{case_id}/results/{index}")
async def fracture_apply_noop(
    case_id: int,
    index: int,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, str]:
    _ = (case_id, index, services)
    return {"status": "noop_applied"}
