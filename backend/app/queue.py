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

    def _drop_from_dispatch_queue(self, case_id: int) -> None:
        self._dispatch_queue = deque(
            queued_case_id
            for queued_case_id in self._dispatch_queue
            if queued_case_id != case_id
        )

    def enqueue_case(
        self,
        *,
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
                expected_results=self.results_per_image,
                state=CaseState.METADATA_ENTERED,
            )
            self._cases[case_id] = case
            return case

    def attach_case_image(self, case_id: int, original_bytes: bytes) -> CaseRecord:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")
            if case.state != CaseState.METADATA_ENTERED:
                raise ValueError("Case is not waiting for image acquisition")

            case.original_bytes = original_bytes
            case.state = CaseState.QUEUED
            case.dispatches = 0
            case.results.clear()
            case.selected_result_bytes = None
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
                if case.original_bytes is None:
                    continue

                case.state = CaseState.COLLECTING_RESULTS
                case.dispatches += 1

                if case.dispatches < case.expected_results:
                    self._dispatch_queue.append(case_id)

                return case

            return None

    def submit_result(
        self, case_id: int, result_bytes: bytes
    ) -> tuple[int, int, bool, bool]:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")

            # Workers can still submit late results after a user resolved a case.
            # Treat these as no-op acknowledgements instead of hard failures.
            if case.state in {
                CaseState.PENDING_FRACTURE,
                CaseState.CONFIRMED,
                CaseState.CANCELED,
            }:
                return len(case.results), case.expected_results, False, True
            if case.original_bytes is None:
                raise ValueError("Case has no acquired image")

            if len(case.results) >= case.expected_results:
                return len(case.results), case.expected_results, True, True

            if len(case.results) < case.expected_results:
                case.results.append(result_bytes)

            ready_for_review = len(case.results) >= case.expected_results
            if ready_for_review:
                case.state = CaseState.AWAITING_REVIEW
                self._awaiting_review.add(case_id)
                self._drop_from_dispatch_queue(case_id)

            return len(case.results), case.expected_results, ready_for_review, False

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

    def pending_image_acquisition(self) -> list[CaseRecord]:
        with self._lock:
            cases = [
                case
                for case in self._cases.values()
                if case.state == CaseState.METADATA_ENTERED
            ]
            return sorted(cases, key=lambda case: case.case_id, reverse=True)

    def pending_fracture(self) -> list[CaseRecord]:
        with self._lock:
            cases = [
                case
                for case in self._cases.values()
                if case.state == CaseState.PENDING_FRACTURE
            ]
            return sorted(cases, key=lambda case: case.case_id, reverse=True)

    def get_review_original(self, case_id: int) -> bytes:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")
            if case.original_bytes is None:
                raise ValueError("Case has no acquired image")
            return case.original_bytes

    def get_review_result(self, case_id: int, index: int) -> bytes:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")
            if index < 0 or index >= len(case.results):
                raise IndexError("Result index out of range")
            return case.results[index]

    def confirm_case(self, case_id: int, choice_index: int) -> None:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")
            if case.state not in {
                CaseState.QUEUED,
                CaseState.COLLECTING_RESULTS,
                CaseState.RETRIED,
                CaseState.AWAITING_REVIEW,
            }:
                raise ValueError("Case is not ready for confirmation")
            if choice_index < 0 or choice_index >= len(case.results):
                raise IndexError("Invalid choice index")

            case.selected_result_bytes = case.results[choice_index]
            case.state = CaseState.PENDING_FRACTURE
            self._awaiting_review.discard(case_id)
            self._drop_from_dispatch_queue(case_id)

    def get_selected_result(self, case_id: int) -> bytes:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")
            if (
                case.state != CaseState.PENDING_FRACTURE
                or case.selected_result_bytes is None
            ):
                raise ValueError("Case is not pending fracture")
            return case.selected_result_bytes

    def finalize_case(
        self,
        case_id: int,
        *,
        output_xray: bytes,
        storage: StorageProvider,
    ) -> None:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")
            if case.state != CaseState.PENDING_FRACTURE:
                raise ValueError("Case is not pending fracture")
            if case.original_bytes is None:
                raise ValueError("Case has no acquired image")
            original_bytes = case.original_bytes

            storage.upload_file(
                case.owner_ref,
                "normal",
                BytesIO(original_bytes),
                f"{case.case_id}_original.png",
            )
            storage.upload_file(
                case.owner_ref,
                "xray",
                BytesIO(output_xray),
                f"{case.case_id}_result.png",
            )

            approved_at = datetime.now(tz=UTC)
            case.approved_at = approved_at
            case.state = CaseState.CONFIRMED

            self._carousel.appendleft(
                CarouselItem(
                    case_id=case.case_id,
                    owner_ref=case.owner_ref,
                    metadata=case.metadata,
                    broken_bone=case.broken_bone,
                    original_bytes=original_bytes,
                    xray_bytes=output_xray,
                    approved_at=approved_at,
                )
            )
            while len(self._carousel) > self.carousel_size:
                self._carousel.pop()

            # Keep case records lightweight once finalized. Recent images remain
            # available via the bounded carousel buffer.
            case.original_bytes = None
            case.results.clear()
            case.selected_result_bytes = None

    def retry_case(self, case_id: int) -> None:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")
            if case.state != CaseState.AWAITING_REVIEW:
                raise ValueError("Case is not pending review")

            case.results.clear()
            case.selected_result_bytes = None
            case.dispatches = 0
            case.state = CaseState.RETRIED
            self._awaiting_review.discard(case_id)
            self._dispatch_queue.append(case_id)

    def cancel_case(self, case_id: int) -> None:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")

            case.original_bytes = None
            case.results.clear()
            case.selected_result_bytes = None
            case.state = CaseState.CANCELED
            self._awaiting_review.discard(case_id)
            self._drop_from_dispatch_queue(case_id)

    def discard_unimaged_case(self, case_id: int) -> None:
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError("Case not found")
            if case.state != CaseState.METADATA_ENTERED:
                raise ValueError("Case already has an acquired image")
            case.state = CaseState.CANCELED

    def carousel_items(self) -> list[CarouselItem]:
        with self._lock:
            return list(self._carousel)
