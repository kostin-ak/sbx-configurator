"""Subscription source adapter with deterministic local cache handling."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import requests
import yaml

from .links import decode_base64_payload, parse_link
from .folders import load_folder
from .naming import apply_naming, split_flag
from .protocols import ProtocolRegistry
from .selectors import build_selectors
from .transforms import apply_node_rules


class SourceError(RuntimeError):
    pass


class SubscriptionProcessor:
    def __init__(self, config_path: Path, cache_dir: Path, selectors_db: Path | None, output_dir: Path, force_cache: bool | None = None, path_root: Path | None = None, registry_path: Path | None = None):
        self.config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        self.settings = self.config.get("settings", {})
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.force_cache_override = force_cache
        self.path_root = path_root
        self.registry = ProtocolRegistry(registry_path) if registry_path else None
        self.database_tags: list[str] = []
        if selectors_db and selectors_db.is_file():
            database = yaml.safe_load(selectors_db.read_text(encoding="utf-8")) or {}
            self.database_tags = [item["tag"] for item in database.get("selectors", []) if item.get("tag")]
        elif selectors_db:
            raise SourceError(f"selectors database is absent: {selectors_db}")

    def _fetch(self, subscription: dict[str, Any], force_cache: bool) -> str:
        name = subscription.get("name", "unnamed")
        if "content" in subscription:
            return str(subscription["content"]).strip()
        cache_file = self.cache_dir / f"{name}_cache.txt"
        if "file" in subscription:
            file_path = Path(subscription["file"])
            if file_path.is_absolute():
                posix = file_path.as_posix()
                if posix.startswith("/etc/sing-box/") and self.path_root:
                    file_path = self.path_root / posix.removeprefix("/etc/sing-box/")
            else:
                file_path = (self.path_root or self.config.parent) / file_path
            return file_path.read_text(encoding="utf-8").strip()
        if "url" not in subscription:
            raise SourceError(f"subscription {name} has neither url nor file")
        if force_cache and cache_file.is_file():
            return cache_file.read_text(encoding="utf-8").strip()
        try:
            response = requests.get(subscription["url"], timeout=45)
            response.raise_for_status()
            content = response.text.strip()
            if subscription.get("enable_cache") or force_cache:
                cache_file.write_text(content + "\n", encoding="utf-8")
            return content
        except Exception as error:
            if cache_file.is_file():
                return cache_file.read_text(encoding="utf-8").strip()
            raise SourceError(f"subscription {name} failed and has no cache: {error}") from error

    def process_subscription(self, subscription: dict[str, Any], global_selectors: list[dict[str, Any]], force_cache: bool) -> dict[str, Any]:
        name = subscription.get("name", "unnamed")
        folder_spec = subscription.get("folder")
        content = "" if folder_spec else decode_base64_payload(self._fetch(subscription, force_cache))
        nodes: list[dict[str, Any]] = []
        seen: set[str] = set()
        skipped = 0
        for line in content.splitlines():
            try:
                node = parse_link(line)
            except Exception:
                skipped += 1
                continue
            if not node:
                skipped += 1
                continue
            processed = apply_node_rules(node, subscription.get("rules", []))
            if not processed:
                continue
            tag = processed.get("tag", "")
            if not tag:
                continue
            final_tag, counter = tag, 1
            while final_tag in seen:
                final_tag = f"{tag} {counter}"
                counter += 1
            seen.add(final_tag)
            processed["tag"] = final_tag
            nodes.append(processed)

        folder_endpoints: list[dict[str, Any]] = []
        folder_report: list[dict[str, Any]] = []
        if folder_spec:
            loaded = load_folder(folder_spec)
            folder_endpoints = loaded["endpoints"]
            folder_report = loaded["report"]
            for item in loaded.get("failed", []):
                if item.get("error") == "folder is absent":
                    print(f"warning: subscription {name}: folder is absent: {item['file']}")
            for endpoint in folder_endpoints:
                tag = endpoint.get("tag", "")
                if tag and not split_flag(tag)[0]:
                    endpoint["tag"] = f"{name} {tag}"
                    endpoint["name"] = endpoint["tag"]
            for raw_node in loaded["outbounds"]:
                processed = apply_node_rules(deepcopy(raw_node), subscription.get("rules", []))
                if not processed or not processed.get("tag"):
                    continue
                tag = processed["tag"]
                final_tag, counter = tag, 1
                while final_tag in seen:
                    final_tag = f"{tag} {counter}"
                    counter += 1
                seen.add(final_tag)
                processed["tag"] = final_tag
                nodes.append(processed)

        native = subscription.get("outbounds", [])
        if not isinstance(native, list):
            raise SourceError(f"subscription {name} outbounds must be a list")
        for raw_node in native:
            node = deepcopy(raw_node)
            if self.registry:
                self.registry.validate(node, "outbounds")
            processed = apply_node_rules(node, subscription.get("rules", []))
            if not processed or not processed.get("tag"):
                continue
            tag = processed["tag"]
            final_tag, counter = tag, 1
            while final_tag in seen:
                final_tag = f"{tag} {counter}"
                counter += 1
            seen.add(final_tag)
            processed["tag"] = final_tag
            nodes.append(processed)

        naming = subscription.get("naming") or {}
        if naming.get("enabled", False):
            apply_naming(nodes, name)
            apply_naming(folder_endpoints, name)
        tls_defaults = subscription.get("tls") or {}
        if tls_defaults.get("insecure"):
            for node in nodes:
                node_tls = node.get("tls")
                if isinstance(node_tls, dict) and node_tls.get("enabled"):
                    node_tls["insecure"] = True

        selector_configs = global_selectors + subscription.get("selectors", [])
        selectors = build_selectors(nodes, selector_configs, self.database_tags, [item["tag"] for item in folder_endpoints])
        subscription_dir = self.output_dir / f"20-{name}"
        subscription_dir.mkdir(parents=True, exist_ok=True)
        import json
        (subscription_dir / "01-outbounds.json").write_text(
            json.dumps({"outbounds": nodes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (subscription_dir / "02-selectors.json").write_text(
            json.dumps({"outbounds": selectors}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        endpoints = deepcopy(subscription.get("endpoints", []))
        if not isinstance(endpoints, list):
            raise SourceError(f"subscription {name} endpoints must be a list")
        endpoints.extend(folder_endpoints)
        for endpoint in endpoints:
            if self.registry:
                self.registry.validate(endpoint, "endpoints")
        (subscription_dir / "03-endpoints.json").write_text(
            json.dumps({"endpoints": endpoints}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return {
            "name": name,
            "nodes": len(nodes),
            "selectors": len(selectors),
            "endpoints": len(endpoints),
            "skipped": skipped,
            "folder": folder_report,
        }

    def process_all(self) -> list[dict[str, Any]]:
        subscriptions = self.config.get("subscriptions", [])
        if not isinstance(subscriptions, list):
            raise SourceError("subscriptions must be a list")
        global_selectors = self.config.get("selectors", [])
        force_cache = self.force_cache_override if self.force_cache_override is not None else bool(self.settings.get("force_cache", False))
        return [self.process_subscription(item, global_selectors, force_cache) for item in subscriptions]
