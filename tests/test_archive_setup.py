from pathlib import Path, PurePosixPath

from aura.ops.repository_audit import _archive_paths, _repository_paths


def test_archive_inventory_matches_real_checkout_without_runtime_or_secrets() -> None:
    root = Path(__file__).resolve().parents[1]
    assert _archive_paths(root) == _repository_paths(root)


def test_source_zip_without_git_can_be_audited(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(".env.local\nruntime/\n.venv/\n")
    (tmp_path / "README.md").write_text("AURA source archive")
    (tmp_path / ".env.local").write_text("PRIVATE=must-not-be-indexed")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "trade.json").write_text("{}")
    paths = _repository_paths(tmp_path)
    assert PurePosixPath("README.md") in paths
    assert PurePosixPath(".env.local") not in paths
    assert not any(path.parts[0] == "runtime" for path in paths)
