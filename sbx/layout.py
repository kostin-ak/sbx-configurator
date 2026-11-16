"""Resolved, relocatable project paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Layout:
    root: Path
    config_dir: Path
    snapshot: Path
    build: Path
    artifacts: Path
    state: Path
    bin: Path
    releases: Path
    inbox: Path
    backups: Path

    @classmethod
    def resolve(cls, root: Path | str | None = None) -> "Layout":
        project = Path(root) if root else Path(__file__).resolve().parents[1]
        return cls(
            root=project,
            config_dir=project / "config",
            snapshot=project / "snapshot",
            build=project / "build",
            artifacts=project / "artifacts",
            state=project / "state",
            bin=project / "bin",
            releases=project / "releases",
            inbox=project / "inbox",
            backups=project / "backups",
        )

    def create_runtime_directories(self) -> None:
        for path in (
            self.config_dir,
            self.build,
            self.artifacts,
            self.state,
            self.bin,
            self.releases,
            self.inbox,
            self.backups,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def singbox_binary(self) -> Path:
        return self.bin / "sing-box-extended"
