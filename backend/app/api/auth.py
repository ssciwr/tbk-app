from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, status

from ..auth import AuthTokenResponse, create_access_token, require_auth, verify_password
from ..state import Services, get_services

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=AuthTokenResponse)
async def login_for_token(
    password: Annotated[str, Form()],
    services: Annotated[Services, Depends(get_services)],
) -> AuthTokenResponse:
    if not verify_password(password, services.settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expires_in = create_access_token(services.settings)
    return AuthTokenResponse(access_token=token, expires_in=expires_in)


@router.get("/verify")
async def verify_token(_: Annotated[dict, Depends(require_auth)]) -> dict[str, bool]:
    return {"valid": True}
