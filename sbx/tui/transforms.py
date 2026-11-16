"""Helpers for editing subscription transforms from the TUI."""

from __future__ import annotations

from typing import Any

import yaml
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .store import ConfigStore, Document


def transforms(document: Document) -> CommentedSeq:
    value = document.data.get("transforms")
    if not isinstance(value, list):
        value = CommentedSeq()
        document.data["transforms"] = value
    return value


def parse_params(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("params must be a mapping")
    return data


def upsert_transform(
    store: ConfigStore,
    document: Document,
    index: int | None,
    action: str,
    pattern: str,
    replacement: str = "",
    params: dict[str, Any] | None = None,
    stop: bool = False,
) -> None:
    items = transforms(document)
    entry = CommentedMap()
    entry["action"] = action
    entry["pattern"] = pattern
    if action == "rename":
        entry["replacement"] = replacement
    if action in {"patch", "random_patch"} and params:
        entry["params"] = params
    if stop:
        entry["stop"] = True
    if index is None:
        items.append(entry)
    else:
        items[index] = entry
    store.save(document)


def remove_transform(store: ConfigStore, document: Document, index: int) -> None:
    items = transforms(document)
    if 0 <= index < len(items):
        items.pop(index)
        store.save(document)


def move_transform(store: ConfigStore, document: Document, index: int, delta: int) -> int:
    items = transforms(document)
    target = index + delta
    if not (0 <= index < len(items) and 0 <= target < len(items)):
        return index
    items[index], items[target] = items[target], items[index]
    store.save(document)
    return target