"""Local activation and rollback of verified, versioned releases."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .pack import extract_pack, verify_pack


def _activate(current: Path, target: Path) -> None:
    temporary = current.with_name(f".{current.name}.new")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, current)


def activate_pack(pack: Path, releases_root: Path, current: Path) -> dict:
    manifest = verify_pack(pack)
    version = manifest["version"]
    destination = releases_root / version
    if destination.exists():
        raise FileExistsError(f"release already exists: {destination}")
    staging = releases_root / f".{version}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    releases_root.mkdir(parents=True, exist_ok=True)
    extract_pack(pack, staging)
    staging.rename(destination)
    previous = current.resolve() if current.exists() or current.is_symlink() else None
    history = current.parent / "previous-release.json"
    _activate(current, destination)
    history.write_text(json.dumps({"version": version, "previous": str(previous) if previous else None}, indent=2) + "\n", encoding="utf-8")
    return {"version": version, "current": str(destination), "previous": str(previous) if previous else None}


def rollback(current: Path) -> dict:
    history = current.parent / "previous-release.json"
    data = json.loads(history.read_text(encoding="utf-8"))
    previous = data.get("previous")
    if not previous:
        raise ValueError("no previous release is recorded")
    previous_path = Path(previous)
    if not previous_path.is_dir():
        raise FileNotFoundError(previous_path)
    active = current.resolve() if current.exists() or current.is_symlink() else None
    _activate(current, previous_path)
    history.write_text(json.dumps({"version": previous_path.name, "previous": str(active) if active else None}, indent=2) + "\n", encoding="utf-8")
    return {"current": str(previous_path), "previous": str(active) if active else None}
