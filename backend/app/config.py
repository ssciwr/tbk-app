from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    APP_NAME: str = "Teddy Hospital X-Ray"

    SHARED_PASSWORD: str = "teddy"
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    RESULTS_PER_IMAGE: int = 3
    CAROUSEL_SIZE: int = 50

    STORAGE_PROVIDER: Literal["local", "seafile"] = "local"

    LOCAL_STORAGE_ROOT: Path = Path("./data/storage")

    SEAFILE_URL: str | None = None
    SEAFILE_LIBRARY_NAME: str = "Teddy Hospital"
    SEAFILE_USERNAME: str | None = None
    SEAFILE_PASSWORD: str | None = None
    SEAFILE_ACCOUNT_TOKEN: str | None = None
    SEAFILE_REPO_TOKEN: str | None = None

    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: list[str] | str) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                try:
                    decoded = json.loads(stripped)
                    if isinstance(decoded, list):
                        return [
                            str(item).strip() for item in decoded if str(item).strip()
                        ]
                except json.JSONDecodeError:
                    pass
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
