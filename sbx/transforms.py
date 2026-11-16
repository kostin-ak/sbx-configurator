"""Deterministic node transforms inherited from the legacy pipeline."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any


_PATTERNS: dict[tuple[str, int], re.Pattern[str]] = {}


def compiled(pattern: str, flags: int = 0) -> re.Pattern[str]:
    key = (pattern, flags)
    if key not in _PATTERNS:
        _PATTERNS[key] = re.compile(pattern, flags)
    return _PATTERNS[key]


def deep_merge(target: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = deepcopy(value)
    return target


def _random_value(value: Any, seed: str) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if isinstance(item, dict):
                result[key] = _random_value(item, f"{seed}_{key}")
            elif isinstance(item, list) and item:
                digest = int(hashlib.md5(f"{seed}_{key}".encode("utf-8")).hexdigest(), 16)
                result[key] = deepcopy(item[digest % len(item)])
            else:
                result[key] = deepcopy(item)
        return result
    if isinstance(value, list) and value:
        digest = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16)
        return deepcopy(value[digest % len(value)])
    return deepcopy(value)


def apply_node_rules(node: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    current = node.get("tag", "")
    stopped = False
    for rule in rules:
        if stopped:
            break
        action = rule.get("action")
        pattern = rule.get("pattern", ".*")
        if not compiled(pattern).search(current):
            continue
        if action == "exclude":
            return None
        if action == "rename":
            current = compiled(pattern).sub(rule.get("replacement", ""), current)
            node["tag"] = current
            stopped = bool(rule.get("stop", False))
        elif action == "patch":
            deep_merge(node, rule.get("params", {}))
        elif action == "random_patch":
            seed = str(rule.get("seed", ""))
            node_id = f"{node.get('server', '')}_{current}"
            deep_merge(node, _random_value(rule.get("params", {}), f"{seed}_{node_id}"))
        else:
            raise ValueError(f"unknown node rule action: {action}")
    return node
