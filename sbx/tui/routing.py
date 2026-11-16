"""Pure helpers for editing the routing files through the TUI."""

from __future__ import annotations

from typing import Iterable

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .store import ConfigStore, Document


def _document(store: ConfigStore, name: str) -> Document:
    return store.load(store.profile.routing_dir / name)


def devices(store: ConfigStore) -> CommentedMap:
    document = _document(store, "devices.yaml")
    return document.data.setdefault("devices", CommentedMap())


def groups(store: ConfigStore) -> CommentedMap:
    document = _document(store, "groups.yaml")
    return document.data.setdefault("groups", CommentedMap())


def policies(store: ConfigStore) -> CommentedSeq:
    document = _document(store, "policies.yaml")
    return document.data.setdefault("policies", CommentedSeq())


def category_names(store: ConfigStore) -> list[str]:
    try:
        document = store.load(store.profile.routing_dir / "categories.yaml")
    except Exception:
        return []
    return [str(item.get("name")) for item in document.data.get("categories", []) if isinstance(item, dict)]


def upsert_device(store: ConfigStore, name: str, ipv4: str, ipv6: str = "") -> None:
    document = _document(store, "devices.yaml")
    table = document.data.setdefault("devices", CommentedMap())
    entry = CommentedMap()
    if ipv4:
        entry["ipv4"] = ipv4
    if ipv6:
        entry["ipv6"] = ipv6
    table[name] = entry
    store.save(document)


def remove_device(store: ConfigStore, name: str) -> None:
    document = _document(store, "devices.yaml")
    table = document.data.get("devices", {})
    table.pop(name, None)
    store.save(document)


def upsert_group(store: ConfigStore, name: str, members: Iterable[str]) -> None:
    document = _document(store, "groups.yaml")
    table = document.data.setdefault("groups", CommentedMap())
    entry = CommentedMap()
    entry["members"] = CommentedSeq([member for member in members if member])
    table[name] = entry
    store.save(document)


def remove_group(store: ConfigStore, name: str) -> None:
    document = _document(store, "groups.yaml")
    table = document.data.get("groups", {})
    table.pop(name, None)
    store.save(document)


def upsert_policy(store: ConfigStore, alias: str, categories: Iterable[str]) -> None:
    document = _document(store, "policies.yaml")
    items = document.data.setdefault("policies", CommentedSeq())
    entry = CommentedMap()
    entry["alias"] = alias
    entry["categories"] = CommentedSeq([category for category in categories if category])
    replaced = False
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("alias") == alias:
            items[index] = entry
            replaced = True
            break
    if not replaced:
        items.append(entry)
    store.save(document)


def remove_policy(store: ConfigStore, alias: str) -> None:
    document = _document(store, "policies.yaml")
    items = document.data.get("policies", [])
    document.data["policies"] = CommentedSeq(
        [item for item in items if not (isinstance(item, dict) and item.get("alias") == alias)]
    )
    store.save(document)