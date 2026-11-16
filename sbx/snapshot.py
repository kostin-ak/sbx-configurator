"""Validation helpers for the local, credential-bearing router snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_snapshot(root: Path) -> tuple[int, list[str]]:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return 0, [f"Missing snapshot manifest: {manifest_path}"]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    files = manifest.get("files", [])
    for entry in files:
        path = root / entry["path"]
        if not path.is_file():
            errors.append(f"Missing file: {entry['path']}")
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            errors.append(f"Hash mismatch: {entry['path']}")
    return len(files), errors
