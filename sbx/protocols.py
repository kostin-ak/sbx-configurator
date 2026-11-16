"""Declarative native-protocol registry for fork-compatible objects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ProtocolRegistry:
    def __init__(self, path: Path):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if data.get("version") != 1:
            raise ValueError("unsupported protocol registry version")
        self.protocols: dict[str, dict[str, Any]] = data.get("protocols", {})

    def validate(self, node: dict[str, Any], section: str) -> None:
        kind = node.get("type")
        tag = node.get("tag")
        if not kind or not tag:
            raise ValueError(f"native {section} object requires type and non-empty tag")
        definition = self.protocols.get(kind)
        if definition is None:
            raise ValueError(f"unknown native protocol {kind} for {tag}")
        if definition.get("section") != section:
            raise ValueError(f"protocol {kind} belongs to {definition.get('section')}, not {section}")
        missing = [field for field in definition.get("required", []) if field not in node]
        if missing:
            raise ValueError(f"native {kind} {tag} is missing required fields: {', '.join(missing)}")
