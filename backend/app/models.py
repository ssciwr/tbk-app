from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class CaseState(str, Enum):
    QUEUED = "queued"
    COLLECTING_RESULTS = "collecting_results"
    AWAITING_REVIEW = "awaiting_review"
    CONFIRMED = "confirmed"
    RETRIED = "retried"
    CANCELED = "canceled"


@dataclass(slots=True)
class CaseMetadata:
    child_name: str
    animal_name: str


@dataclass(slots=True)
class CaseRecord:
    case_id: int
    owner_ref: str
    metadata: CaseMetadata
    broken_bone: bool
    original_bytes: bytes
    expected_results: int
    results: list[bytes] = field(default_factory=list)
    state: CaseState = CaseState.QUEUED
    dispatches: int = 0
    approved_at: datetime | None = None


@dataclass(slots=True)
class CarouselItem:
    original_bytes: bytes
    xray_bytes: bytes
    approved_at: datetime
