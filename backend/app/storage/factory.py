from __future__ import annotations

from .base import StorageProvider
from .providers.local import LocalFilesystemProvider
from .providers.seafile import SeafileProvider
from ..config import Settings


def create_storage_provider(settings: Settings) -> StorageProvider:
    if settings.STORAGE_PROVIDER == "local":
        return LocalFilesystemProvider(settings.LOCAL_STORAGE_ROOT)

    if settings.STORAGE_PROVIDER == "seafile":
        return SeafileProvider(
            server_url=settings.SEAFILE_URL or "",
            library_name=settings.SEAFILE_LIBRARY_NAME,
            username=settings.SEAFILE_USERNAME,
            password=settings.SEAFILE_PASSWORD,
            account_token=settings.SEAFILE_ACCOUNT_TOKEN,
            repo_token=settings.SEAFILE_REPO_TOKEN,
        )

    raise ValueError(f"Unsupported storage provider: {settings.STORAGE_PROVIDER}")
