"""Batch operations across subscriptions."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Iterable

from .store import ConfigStore


def _by_name(store: ConfigStore) -> dict[str, object]:
    result: dict[str, object] = {}
    for document in store.subscriptions():
        name = (document.data.get("metadata") or {}).get("name")
        if name:
            result[str(name)] = document
    return result


def set_enabled(store: ConfigStore, names: Iterable[str], enabled: bool) -> tuple[int, list[str]]:
    mapping = _by_name(store)
    updated = 0
    errors: list[str] = []
    for name in names:
        document = mapping.get(name)
        if document is None:
            errors.append(f"{name}: not found")
            continue
        metadata = document.data.setdefault("metadata", {})
        if bool(metadata.get("enabled", True)) == enabled:
            continue
        metadata["enabled"] = enabled
        try:
            store.save(document)
            updated += 1
        except Exception as error:  # noqa: BLE001
            errors.append(f"{name}: {error}")
    return updated, errors


def archive_many(store: ConfigStore, names: Iterable[str]) -> tuple[int, list[str]]:
    mapping = _by_name(store)
    removed = 0
    errors: list[str] = []
    for name in names:
        document = mapping.get(name)
        if document is None:
            errors.append(f"{name}: not found")
            continue
        try:
            store.archive(document.path)
            removed += 1
        except Exception as error:  # noqa: BLE001
            errors.append(f"{name}: {error}")
    return removed, errors


def clone_subscription(store: ConfigStore, name: str, new_name: str | None = None) -> Path:
    mapping = _by_name(store)
    document = mapping.get(name)
    if document is None:
        raise ValueError(f"subscription not found: {name}")
    data = deepcopy(document.data)
    metadata = data.setdefault("metadata", {})
    target_name = new_name or f"{name} copy"
    if target_name in mapping:
        raise ValueError(f"subscription already exists: {target_name}")
    metadata["name"] = target_name
    metadata["enabled"] = True

    numbers = []
    for path in store.profile.subscriptions_dir.glob("*.yaml"):
        prefix = path.name.split("-", 1)[0]
        if prefix.isdigit():
            numbers.append(int(prefix))
    prefix = f"{(max(numbers) + 10) if numbers else 10:02d}"
    slug = "".join(character.lower() if character.isalnum() else "-" for character in target_name)
    slug = "-".join(part for part in slug.split("-") if part) or "clone"
    target = store.profile.subscriptions_dir / f"{prefix}-{slug}.yaml"
    store.create(target, data)
    return target