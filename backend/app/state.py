from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from .config import Settings
from .qr import QRJobManager
from .queue import CaseQueue
from .storage import StorageProvider, create_storage_provider


@dataclass(slots=True)
class Services:
    settings: Settings
    storage: StorageProvider
    queue: CaseQueue
    qr_jobs: QRJobManager


def build_services(settings: Settings) -> Services:
    storage = create_storage_provider(settings)
    queue = CaseQueue(
        results_per_image=settings.RESULTS_PER_IMAGE,
        carousel_size=settings.CAROUSEL_SIZE,
    )
    qr_jobs = QRJobManager(storage, storage_backend=settings.STORAGE_PROVIDER)
    return Services(settings=settings, storage=storage, queue=queue, qr_jobs=qr_jobs)


async def get_services(request: Request) -> Services:
    return request.app.state.services
