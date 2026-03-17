from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from io import BytesIO
from threading import RLock

from .models import CarouselItem, CaseMetadata, CaseRecord, CaseState
from .storage import StorageProvider


class CaseQueue:
    def __init__(self, *, results_per_image: int, carousel_size: int) -> None:
        self.results_per_image = results_per_image
        self.carousel_size = carousel_size

        self._next_case_id = 1
        self._cases: dict[int, CaseRecord] = {}
        self._dispatch_queue: deque[int] = deque()
        self._awaiting_review: set[int] = set()
        self._carousel: deque[CarouselItem] = deque()

        self._lock = RLock()

    @property
    def queue_depth(self) -> int:
        with self._lock:
            return len(self._dispatch_queue)

    def enqueue_case(
        self,
        *,
        original_bytes: bytes,
        owner_ref: str,
        metadata: CaseMetadata,
        broken_bone: bool,
    ) -> CaseRecord:
        with self._lock:
            case_id = self._next_case_id
            self._next_case_id += 1

            case = CaseRecord(
                case_id=case_id,
                owner_ref=owner_ref,
                metadata=metadata,
                broken_bone=broken_bone,
                original_bytes=original_bytes,
                expected_results=self.results_per_image,
            )
            self._cases[case_id] = case
            self._dispatch_queue.append(case_id)
            return case

    def get_case(self, case_id: int) -> CaseRecord | None:
        with self._lock:
            return self._cases.get(case_id)

    def get_next_job(self) -> CaseRecord | None:
        with self._lock:
            for _ in range(len(self._dispatch_queue)):
                case_id = self._dispatch_queue.popleft()
                case = self._cases.get(case_id)
                if case is None:
                    continue
                if case.state not in {
                    CaseState.QUEUED,
                    CaseState.COLLECTING_RESULTS,
                    CaseState.RETRIED,
                }:
                    continue

                case.state = CaseState.COLLECTING_RESULTS
                case.dispatches += 1

                if case.dispatches < case.expected_results:
                    self._dispatch_queue.append(case_id)

                return case

            return None

    def submit_result(self, case_id: int, result_bytes: bytes) -> tuple[int, int, bool]:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")

            if case.state in {CaseState.CONFIRMED, CaseState.CANCELED}:
                raise ValueError("Case is closed")

            if len(case.results) < case.expected_results:
                case.results.append(result_bytes)

            ready_for_review = len(case.results) >= case.expected_results
            if ready_for_review:
                case.state = CaseState.AWAITING_REVIEW
                self._awaiting_review.add(case_id)
                self._dispatch_queue = deque(
                    item for item in self._dispatch_queue if item != case_id
                )

            return len(case.results), case.expected_results, ready_for_review

    def pending_review(self) -> list[CaseRecord]:
        with self._lock:
            active_states = {
                CaseState.QUEUED,
                CaseState.COLLECTING_RESULTS,
                CaseState.RETRIED,
                CaseState.AWAITING_REVIEW,
            }
            cases = [
                case for case in self._cases.values() if case.state in active_states
            ]
            return sorted(cases, key=lambda case: case.case_id, reverse=True)

    def get_review_original(self, case_id: int) -> bytes:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")
            return case.original_bytes

    def get_review_result(self, case_id: int, index: int) -> bytes:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")
            if index < 0 or index >= len(case.results):
                raise IndexError("Result index out of range")
            return case.results[index]

    def confirm_case(
        self, case_id: int, choice_index: int, storage: StorageProvider
    ) -> None:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")
            if case.state != CaseState.AWAITING_REVIEW:
                raise ValueError("Case is not ready for confirmation")
            if choice_index < 0 or choice_index >= len(case.results):
                raise IndexError("Invalid choice index")

            selected = case.results[choice_index]
            storage.upload_file(
                case.owner_ref,
                "normal",
                BytesIO(case.original_bytes),
                f"{case.case_id}_original.png",
            )
            storage.upload_file(
                case.owner_ref,
                "xray",
                BytesIO(selected),
                f"{case.case_id}_result.png",
            )

            approved_at = datetime.now(tz=UTC)
            case.approved_at = approved_at
            case.state = CaseState.CONFIRMED
            self._awaiting_review.discard(case_id)

            self._carousel.appendleft(
                CarouselItem(
                    original_bytes=case.original_bytes,
                    xray_bytes=selected,
                    approved_at=approved_at,
                )
            )
            while len(self._carousel) > self.carousel_size:
                self._carousel.pop()

    def retry_case(self, case_id: int) -> None:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")
            if case.state != CaseState.AWAITING_REVIEW:
                raise ValueError("Case is not pending review")

            case.results.clear()
            case.dispatches = 0
            case.state = CaseState.RETRIED
            self._awaiting_review.discard(case_id)
            self._dispatch_queue.append(case_id)

    def cancel_case(self, case_id: int) -> None:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")

            case.results.clear()
            case.state = CaseState.CANCELED
            self._awaiting_review.discard(case_id)
            self._dispatch_queue = deque(
                item for item in self._dispatch_queue if item != case_id
            )

    def carousel_items(self) -> list[CarouselItem]:
        with self._lock:
            return list(self._carousel)
