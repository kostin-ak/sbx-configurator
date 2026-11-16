"""Load nodes from directories of WireGuard configs and share links."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .awg import parse_wireguard_conf
from .links import LinkError, decode_base64_payload, parse_link

_PREFIXES = ("wp1_awg_", "wag_", "awg3_", "awg_", "warp_", "wg_")
_SLOT = re.compile(r"_slot\d+$", re.IGNORECASE)


class FolderError(RuntimeError):
    pass


def _clean_tag(stem: str) -> str:
    name = stem
    for prefix in _PREFIXES:
        if name.lower().startswith(prefix):
            name = name[len(prefix):]
            break
    return _SLOT.sub("", name) or stem


def _meta_for(path: Path) -> dict[str, Any]:
    """Optional sidecar ``<stem>.yaml`` with tag/country/provider overrides."""
    candidates = (path.with_suffix(".yaml"), path.with_suffix(".yml"), path.with_name(path.stem + ".meta.yaml"))
    for candidate in candidates:
        if candidate.is_file():
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                return data
    return {}


def _apply_meta(node: dict[str, Any], meta: dict[str, Any], path: Path) -> dict[str, Any]:
    if not meta:
        return node
    from .naming import flag_for

    tag = str(meta.get("tag") or _clean_tag(path.stem))
    country = str(meta.get("country") or "").upper()
    if country:
        tag = f"{flag_for(country)}{tag}"
    node["tag"] = tag
    if node.get("type") in {"wireguard", "warp"}:
        node["name"] = tag
    if meta.get("provider"):
        node["name"] = f"{meta['provider']} {tag}"
    return node


def _parse_links_file(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    content = decode_base64_payload(path.read_text(encoding="utf-8", errors="replace"))
    nodes: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, line in enumerate(content.splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith(("#", ";", "//")):
            continue
        try:
            node = parse_link(text)
        except (LinkError, Exception) as error:  # noqa: BLE001 - per-line isolation
            errors.append(f"line {index}: {error}")
            continue
        if node:
            nodes.append(node)
        else:
            errors.append(f"line {index}: unsupported link")
    return nodes, errors


def load_folder(spec: dict[str, Any]) -> dict[str, Any]:
    """Walk a folder and return outbounds, endpoints and a per-file report."""
    path_value = spec.get("path")
    if not path_value:
        raise FolderError("folder source requires a path")
    root = Path(str(path_value))
    if not root.is_dir():
        if spec.get("optional"):
            return {
                "outbounds": [],
                "endpoints": [],
                "files": 0,
                "report": [{"file": str(root), "ok": False, "error": "folder is absent"}],
                "failed": [{"file": str(root), "ok": False, "error": "folder is absent"}],
            }
        raise FolderError(f"folder is absent: {root}")
    parser = str(spec.get("parser", "auto"))
    include = list(spec.get("include") or ["*.conf", "*.txt", "*.list"])
    recursive = bool(spec.get("recursive", False))
    system = bool(spec.get("system", False))

    pattern = "**/*" if recursive else "*"
    files = sorted(p for p in root.glob(pattern) if p.is_file())
    files = [p for p in files if any(p.match(glob) for glob in include)]

    outbounds: list[dict[str, Any]] = []
    endpoints: list[dict[str, Any]] = []
    report: list[dict[str, Any]] = []

    for path in files:
        kind = parser
        if kind == "auto":
            kind = "wireguard-conf" if path.suffix.lower() == ".conf" else "share-links"
        entry: dict[str, Any] = {"file": path.name, "parser": kind}
        try:
            if kind == "wireguard-conf":
                tag = _clean_tag(path.stem)
                endpoint = parse_wireguard_conf(path.read_text(encoding="utf-8", errors="replace"), tag, system=system)
                endpoint = _apply_meta(endpoint, _meta_for(path), path)
                if spec.get("detour"):
                    endpoint["detour"] = spec["detour"]
                endpoints.append(endpoint)
                entry.update({"tag": endpoint["tag"], "ok": True, "kind": "endpoint"})
            elif kind == "share-links":
                nodes, errors = _parse_links_file(path)
                for node in nodes:
                    outbounds.append(node)
                entry.update({"ok": not errors, "nodes": len(nodes), "kind": "outbounds"})
                if errors:
                    entry["errors"] = errors[:5]
            else:
                raise FolderError(f"unknown folder parser: {kind}")
        except Exception as error:  # noqa: BLE001 - report and continue
            entry.update({"ok": False, "error": str(error)})
        report.append(entry)

    return {
        "outbounds": outbounds,
        "endpoints": endpoints,
        "files": len(files),
        "report": report,
        "failed": [item for item in report if not item.get("ok")],
    }
