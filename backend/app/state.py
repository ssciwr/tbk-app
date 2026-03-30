from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock

from fastapi import Request

from .config import Settings
from .qr import QRJobManager
from .queue import CaseQueue
from .storage import StorageProvider, create_storage_provider


class RunnerHeartbeatTracker:
    def __init__(self) -> None:
        self._last_poll_at: datetime | None = None
        self._lock = RLock()

    def record_poll(self, polled_at: datetime | None = None) -> datetime:
        timestamp = polled_at or datetime.now(tz=UTC)
        with self._lock:
            self._last_poll_at = timestamp
        return timestamp

    def last_poll_at(self) -> datetime | None:
        with self._lock:
            return self._last_poll_at

    def is_connected(
        self,
        *,
        stale_after_seconds: float,
        now: datetime | None = None,
    ) -> bool:
        with self._lock:
            last_poll = self._last_poll_at
        if last_poll is None:
            return False

        current = now or datetime.now(tz=UTC)
        age_seconds = (current - last_poll).total_seconds()
        return age_seconds <= stale_after_seconds


@dataclass(slots=True)
class Services:
    settings: Settings
    storage: StorageProvider
    queue: CaseQueue
    qr_jobs: QRJobManager
    runner_heartbeat: RunnerHeartbeatTracker


def build_services(settings: Settings) -> Services:
    storage = create_storage_provider(settings)
    queue = CaseQueue(
        results_per_image=settings.RESULTS_PER_IMAGE,
        carousel_size=settings.CAROUSEL_SIZE,
    )
    qr_jobs = QRJobManager(storage)
    runner_heartbeat = RunnerHeartbeatTracker()
    return Services(
        settings=settings,
        storage=storage,
        queue=queue,
        qr_jobs=qr_jobs,
        runner_heartbeat=runner_heartbeat,
    )


async def get_services(request: Request) -> Services:
    return request.app.state.services
