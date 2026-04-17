from pathlib import Path

from app.storage.providers import parents_assets


def test_parents_asset_files_supports_packaged_backend_layout(
    tmp_path: Path, monkeypatch
) -> None:
    container_root = tmp_path / "container"
    parents_dir = container_root / "app" / "assets" / "parents"
    parents_dir.mkdir(parents=True)
    (parents_dir / "welcome.md").write_text("hello parents", encoding="utf-8")
    (parents_dir / "details.txt").write_text("more info", encoding="utf-8")
    (parents_dir / "nested").mkdir()
    (parents_dir / "nested" / "ignored.txt").write_text("ignore", encoding="utf-8")

    fake_module_path = (
        container_root / "app" / "app" / "storage" / "providers" / "parents_assets.py"
    )
    unrelated_cwd = tmp_path / "elsewhere"
    unrelated_cwd.mkdir()

    parents_assets.parents_asset_files.cache_clear()
    monkeypatch.setattr(parents_assets, "__file__", str(fake_module_path))
    monkeypatch.chdir(unrelated_cwd)

    assert parents_assets.parents_asset_files() == (
        parents_assets.ParentAsset("details.txt", b"more info"),
        parents_assets.ParentAsset("welcome.md", b"hello parents"),
    )

    parents_assets.parents_asset_files.cache_clear()
