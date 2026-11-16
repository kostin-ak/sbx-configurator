"""Helpers for the visual (path table) YAML editor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True)
class Node:
    path: tuple[str | int, ...]
    kind: str
    preview: str

    @property
    def label(self) -> str:
        return display_path(self.path)


def display_path(path: tuple[str | int, ...]) -> str:
    text = ""
    for part in path:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text = f"{text}.{part}" if text else str(part)
    return text or "/"


def _preview(value: Any, limit: int = 70) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def flatten(data: Any) -> list[Node]:
    """Flatten a YAML document into container and scalar rows."""

    rows: list[Node] = []

    def walk(value: Any, path: tuple[str | int, ...]) -> None:
        if isinstance(value, dict):
            rows.append(Node(path, "map", f"{len(value)} key(s)"))
            for key, item in value.items():
                walk(item, (*path, key))
        elif isinstance(value, list):
            rows.append(Node(path, "list", f"{len(value)} item(s)"))
            for index, item in enumerate(value):
                walk(item, (*path, index))
        else:
            rows.append(Node(path, "scalar", _preview(value)))

    walk(data, ())
    return rows


def get(data: Any, path: tuple[str | int, ...]) -> Any:
    current = data
    for part in path:
        current = current[part]
    return current


def set_value(data: Any, path: tuple[str | int, ...], value: Any) -> None:
    if not path:
        raise ValueError("the root value cannot be replaced this way")
    parent = get(data, path[:-1])
    parent[path[-1]] = value


def delete(data: Any, path: tuple[str | int, ...]) -> None:
    if not path:
        raise ValueError("the root cannot be removed")
    parent = get(data, path[:-1])
    del parent[path[-1]]


def add_key(data: Any, path: tuple[str | int, ...], key: str, value: Any) -> None:
    target = get(data, path)
    if not isinstance(target, dict):
        raise ValueError("the selected node is not a mapping")
    target[key] = value


def append_item(data: Any, path: tuple[str | int, ...], value: Any) -> None:
    target = get(data, path)
    if not isinstance(target, list):
        raise ValueError("the selected node is not a list")
    target.append(value)


def parse_value(text: str) -> Any:
    if text.strip() == "":
        return None
    return yaml.safe_load(text)


def dump_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return yaml.safe_dump(value, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip()
    import json

    return json.dumps(value, ensure_ascii=False)