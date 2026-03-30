from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class CaseState(str, Enum):
    METADATA_ENTERED = "metadata_entered"
    QUEUED = "queued"
    COLLECTING_RESULTS = "collecting_results"
    AWAITING_REVIEW = "awaiting_review"
    PENDING_FRACTURE = "pending_fracture"
    CONFIRMED = "confirmed"
    RETRIED = "retried"
    CANCELED = "canceled"


@dataclass(slots=True)
class CaseMetadata:
    child_name: str
    animal_name: str
    animal_type: str = ""


@dataclass(slots=True)
class CaseRecord:
    case_id: int
    owner_ref: str
    metadata: CaseMetadata
    broken_bone: bool
    expected_results: int
    original_bytes: bytes | None = None
    results: list[bytes] = field(default_factory=list)
    selected_result_bytes: bytes | None = None
    state: CaseState = CaseState.METADATA_ENTERED
    dispatches: int = 0
    approved_at: datetime | None = None


@dataclass(slots=True)
class CarouselItem:
    case_id: int
    owner_ref: str
    metadata: CaseMetadata
    broken_bone: bool
    original_bytes: bytes
    xray_bytes: bytes
    approved_at: datetime
