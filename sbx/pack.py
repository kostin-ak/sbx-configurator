"""Versioned, checksum-verified .sbxpack creation and staging."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_NAME = "manifest.json"
EXCLUDED_NAMES = {"__pycache__", ".pytest_cache"}


def _hash_entry(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _should_include(path: Path) -> bool:
    return not any(part in EXCLUDED_NAMES for part in path.parts)


def create_pack(source: Path, output: Path, version: str, name: str = "sbx-core") -> Path:
    if not source.is_dir():
        raise FileNotFoundError(source)
    files: list[dict[str, Any]] = []
    for path in sorted(item for item in source.rglob("*") if item.is_file() and _should_include(item.relative_to(source))):
        content = path.read_bytes()
        files.append({
            "path": path.relative_to(source).as_posix(),
            "size": len(content),
            "sha256": _hash_entry(content),
        })
    manifest = {
        "format": 1,
        "name": name,
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        manifest_data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        info = zipfile.ZipInfo(MANIFEST_NAME, date_time=(1980, 1, 1, 0, 0, 0))
        archive.writestr(info, manifest_data)
        for entry in files:
            info = zipfile.ZipInfo("files/" + entry["path"], date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(info, (source / entry["path"]).read_bytes())
    return output


def verify_pack(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        try:
            if MANIFEST_NAME not in names:
                raise ValueError("missing manifest.json")
            manifest = json.loads(archive.read(MANIFEST_NAME))
        except (zipfile.BadZipFile, RuntimeError, json.JSONDecodeError) as error:
            raise ValueError(f"corrupt pack manifest: {error}") from error
        if manifest.get("format") != 1:
            raise ValueError("unsupported pack format")
        errors: list[str] = []
        for entry in manifest.get("files", []):
            member = "files/" + entry["path"]
            if member not in names:
                errors.append(f"missing pack file: {entry['path']}")
                continue
            try:
                content = archive.read(member)
            except (zipfile.BadZipFile, RuntimeError) as error:
                raise ValueError(f"corrupt pack file: {entry['path']}") from error
            if len(content) != entry.get("size") or _hash_entry(content) != entry.get("sha256"):
                errors.append(f"checksum mismatch: {entry['path']}")
        extra_files = names - {MANIFEST_NAME} - {"files/" + item["path"] for item in manifest.get("files", [])}
        if extra_files:
            errors.append(f"unexpected pack files: {sorted(extra_files)}")
        if errors:
            raise ValueError("; ".join(errors))
        return manifest


def extract_pack(path: Path, destination: Path) -> dict[str, Any]:
    manifest = verify_pack(path)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            if member.filename == MANIFEST_NAME:
                continue
            relative = Path(member.filename).relative_to("files")
            target = destination / relative
            if not destination.resolve() in target.resolve().parents:
                raise ValueError(f"unsafe pack member: {member.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
    return manifest
