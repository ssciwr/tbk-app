from __future__ import annotations

from abc import ABC, abstractmethod
from typing import BinaryIO, Literal


class StorageProvider(ABC):
    @abstractmethod
    def qr_pdf_backend_label(self) -> str:
        """Return non-secret storage backend details for QR PDF headers."""

    @abstractmethod
    def create_storage_for_user(self) -> str:
        """Create per-case storage and return a user-facing reference."""

    @abstractmethod
    def next_sequence_for_user(self, user_ref: int | str) -> int:
        """Return the next acquisition sequence number for a per-case location."""

    @abstractmethod
    def upload_file(
        self,
        user_ref: int | str,
        file_type: Literal["normal", "xray"],
        file_obj: BinaryIO,
        filename: str,
    ) -> None:
        """Upload a file to a per-case location."""
