"""Comment-aware deterministic merging of native sing-box JSON parts."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


def remove_comments(text: str) -> str:
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    cleaned: list[str] = []
    for line in text.splitlines():
        in_string = False
        escaped = False
        position = -1
        for index, character in enumerate(line):
            if escaped:
                escaped = False
                continue
            if character == "\\":
                escaped = True
                continue
            if character == '"':
                in_string = not in_string
                continue
            if not in_string and line[index:index + 2] == "//":
                position = index
                break
        cleaned.append(line if position < 0 else line[:position])
    return "\n".join(cleaned)


def load_json_part(path: Path) -> dict[str, Any]:
    value = json.loads(remove_comments(path.read_text(encoding="utf-8")))
    if not isinstance(value, dict):
        raise ValueError(f"JSON part must contain an object: {path}")
    return value


def deep_merge(target: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, list) and "__overwrite__" in value:
            target[key] = [item for item in value if item != "__overwrite__"]
        elif key in target and isinstance(target[key], dict) and isinstance(value, dict):
            deep_merge(target[key], value)
        elif key in target and isinstance(target[key], list) and isinstance(value, list):
            if value and isinstance(value[0], dict) and "tag" in value[0]:
                _merge_tagged_lists(target[key], value)
            else:
                target[key].extend(item for item in value if item not in target[key])
        else:
            target[key] = value
    return target


def _merge_tagged_lists(target: list[Any], updates: list[Any]) -> None:
    indexes = {
        item["tag"]: index
        for index, item in enumerate(target)
        if isinstance(item, dict) and "tag" in item
    }
    for update in updates:
        if isinstance(update, dict) and update.get("tag") in indexes:
            deep_merge(target[indexes[update["tag"]]], update)
        else:
            target.append(update)
            if isinstance(update, dict) and "tag" in update:
                indexes[update["tag"]] = len(target) - 1


def collect_parts(static_root: Path, generated_root: Path, excluded_top_dirs: set[str]) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    if static_root.is_dir():
        for path in static_root.rglob("*.json"):
            relative = path.relative_to(static_root)
            if relative.parts and relative.parts[0] in excluded_top_dirs:
                continue
            if any(part.endswith(".disable") for part in relative.parent.parts):
                continue
            entries.append((relative.as_posix(), path))
    if generated_root.is_dir():
        for path in generated_root.rglob("*.json"):
            relative = PurePosixPath("30-auto-generated") / path.relative_to(generated_root)
            entries.append((relative.as_posix(), path))
    return sorted(entries, key=lambda item: item[0])


def merge_parts(static_root: Path, generated_root: Path, excluded_top_dirs: set[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for _, path in collect_parts(static_root, generated_root, excluded_top_dirs or set()):
        deep_merge(result, load_json_part(path))
    if not result:
        raise ValueError("no JSON configuration parts were found")
    return result
