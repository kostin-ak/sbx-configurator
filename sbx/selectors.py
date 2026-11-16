"""Selector generation compatible with existing per-device selectors."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .transforms import compiled


def build_selectors(nodes: list[dict[str, Any]], configs: list[dict[str, Any]], database_tags: list[str], extra_tags: list[str] | None = None) -> list[dict[str, Any]]:
    node_tags = [node["tag"] for node in nodes if node.get("tag")]
    if extra_tags:
        node_tags.extend(tag for tag in extra_tags if tag and tag not in node_tags)
    generated: list[dict[str, Any]] = []
    for raw_config in configs:
        config = deepcopy(raw_config)
        tag_rule = config.get("tag", "")
        filter_pattern = config.pop("filter", ".*")
        prefer_pattern = config.pop("prefer", "")
        matched_tags = [tag for tag in node_tags if compiled(filter_pattern).search(tag)]
        if prefer_pattern:
            preferred = compiled(prefer_pattern)
            matched_tags.sort(key=lambda tag: 0 if preferred.search(tag) else 1)
        if not matched_tags:
            continue
        use_regex = bool(config.pop("regex", False))
        if not tag_rule and not use_regex:
            continue
        targets = database_tags if not tag_rule else None
        if targets is None:
            targets = [tag for tag in database_tags if compiled(tag_rule).search(tag)] if use_regex else [tag_rule]
        for target in targets:
            members = matched_tags.copy()
            match = re.match(r"^(.*?)\s*\[(.*?)\]$", target)
            if match:
                category, device = match.groups()
                if device != "Default":
                    default = f"{category.strip()} [Default]"
                    if default in database_tags and default not in members:
                        members.insert(0, default)
            selector = deepcopy(config)
            selector["tag"] = target
            selector["outbounds"] = members
            generated.append(selector)
    return generated
