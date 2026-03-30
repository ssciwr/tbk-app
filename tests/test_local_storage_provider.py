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
    provider.upload_file(user_ref, "combined", BytesIO(b"combo"), "combo.png")

    case_dir = tmp_path / "1"
    assert (
        (case_dir / "README.md").read_text(encoding="utf-8").startswith("Liebe Eltern,")
    )
    assert (case_dir / "orig.png").read_bytes() == b"original"
    assert (case_dir / "xray.png").read_bytes() == b"xray"
    assert (case_dir / "combo.png").read_bytes() == b"combo"

    # Numeric refs must also work.
    provider.upload_file(1, "normal", BytesIO(b"overwrite"), "again.png")
    assert (case_dir / "again.png").read_bytes() == b"overwrite"

    # Paths outside the configured root must be rejected.
    with pytest.raises(ValueError):
        provider.upload_file(
            "file:///tmp/not-allowed", "normal", BytesIO(b"bad"), "bad.png"
        )

    with pytest.raises(ValueError):
        provider.upload_file(
            "https://example.com/not-local", "normal", BytesIO(b"bad"), "bad.png"
        )


def test_local_storage_provider_next_sequence_uses_existing_files(
    tmp_path: Path,
) -> None:
    provider = LocalFilesystemProvider(tmp_path)
    user_ref = provider.create_storage_for_user()

    assert provider.next_sequence_for_user(user_ref) == 1
    provider.upload_file(user_ref, "normal", BytesIO(b"first"), "Bunny_1_original.png")
    provider.upload_file(user_ref, "xray", BytesIO(b"first"), "Bunny_1_xray.png")
    provider.upload_file(
        user_ref, "combined", BytesIO(b"first"), "Bunny_1_combined.png"
    )
    provider.upload_file(user_ref, "normal", BytesIO(b"second"), "Otter_2_original.png")

    assert provider.next_sequence_for_user(user_ref) == 3
