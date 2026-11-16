"""Helpers for editing categories and rule-sets from the TUI."""

from __future__ import annotations

from typing import Any

import yaml
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .store import ConfigStore, Document


def _document(store: ConfigStore, name: str) -> Document:
    return store.load(store.profile.routing_dir / name)


def categories(store: ConfigStore) -> CommentedSeq:
    document = _document(store, "categories.yaml")
    value = document.data.get("categories")
    if not isinstance(value, list):
        value = CommentedSeq()
        document.data["categories"] = value
    return value


def rule_sets(store: ConfigStore) -> CommentedSeq:
    document = _document(store, "rule-sets.yaml")
    value = document.data.get("rule_sets")
    if not isinstance(value, list):
        value = CommentedSeq()
        document.data["rule_sets"] = value
    return value


def category_rule_sets(entry: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for rule in entry.get("rules", []) or []:
        if isinstance(rule, dict):
            result.extend(str(tag) for tag in rule.get("rule_set", []) or [])
    return result


def parse_rules(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    if not text:
        return []
    data = yaml.safe_load(text)
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError("rules must be a YAML list of mappings")
    return data


def upsert_category(
    store: ConfigStore,
    original: str | None,
    name: str,
    display: str,
    rules: list[dict[str, Any]],
    disable_default: bool = False,
) -> None:
    document = _document(store, "categories.yaml")
    items = document.data.setdefault("categories", CommentedSeq())
    entry = CommentedMap()
    entry["name"] = name
    entry["display"] = display
    entry["rules"] = CommentedSeq(rules)
    entry["disable_default"] = bool(disable_default)
    replaced = False
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("name") == (original or name):
            items[index] = entry
            replaced = True
            break
    if not replaced:
        items.append(entry)
    store.save(document)


def remove_category(store: ConfigStore, name: str) -> None:
    document = _document(store, "categories.yaml")
    items = document.data.get("categories", [])
    document.data["categories"] = CommentedSeq(
        [item for item in items if not (isinstance(item, dict) and item.get("name") == name)]
    )
    store.save(document)


def upsert_rule_set(
    store: ConfigStore,
    original: str | None,
    tag: str,
    type: str,
    format: str,
    url: str,
    download_detour: str = "",
) -> None:
    document = _document(store, "rule-sets.yaml")
    items = document.data.setdefault("rule_sets", CommentedSeq())
    entry = CommentedMap()
    entry["tag"] = tag
    entry["type"] = type
    entry["format"] = format
    if url:
        entry["url"] = url
    if download_detour:
        entry["download_detour"] = download_detour
    replaced = False
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("tag") == (original or tag):
            items[index] = entry
            replaced = True
            break
    if not replaced:
        items.append(entry)
    store.save(document)


def remove_rule_set(store: ConfigStore, tag: str) -> None:
    document = _document(store, "rule-sets.yaml")
    items = document.data.get("rule_sets", [])
    document.data["rule_sets"] = CommentedSeq(
        [item for item in items if not (isinstance(item, dict) and item.get("tag") == tag)]
    )
    store.save(document)