from __future__ import annotations

import shutil
from pathlib import Path
import re
from threading import Lock
from typing import BinaryIO, Literal
from urllib.parse import unquote, urlparse

from ..base import StorageProvider


class LocalFilesystemProvider(StorageProvider):
    _SEQUENCE_PATTERN = re.compile(r"_(\d+)_(?:original|xray)\.png$")

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._next_id = self._discover_next_id()

    def _discover_next_id(self) -> int:
        max_id = 0
        for path in self.root_dir.iterdir():
            if path.is_dir() and path.name.isdigit():
                max_id = max(max_id, int(path.name))
        return max_id + 1

    def _case_dir(self, case_id: int) -> Path:
        case_dir = self.root_dir / str(case_id)
        case_dir.mkdir(parents=True, exist_ok=True)
        return case_dir

    def qr_pdf_backend_label(self) -> str:
        return f"local (root={self.root_dir})"

    def create_storage_for_user(self) -> str:
        with self._lock:
            case_id = self._next_id
            self._next_id += 1
        case_dir = self._case_dir(case_id)
        return case_dir.as_uri()

    def _resolve_user_ref(self, user_ref: int | str) -> Path:
        if isinstance(user_ref, int):
            return self._case_dir(user_ref)

        if user_ref.isdigit():
            return self._case_dir(int(user_ref))

        parsed = urlparse(user_ref)
        if parsed.scheme != "file":
            raise ValueError("Unsupported user reference for local provider")

        case_dir = Path(unquote(parsed.path)).resolve()
        try:
            case_dir.relative_to(self.root_dir)
        except ValueError as exc:
            raise ValueError("Invalid local storage path") from exc

        if not case_dir.exists() or not case_dir.is_dir():
            raise ValueError("Referenced local storage path does not exist")

        return case_dir

    def next_sequence_for_user(self, user_ref: int | str) -> int:
        case_dir = self._resolve_user_ref(user_ref)
        max_sequence = 0
        for path in case_dir.iterdir():
            if not path.is_file():
                continue
            match = self._SEQUENCE_PATTERN.search(path.name)
            if match is None:
                continue
            max_sequence = max(max_sequence, int(match.group(1)))
        return max_sequence + 1

    def upload_file(
        self,
        user_ref: int | str,
        file_type: Literal["normal", "xray"],
        file_obj: BinaryIO,
        filename: str,
    ) -> None:
        if file_type not in {"normal", "xray"}:
            raise ValueError("file_type must be 'normal' or 'xray'")

        case_dir = self._resolve_user_ref(user_ref)
        target_dir = case_dir.resolve()

        try:
            target_dir.relative_to(case_dir)
        except ValueError as exc:
            raise ValueError("Invalid upload target directory") from exc

        safe_name = Path(filename).name
        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("Invalid filename")

        target_path = (target_dir / safe_name).resolve()
        try:
            target_path.relative_to(target_dir)
        except ValueError as exc:
            raise ValueError("Path traversal detected") from exc

        if hasattr(file_obj, "seek"):
            file_obj.seek(0)

        with target_path.open("wb") as destination:
            shutil.copyfileobj(file_obj, destination)
