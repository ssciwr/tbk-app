from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..auth import require_auth
from ..state import Services, get_services

router = APIRouter(tags=["config"])


@router.get("/config")
async def get_app_config(
    _: Annotated[dict, Depends(require_auth)],
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, bool | str | list[str]]:
    return {
        "fracture_editor_enabled": services.settings.FRACTURE_EDITOR_ENABLED,
        "generation_model": services.settings.GENERATION_MODELS[0],
        "generation_models": services.settings.GENERATION_MODELS,
    }
