from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from app.storage.providers.local import LocalFilesystemProvider


def test_local_storage_provider_writes_and_path_safety(tmp_path: Path) -> None:
    provider = LocalFilesystemProvider(tmp_path)
    label = provider.qr_pdf_backend_label()
    assert label.startswith("local (")
    assert "root=" in label

    user_ref = provider.create_storage_for_user()
    provider.upload_file(user_ref, "normal", BytesIO(b"original"), "orig.png")
    provider.upload_file(user_ref, "xray", BytesIO(b"xray"), "xray.png")

    case_dir = tmp_path / "1"
    assert (case_dir / "normal" / "orig.png").read_bytes() == b"original"
    assert (case_dir / "xray" / "xray.png").read_bytes() == b"xray"

    # Numeric refs must also work.
    provider.upload_file(1, "normal", BytesIO(b"overwrite"), "again.png")
    assert (case_dir / "normal" / "again.png").read_bytes() == b"overwrite"

    # Paths outside the configured root must be rejected.
    with pytest.raises(ValueError):
        provider.upload_file(
            "file:///tmp/not-allowed", "normal", BytesIO(b"bad"), "bad.png"
        )

    with pytest.raises(ValueError):
        provider.upload_file(
            "https://example.com/not-local", "normal", BytesIO(b"bad"), "bad.png"
        )
