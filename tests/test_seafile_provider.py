from __future__ import annotations

from io import BytesIO

from app.storage.providers import seafile
from app.storage.providers.parents_assets import ParentAsset
from app.storage.providers.seafile import SeafileProvider


def test_seafile_provider_is_mockable(monkeypatch) -> None:
    monkeypatch.setattr(
        seafile,
        "parents_asset_files",
        lambda: (
            ParentAsset("PARENTS.md", b"Liebe Eltern,\n"),
            ParentAsset("consent.txt", b"consent details"),
        ),
    )
    monkeypatch.setattr(SeafileProvider, "_get_server_version", lambda self: "12.0")
    monkeypatch.setattr(SeafileProvider, "_ensure_library", lambda self: "repo-1")
    monkeypatch.setattr(SeafileProvider, "_discover_next_case_id", lambda self: 1)

    upload_calls: list[tuple[str, str]] = []
    link_calls: list[str] = []
    created_dirs: list[str] = []

    monkeypatch.setattr(
        SeafileProvider, "_create_dir", lambda self, path: created_dirs.append(path)
    )
    monkeypatch.setattr(
        SeafileProvider,
        "_create_shared_link",
        lambda self, path: f"https://seafile.local/s/{path.strip('/')}",
    )
    monkeypatch.setattr(
        SeafileProvider,
        "_upload_to_repo",
        lambda self, parent_dir, file_obj, filename: upload_calls.append(
            (parent_dir, filename)
        ),
    )
    monkeypatch.setattr(
        SeafileProvider,
        "_upload_via_share_link",
        lambda self, share_link, file_type, file_obj, filename: link_calls.append(
            f"{share_link}:{file_type}:{filename}"
        ),
    )

    provider = SeafileProvider(
        server_url="https://seafile.local",
        library_name="Teddy",
        account_token="super-secret-account-token",
    )
    label = provider.qr_pdf_backend_label()
    assert "seafile (" in label
    assert "url=https://seafile.local" in label
    assert "library=Teddy" in label
    assert "auth=" not in label
    assert "repo_id=" not in label
    assert "version=" not in label
    assert "super-secret-account-token" not in label

    ref = provider.create_storage_for_user()
    assert ref.startswith("https://seafile.local/s/")
    assert "/1" in created_dirs
    assert upload_calls == [("/1", "PARENTS.md"), ("/1", "consent.txt")]

    provider.upload_file(1, "normal", BytesIO(b"a"), "original.png")
    assert upload_calls[-1] == ("/1", "original.png")

    provider.upload_file(
        "https://seafile.local/s/abcd/", "xray", BytesIO(b"b"), "xray.png"
    )
    assert link_calls == ["https://seafile.local/s/abcd/:xray:xray.png"]
    provider.upload_file(1, "combined", BytesIO(b"c"), "combined.png")
    assert upload_calls[-1] == ("/1", "combined.png")

    monkeypatch.setattr(
        SeafileProvider,
        "_list_dir",
        lambda self, path: [
            {"name": "Bunny_1_original.png"},
            {"name": "Bunny_1_xray.png"},
            {"name": "Bunny_1_combined.png"},
            {"name": "Otter_2_original.png"},
            {"name": "notes.txt"},
        ],
    )
    assert provider.next_sequence_for_user(1) == 3


def test_seafile_provider_repo_token_mode(monkeypatch) -> None:
    monkeypatch.setattr(SeafileProvider, "_get_server_version", lambda self: "12.0")
    monkeypatch.setattr(SeafileProvider, "_discover_next_case_id", lambda self: 5)

    def fake_request_json(self, method, path, **kwargs):
        if path == "/api/v2.1/via-repo-token/repo-info/":
            return {"repo_id": "repo-xyz"}
        return {}

    monkeypatch.setattr(SeafileProvider, "_request_json", fake_request_json)

    provider = SeafileProvider(
        server_url="https://seafile.local",
        library_name="Teddy",
        repo_token="repo-token",
    )

    assert provider.repo_id == "repo-xyz"
    label = provider.qr_pdf_backend_label()
    assert "seafile (" in label
    assert "url=https://seafile.local" in label
    assert "library=Teddy" in label
    assert "auth=" not in label
    assert "repo_id=" not in label
    assert "repo-token" not in label
