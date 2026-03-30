from __future__ import annotations

from functools import lru_cache
from pathlib import Path

README_FILENAME = "README.md"
_PARENTS_FILENAME = "PARENTS.md"


def _candidate_parents_paths() -> list[Path]:
    return [
        # Repository layout: <repo>/backend/app/storage/providers/readme_template.py
        (Path(__file__).resolve().parents[4] / "assets" / _PARENTS_FILENAME).resolve(),
        (Path.cwd() / "assets" / _PARENTS_FILENAME).resolve(),
        (Path.cwd().parent / "assets" / _PARENTS_FILENAME).resolve(),
    ]


@lru_cache(maxsize=1)
def parents_readme_bytes() -> bytes:
    for candidate in _candidate_parents_paths():
        if candidate.exists() and candidate.is_file():
            return candidate.read_bytes()

    looked_in = ", ".join(str(path) for path in _candidate_parents_paths())
    raise FileNotFoundError(
        f"Missing assets/{_PARENTS_FILENAME}. Looked in: {looked_in}"
    )
