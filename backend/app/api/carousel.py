from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..auth import require_auth
from ..state import Services, get_services
from ..utils import apply_no_cache_headers

router = APIRouter(tags=["carousel"])


@router.get("/carousel")
async def carousel_list(
    request: Request,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, list[dict] | int]:
    items = []
    for idx, item in enumerate(services.queue.carousel_items()):
        items.append(
            {
                "case_id": item.case_id,
                "metadata": {
                    "child_name": item.metadata.child_name,
                    "animal_name": item.metadata.animal_name,
                    "animal_type": item.metadata.animal_type,
                    "broken_bone": item.broken_bone,
                    "qr_content": item.owner_ref,
                },
                "xray_url": str(
                    request.url_for("carousel_image", index=idx, kind="xray")
                ),
                "original_url": str(
                    request.url_for("carousel_image", index=idx, kind="original")
                ),
                "approved_at": item.approved_at.isoformat(),
            }
        )
    return {
        "items": items,
        "max_items": services.settings.CAROUSEL_SIZE,
        "autoplay_interval_seconds": services.settings.CAROUSEL_AUTOPLAY_SECONDS,
    }


@router.get("/carousel/{index}/{kind}", name="carousel_image")
async def carousel_image(
    index: int,
    kind: Literal["xray", "original"],
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    items = services.queue.carousel_items()
    if index < 0 or index >= len(items):
        raise HTTPException(status_code=404, detail="Carousel item not found")

    item = items[index]
    content = item.xray_bytes if kind == "xray" else item.original_bytes
    response = Response(content=content, media_type="image/png")
    apply_no_cache_headers(response)
    return response
