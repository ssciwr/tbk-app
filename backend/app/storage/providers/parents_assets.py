from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_PARENTS_DIRNAME = "parents"


@dataclass(frozen=True)
class ParentAsset:
    filename: str
    content: bytes


def _candidate_parents_dirs() -> list[Path]:
    file_path = Path(__file__).resolve()
    candidates = [
        # Repository layout: <repo>/backend/app/storage/providers/parents_assets.py
        file_path.parents[4] / "assets" / _PARENTS_DIRNAME,
        # Packaged backend image layout: /app/app/storage/providers/parents_assets.py
        file_path.parents[3] / "assets" / _PARENTS_DIRNAME,
        Path.cwd() / "assets" / _PARENTS_DIRNAME,
        Path.cwd().parent / "assets" / _PARENTS_DIRNAME,
    ]

    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_candidates.append(resolved)
    return unique_candidates


@lru_cache(maxsize=1)
def parents_asset_files() -> tuple[ParentAsset, ...]:
    for candidate in _candidate_parents_dirs():
        if candidate.exists() and candidate.is_dir():
            return tuple(
                ParentAsset(path.name, path.read_bytes())
                for path in sorted(candidate.iterdir(), key=lambda item: item.name)
                if path.is_file()
            )

    looked_in = ", ".join(str(path) for path in _candidate_parents_dirs())
    raise FileNotFoundError(
        f"Missing assets/{_PARENTS_DIRNAME}. Looked in: {looked_in}"
    )
