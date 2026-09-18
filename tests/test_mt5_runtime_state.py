from __future__ import annotations

import json
from pathlib import Path

import pytest

from aura.ops.mt5_autonomous_demo import runtime_lock
from aura.persistence.atomic import atomic_write_json


def test_worker_lock_blocks_duplicate_and_releases_after_failure(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="test crash"), runtime_lock(tmp_path):
        with pytest.raises(RuntimeError, match="already owns"), runtime_lock(tmp_path):
            pytest.fail("duplicate worker entered")
        raise ValueError("test crash")
    with runtime_lock(tmp_path):
        pass


def test_atomic_brain_status_retries_transient_windows_file_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    destination = tmp_path / "brain" / "status.json"
    original_replace = Path.replace
    attempts = 0

    def flaky_replace(source: Path, target: Path):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("transient reader lock")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    atomic_write_json(destination, {"state": "running"})

    assert attempts == 3
    assert json.loads(destination.read_text(encoding="utf-8")) == {"state": "running"}
    assert not tuple(destination.parent.glob(".*.tmp"))
