"""Crash-safe artifact publication helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_json(value))


def publish_artifact(directory: Path, name: str, value: Any, metadata: dict[str, Any] | None = None) -> Path:
    """Publish config.json and a manifest containing its hash and metadata."""

    target = directory / name
    content = value if isinstance(value, bytes) else canonical_json(value)
    atomic_write_bytes(target, content)
    manifest = {
        "format": 1,
        "artifact": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "size": len(content),
        "sha256": sha256_bytes(content),
        "metadata": metadata or {},
    }
    atomic_write_json(directory / f"{name}.manifest.json", manifest)
    return target
