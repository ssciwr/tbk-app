from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from .config import Settings


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def verify_password(password: str, settings: Settings) -> bool:
    return secrets.compare_digest(password, settings.SHARED_PASSWORD)


def create_access_token(settings: Settings) -> tuple[str, int]:
    expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    now = datetime.now(tz=UTC)
    expires_at = now + expires_delta
    payload = {
        "sub": "shared-user",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return token, int(expires_delta.total_seconds())


def decode_token(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_settings_from_request(request: Request) -> Settings:
    return request.app.state.services.settings


async def require_auth(
    token: Annotated[str, Depends(oauth2_scheme)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> dict:
    return decode_token(token, settings)
