from __future__ import annotations

import json
from pathlib import Path

from aura.runtime.mt5_learning_daemon import _atomic_json


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
    _atomic_json(destination, {"state": "running"})

    assert attempts == 3
    assert json.loads(destination.read_text(encoding="utf-8")) == {"state": "running"}
    assert not tuple(destination.parent.glob(".*.tmp"))
