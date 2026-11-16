"""Configuration profiles: one project root can host several setups."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Profile:
    """A self-contained configuration tree."""

    name: str
    root: Path
    config_dir: Path
    pipeline: Path
    secrets: Path
    build_dir: Path

    @property
    def subscriptions_dir(self) -> Path:
        return self.config_dir / "subscriptions.d"

    @property
    def routing_dir(self) -> Path:
        return self.config_dir / "routing"

    @property
    def protocols_dir(self) -> Path:
        return self.config_dir / "protocols.d"

    @property
    def rules_dir(self) -> Path:
        return self.config_dir / "rules"

    @property
    def selectors_file(self) -> Path:
        return self.config_dir / "selectors.yaml"

    @property
    def artifact(self) -> Path:
        return self.build_dir / "artifacts" / "config.json"

    @property
    def manifest(self) -> Path:
        return self.build_dir / "artifacts" / "config.json.manifest.json"

    @property
    def diff_file(self) -> Path:
        return self.build_dir / "artifacts" / "diff.json"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _profile(name: str, base: Path) -> Profile | None:
    config_dir = base / "config"
    pipeline = config_dir / "pipeline.yaml"
    if not pipeline.is_file():
        return None
    return Profile(
        name=name,
        root=base,
        config_dir=config_dir,
        pipeline=pipeline,
        secrets=config_dir / "secrets" / "local.yaml",
        build_dir=base / "build",
    )


def list_profiles(root: Path | None = None) -> list[Profile]:
    root = (root or project_root()).resolve()
    profiles: list[Profile] = []
    default = _profile("default", root)
    if default:
        profiles.append(default)
    base = root / "profiles"
    if base.is_dir():
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            candidate = _profile(entry.name, entry)
            if candidate:
                profiles.append(candidate)
    return profiles


def get_profile(name: str = "default", root: Path | None = None) -> Profile:
    for profile in list_profiles(root):
        if profile.name == name:
            return profile
    raise KeyError(f"unknown profile: {name}")


def create_profile(name: str, root: Path | None = None) -> Profile:
    """Create ``profiles/<name>`` by copying the example config tree."""

    import shutil

    root = (root or project_root()).resolve()
    if name in {"default", ""}:
        raise ValueError("default profile already exists")
    base = root / "profiles" / name
    if base.exists():
        raise FileExistsError(base)
    source = root / "config"
    target = base / "config"
    shutil.copytree(source, target)
    candidate = _profile(name, base)
    if candidate is None:
        raise RuntimeError("profile was not created correctly")
    return candidate