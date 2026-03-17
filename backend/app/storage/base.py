from __future__ import annotations

from abc import ABC, abstractmethod
from typing import BinaryIO, Literal


class StorageProvider(ABC):
    @abstractmethod
    def create_storage_for_user(self) -> str:
        """Create per-case storage and return a user-facing reference."""

    @abstractmethod
    def upload_file(
        self,
        user_ref: int | str,
        file_type: Literal["normal", "xray"],
        file_obj: BinaryIO,
        filename: str,
    ) -> None:
        """Upload a file to a per-case location."""
