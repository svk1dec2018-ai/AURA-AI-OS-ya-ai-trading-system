from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically persist JSON with bounded retries for transient Windows locks."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    try:
        for attempt in range(6):
            try:
                temp.replace(path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
