from pathlib import Path

from app.storage.providers import readme_template


def test_parents_readme_bytes_supports_packaged_backend_layout(
    tmp_path: Path, monkeypatch
) -> None:
    container_root = tmp_path / "container"
    asset_path = container_root / "app" / "assets" / "PARENTS.md"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_text("hello parents", encoding="utf-8")

    fake_module_path = (
        container_root / "app" / "app" / "storage" / "providers" / "readme_template.py"
    )
    unrelated_cwd = tmp_path / "elsewhere"
    unrelated_cwd.mkdir()

    readme_template.parents_readme_bytes.cache_clear()
    monkeypatch.setattr(readme_template, "__file__", str(fake_module_path))
    monkeypatch.chdir(unrelated_cwd)

    assert readme_template.parents_readme_bytes() == b"hello parents"

    readme_template.parents_readme_bytes.cache_clear()
