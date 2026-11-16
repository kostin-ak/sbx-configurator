"""Services used by the TUI: build, preview, logs, deploy."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from ..folders import load_folder
from ..links import decode_base64_payload, parse_link
from ..loader import load_config
from ..naming import apply_naming
from ..transforms import apply_node_rules
from .profiles import Profile
from .store import ConfigStore


class ServiceError(RuntimeError):
    pass


@dataclass
class BuildResult:
    ok: bool
    output: str
    manifest: dict[str, Any] = field(default_factory=dict)
    diff: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourcePreview:
    name: str
    kind: str
    total: int
    types: dict[str, int]
    tags: list[str]
    errors: list[str] = field(default_factory=list)


def _secrets_path(profile: Profile) -> Path | None:
    return profile.secrets if profile.secrets.is_file() else None


def load_profile(profile: Profile):
    return load_config(profile.config_dir, _secrets_path(profile))


def find_subscription(profile: Profile, name: str) -> dict[str, Any]:
    loaded = load_profile(profile)
    for item in loaded.subscriptions["subscriptions"]:
        if item.get("name") == name:
            return item
    raise ServiceError(f"subscription not found: {name}")


def preview_source(profile: Profile, name: str) -> SourcePreview:
    subscription = find_subscription(profile, name)
    if "folder" in subscription:
        result = load_folder(subscription["folder"])
        nodes = list(result["endpoints"]) + list(result["outbounds"])
        types = Counter(node.get("type", "?") for node in nodes)
        return SourcePreview(
            name=name,
            kind="folder",
            total=len(nodes),
            types=dict(types),
            tags=[node.get("tag", "?") for node in nodes[:20]],
            errors=[item.get("error", "") for item in result.get("failed", [])][:10],
        )

    text = ""
    kind = "url"
    if "url" in subscription:
        import requests

        response = requests.get(subscription["url"], timeout=45)
        response.raise_for_status()
        text = response.text
    elif "file" in subscription:
        kind = "file"
        raw = str(subscription["file"])
        if raw.startswith("/etc/sing-box/"):
            path = profile.root / "snapshot/etc/sing-box" / raw[len("/etc/sing-box/") :]
        else:
            path = Path(raw)
            if not path.is_absolute():
                path = profile.root / "snapshot/etc/sing-box" / raw
        if not path.is_file():
            raise ServiceError(f"file is absent: {path}")
        text = path.read_text(encoding="utf-8")
    else:
        raise ServiceError("subscription has neither url, file nor folder")
    return _preview_from_text(name, kind, text)


def _source_nodes(profile: Profile, subscription: dict[str, Any]) -> list[dict[str, Any]]:
    """Return raw nodes before transforms (outbounds and endpoints)."""

    if "folder" in subscription:
        result = load_folder(subscription["folder"])
        return list(result["endpoints"]) + list(result["outbounds"])
    text = ""
    if "url" in subscription:
        import requests

        response = requests.get(subscription["url"], timeout=45)
        response.raise_for_status()
        text = response.text
    elif "file" in subscription:
        raw = str(subscription["file"])
        if raw.startswith("/etc/sing-box/"):
            path = profile.root / "snapshot/etc/sing-box" / raw[len("/etc/sing-box/") :]
        else:
            path = Path(raw)
            if not path.is_absolute():
                path = profile.root / "snapshot/etc/sing-box" / raw
        text = path.read_text(encoding="utf-8")
    content = decode_base64_payload(text)
    nodes: list[dict[str, Any]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";", "//")):
            continue
        try:
            node = parse_link(line)
        except Exception:
            continue
        if node:
            nodes.append(node)
    return nodes


def preview_names(profile: Profile, name: str, limit: int = 40) -> list[tuple[str, str]]:
    """Apply transforms and naming to a source without touching the build."""

    subscription = find_subscription(profile, name)
    nodes = _source_nodes(profile, subscription)
    rules = subscription.get("rules") or []
    processed: list[dict[str, Any]] = []
    originals: list[str] = []
    for node in nodes:
        original = str(node.get("tag", ""))
        result = apply_node_rules(deepcopy(node), rules)
        if not result:
            continue
        originals.append(original)
        processed.append(result)
    apply_naming(processed, name, subscription.get("naming"))
    pairs = list(zip(originals, [str(node.get("tag", "")) for node in processed]))
    return pairs[:limit]


def preview_selector(profile: Profile, filter_pattern: str, prefer: str = "", limit: int = 60) -> list[str]:
    """Return the tags of the last artifact that match a selector filter."""

    path = profile.artifact
    if not path.is_file():
        raise ServiceError("artifact is absent; build first")
    data = json.loads(path.read_text(encoding="utf-8"))
    tags: list[str] = []
    for item in data.get("outbounds", []):
        if not isinstance(item, dict) or not item.get("tag"):
            continue
        if item.get("type") in {"selector", "urltest", "direct", "block"}:
            continue
        tags.append(str(item["tag"]))
    for item in data.get("endpoints", []):
        if isinstance(item, dict) and item.get("tag"):
            tags.append(str(item["tag"]))
    try:
        pattern = re.compile(filter_pattern)
    except re.error as error:
        raise ServiceError(f"invalid regex: {error}") from error
    matched = [tag for tag in tags if pattern.search(tag)]
    if prefer:
        try:
            preferred = re.compile(prefer)
            matched.sort(key=lambda tag: 0 if preferred.search(tag) else 1)
        except re.error:
            pass
    return matched[:limit]


def remote_logs(host: str, password: str, lines: int = 200) -> str:
    if not host:
        raise ServiceError("router host is required")
    try:
        import paramiko
    except ImportError as error:
        raise ServiceError("paramiko is not installed (pip install .[router])") from error
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username="root", password=password, timeout=15, banner_timeout=15)
    try:
        command = (
            f"tail -n {int(lines)} /data/sbx/state/local/logs/sing-box.log 2>/dev/null "
            f"|| tail -n {int(lines)} /data/sbx/state/main/logs/sing-box.log 2>/dev/null "
            f"|| echo 'no log file'"
        )
        _, stdout, stderr = client.exec_command(command, timeout=60)
        return (stdout.read().decode("utf-8", "replace") + stderr.read().decode("utf-8", "replace")).strip()
    finally:
        client.close()


def _preview_from_text(name: str, kind: str, text: str) -> SourcePreview:
    content = decode_base64_payload(text)
    types: Counter[str] = Counter()
    tags: list[str] = []
    errors: list[str] = []
    for index, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith(("#", ";", "//")):
            continue
        try:
            node = parse_link(line)
        except Exception as error:  # noqa: BLE001 - per-line report
            errors.append(f"line {index}: {error}")
            continue
        if not node:
            errors.append(f"line {index}: unsupported link")
            continue
        types[node.get("type", "?")] += 1
        if len(tags) < 20:
            tags.append(node.get("tag", "?"))
    return SourcePreview(
        name=name,
        kind=kind,
        total=sum(types.values()),
        types=dict(types),
        tags=tags,
        errors=errors[:10],
    )


def fetch_to_cache(profile: Profile, name: str) -> SourcePreview:
    """Download a URL subscription into the pipeline cache and preview it."""

    subscription = find_subscription(profile, name)
    if "url" not in subscription:
        return preview_source(profile, name)
    import requests

    response = requests.get(subscription["url"], timeout=45)
    response.raise_for_status()
    text = response.text.strip()
    cache_dir = profile.root / "state/subscriptions"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{name}_cache.txt").write_text(text, encoding="utf-8")
    return _preview_from_text(name, "url", text)


def _venv_python() -> str:
    candidate = Path(sys.executable)
    return str(candidate)


def run_build(profile: Profile, on_line: Callable[[str], None] | None = None, timeout: int = 1800) -> BuildResult:
    command = [
        _venv_python(),
        "-m",
        "sbx.cli",
        "--root",
        str(profile.root),
        "build",
        "--check",
        "--pipeline",
        str(profile.pipeline),
    ]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(profile.root) + (
        os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
    )
    process = subprocess.Popen(
        command,
        cwd=str(profile.root),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    assert process.stdout is not None
    try:
        for line in process.stdout:
            lines.append(line.rstrip("\n"))
            if on_line:
                on_line(line.rstrip("\n"))
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        raise ServiceError("build timed out")
    output = "\n".join(lines)
    result = BuildResult(ok=process.returncode == 0, output=output)
    if profile.manifest.is_file():
        try:
            result.manifest = json.loads(profile.manifest.read_text(encoding="utf-8"))
        except Exception:
            pass
    if profile.diff_file.is_file():
        try:
            result.diff = json.loads(profile.diff_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return result


def artifact_info(profile: Profile) -> dict[str, Any]:
    path = profile.artifact
    if not path.is_file():
        return {"exists": False}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "sha256": digest,
    }


def read_logs(profile: Profile, lines: int = 200) -> str:
    candidates = [
        profile.root / "state/local/logs/sing-box.log",
        profile.root / "state/main/logs/sing-box.log",
        profile.root / "state/proxy-only-runtime.log",
    ]
    for path in candidates:
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(content[-lines:])
    return "no log files found"


def run_probe(profile: Profile, target: str = "all") -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(profile.root)
    command = [
        _venv_python(),
        str(profile.root / "tools/probe_folder.py"),
        "--binary",
        str(profile.root / "bin/sing-box-extended"),
        "--state",
        str(profile.root / "state/probe"),
    ]
    if target == "all":
        for name in ("awg3", "warp", "links"):
            folder = profile.root / "keys" / name
            if folder.is_dir():
                command += ["--folder", str(folder)]
    else:
        folder = profile.root / "keys" / target
        if not folder.is_dir():
            raise ServiceError(f"folder is absent: {folder}")
        command += ["--folder", str(folder)]
    process = subprocess.run(command, cwd=str(profile.root), env=env, capture_output=True, text=True, timeout=1800)
    return (process.stdout + process.stderr).strip()


def deploy(profile: Profile, host: str, password: str, restart: bool) -> str:
    if not host:
        raise ServiceError("router host is required")
    if not profile.artifact.is_file():
        raise ServiceError("artifact is absent; build first")
    environment = os.environ.copy()
    environment["ROUTER_PASSWORD"] = password
    environment["ROUTER_HOST"] = host
    command = [
        _venv_python(),
        str(profile.root / "tools/push_artifact.py"),
        "--artifact",
        str(profile.artifact),
        "--host",
        host,
    ]
    if restart:
        command.append("--restart")
    process = subprocess.run(command, cwd=str(profile.root), env=environment, capture_output=True, text=True, timeout=900)
    return (process.stdout + process.stderr).strip()


def export_subscription(profile: Profile, name: str) -> Path:
    """Copy a subscription file (with transforms) to config/exports."""

    for path in sorted(profile.subscriptions_dir.glob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        metadata = document.get("metadata") or {}
        if metadata.get("name") == name:
            target_dir = profile.config_dir / "exports"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / path.name
            shutil.copy2(path, target)
            return target
    raise ServiceError(f"subscription not found: {name}")


def list_imports(profile: Profile) -> list[Path]:
    folder = profile.config_dir / "imports"
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.glob("*.yaml") if path.is_file())


def import_subscription(profile: Profile, path: Path) -> Path:
    """Import a subscription YAML from config/imports under a unique name."""

    if not path.is_file():
        raise ServiceError(f"file is absent: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("kind") != "Subscription":
        raise ServiceError("file is not a Subscription document")
    metadata = data.setdefault("metadata", {})
    base_name = str(metadata.get("name") or path.stem)
    metadata["name"] = _unique_name(profile, base_name)

    numbers = []
    for item in profile.subscriptions_dir.glob("*.yaml"):
        prefix = item.name.split("-", 1)[0]
        if prefix.isdigit():
            numbers.append(int(prefix))
    prefix = f"{(max(numbers) + 10) if numbers else 10:02d}"
    slug = "".join(character.lower() if character.isalnum() else "-" for character in metadata["name"])
    slug = "-".join(part for part in slug.split("-") if part) or "imported"
    target = profile.subscriptions_dir / f"{prefix}-{slug}.yaml"
    ConfigStore(profile).create(target, data)
    return target


def _unique_name(profile: Profile, base: str) -> str:
    existing: set[str] = set()
    for path in profile.subscriptions_dir.glob("*.yaml"):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        name = (document.get("metadata") or {}).get("name")
        if name:
            existing.add(str(name))
    if base not in existing:
        return base
    counter = 2
    while f"{base} ({counter})" in existing:
        counter += 1
    return f"{base} ({counter})"

SBXCTL_ACTIONS = ("status", "releases", "fetch", "probe", "logs", "rollback")


def remote_sbxctl(host: str, password: str, action: str) -> str:
    """Run a whitelisted /root/sbxctl action on the router over SSH."""

    if action not in SBXCTL_ACTIONS:
        raise ServiceError(f"action is not allowed: {action}")
    if not host:
        raise ServiceError("router host is required")
    try:
        import paramiko
    except ImportError as error:
        raise ServiceError("paramiko is not installed (pip install .[router])") from error
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username="root", password=password, timeout=15, banner_timeout=15)
    try:
        _, stdout, stderr = client.exec_command(f"/root/sbxctl {action}", timeout=300)
        return (stdout.read().decode("utf-8", "replace") + stderr.read().decode("utf-8", "replace")).strip()
    finally:
        client.close()
