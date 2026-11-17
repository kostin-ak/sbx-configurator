"""Profile bundles: export a configuration tree and import it as a profile."""

from __future__ import annotations

import json
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any

from ..loader import ConfigError, load_config
from .profiles import Profile, get_profile


class BundleError(RuntimeError):
    pass


def export_bundle(profile: Profile, include_secrets: bool = False) -> Path:
    """Write ``<root>/exports/<profile>-<stamp>.tar.gz`` with the config tree."""

    output_dir = profile.root / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = output_dir / f"{profile.name}-{stamp}.tar.gz"
    config_dir = profile.config_dir

    files: list[Path] = []
    for path in sorted(config_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix in {".bak", ".pyc"}:
            continue
        if ".trash" in path.parts or "__pycache__" in path.parts:
            continue
        if "secrets" in path.parts and not include_secrets:
            continue
        files.append(path)

    manifest = {
        "format": 1,
        "profile": profile.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "include_secrets": include_secrets,
        "files": [path.relative_to(profile.root).as_posix() for path in files],
    }

    with tarfile.open(target, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=path.relative_to(profile.root).as_posix())
        payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        info.mtime = int(datetime.now().timestamp())
        import io

        archive.addfile(info, io.BytesIO(payload))

    return target


def list_bundles(root: Path) -> list[Path]:
    folder = root / "imports"
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.tar.gz"))


def import_bundle(root: Path, path: Path, name: str | None = None) -> Profile:
    """Extract a bundle into ``profiles/<name>`` and validate it."""

    if not path.is_file():
        raise BundleError(f"bundle is absent: {path}")
    profile_name = _safe_name(name or path.name.replace(".tar.gz", ""))
    target_root = root / "profiles" / profile_name
    if target_root.exists():
        raise BundleError(f"profile already exists: {profile_name}")

    target_root.mkdir(parents=True)
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                if not (member.name == "manifest.json" or member.name.startswith("config/")):
                    continue
                destination = (target_root / member.name).resolve()
                if not _inside(destination, target_root.resolve()):
                    raise BundleError(f"unsafe path in bundle: {member.name}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    continue
                with source, destination.open("wb") as stream:
                    shutil.copyfileobj(source, stream)
        config_dir = target_root / "config"
        if not (config_dir / "pipeline.yaml").is_file():
            raise BundleError("bundle has no config/pipeline.yaml")
        secrets = config_dir / "secrets" / "local.yaml"
        load_config(config_dir, secrets if secrets.is_file() else None)
    except Exception:
        shutil.rmtree(target_root, ignore_errors=True)
        raise

    return get_profile(profile_name, root)


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_name(name: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in name)
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "imported"