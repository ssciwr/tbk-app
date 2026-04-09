from __future__ import annotations

from functools import lru_cache
from pathlib import Path

README_FILENAME = "README.md"
_PARENTS_FILENAME = "PARENTS.md"


def _candidate_parents_paths() -> list[Path]:
    file_path = Path(__file__).resolve()
    candidates = [
        # Repository layout: <repo>/backend/app/storage/providers/readme_template.py
        file_path.parents[4] / "assets" / _PARENTS_FILENAME,
        # Packaged backend image layout: /app/app/storage/providers/readme_template.py
        file_path.parents[3] / "assets" / _PARENTS_FILENAME,
        Path.cwd() / "assets" / _PARENTS_FILENAME,
        Path.cwd().parent / "assets" / _PARENTS_FILENAME,
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
def parents_readme_bytes() -> bytes:
    for candidate in _candidate_parents_paths():
        if candidate.exists() and candidate.is_file():
            return candidate.read_bytes()

    looked_in = ", ".join(str(path) for path in _candidate_parents_paths())
    raise FileNotFoundError(
        f"Missing assets/{_PARENTS_FILENAME}. Looked in: {looked_in}"
    )
