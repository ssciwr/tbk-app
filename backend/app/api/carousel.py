from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ..auth import require_auth
from ..models import CarouselItem
from ..state import Services, get_services
from ..utils import apply_no_cache_headers, cached_binary_response, etag_for_bytes

router = APIRouter(tags=["carousel"])


def _carousel_manifest_etag(
    items: list[CarouselItem], *, max_items: int, autoplay_interval_seconds: int
) -> str:
    manifest = "|".join(
        [
            str(max_items),
            str(autoplay_interval_seconds),
            *[
                f"{item.case_id}:{item.approved_at.isoformat()}:{item.metadata.child_name}:"
                f"{item.metadata.animal_name}:{item.metadata.animal_type}:{item.broken_bone}:"
                f"{item.owner_ref}"
                for item in items
            ],
        ]
    )
    return etag_for_bytes(manifest.encode("utf-8"))


def _apply_manifest_cache_headers(response: Response, etag: str) -> None:
    response.headers["Cache-Control"] = "private, no-cache"
    response.headers["ETag"] = etag
    response.headers["Vary"] = "Authorization"


@router.get("/carousel")
async def carousel_list(
    request: Request,
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    carousel_items = services.queue.carousel_items()
    etag = _carousel_manifest_etag(
        carousel_items,
        max_items=services.settings.CAROUSEL_SIZE,
        autoplay_interval_seconds=services.settings.CAROUSEL_AUTOPLAY_SECONDS,
    )
    if request.headers.get("if-none-match") == etag:
        response = Response(status_code=304)
        _apply_manifest_cache_headers(response, etag)
        return response

    items = []
    for item in carousel_items:
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
                    request.app.url_path_for(
                        "carousel_image_by_case", case_id=item.case_id, kind="xray"
                    )
                ),
                "original_url": str(
                    request.app.url_path_for(
                        "carousel_image_by_case",
                        case_id=item.case_id,
                        kind="original",
                    )
                ),
                "approved_at": item.approved_at.isoformat(),
            }
        )
    response = JSONResponse(
        content={
            "items": items,
            "max_items": services.settings.CAROUSEL_SIZE,
            "autoplay_interval_seconds": services.settings.CAROUSEL_AUTOPLAY_SECONDS,
        }
    )
    _apply_manifest_cache_headers(response, etag)
    return response


@router.get("/carousel/items/{case_id}/{kind}", name="carousel_image_by_case")
async def carousel_image_by_case(
    request: Request,
    case_id: int,
    kind: Literal["xray", "original"],
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    for item in services.queue.carousel_items():
        if item.case_id == case_id:
            content = item.xray_bytes if kind == "xray" else item.original_bytes
            return cached_binary_response(content, request, media_type="image/png")
    raise HTTPException(status_code=404, detail="Carousel item not found")


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
