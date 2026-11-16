"""Top-level deterministic build orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
import shutil

from . import migrate
from .artifact import publish_artifact
from .assembly import merge_parts
from .routing import generate_routing
from .sources import SubscriptionProcessor
from .srs import compile_rules
from .validate import validate_config
from .loader import load_config


class PipelineError(RuntimeError):
    pass


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def build(root: Path, pipeline_path: Path | None = None, compile_srs: bool | None = None) -> dict[str, Any]:
    root = root.resolve()
    pipeline_path = pipeline_path or root / "config/pipeline.yaml"
    config = yaml.safe_load(pipeline_path.read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise PipelineError("pipeline configuration must be a mapping")
    settings = config.get("settings", {})
    build_dir = _resolve(root, settings.get("build_dir", "build"))
    loaded = load_config(
        _resolve(root, settings.get("config_root", "config")),
        _resolve(root, settings.get("secrets", "config/secrets/local.yaml")),
    )
    resolved_dir = build_dir / "config"
    resolved_dir.mkdir(parents=True, exist_ok=True)
    source_config_path = resolved_dir / "source.yaml"
    routing_config_path = resolved_dir / "routing.yaml"
    source_config_path.write_text(yaml.dump(loaded.subscriptions, allow_unicode=True, sort_keys=False), encoding="utf-8")
    routing_config_path.write_text(yaml.dump(loaded.routing, allow_unicode=True, sort_keys=False), encoding="utf-8")
    config_stats = loaded.stats
    (_resolve(root, settings.get("state_runtime_root", "state/local")) / "logs").mkdir(parents=True, exist_ok=True)
    if compile_srs is None:
        compile_srs = bool(settings.get("compile_srs", True))
    srs_results = compile_rules(
        _resolve(root, settings.get("srs_input", "snapshot/etc/sing-box/configs/rules")),
        _resolve(root, settings.get("srs_output", "state/rules")),
        _resolve(root, settings.get("singbox_binary", "bin/sing-box-extended")),
    ) if compile_srs else []
    generated_dir = build_dir / "generated"
    if generated_dir.exists():
        shutil.rmtree(generated_dir)
    routing_output = generated_dir / "03-routing.json"
    selectors_db = build_dir / "generated-selectors.yaml"

    routing_stats = generate_routing(
        routing_config_path,
        routing_output,
        selectors_db,
    )
    processor = SubscriptionProcessor(
        source_config_path,
        _resolve(root, settings.get("cache_dir", "state/subscriptions")),
        selectors_db,
        generated_dir,
        force_cache=bool(settings.get("force_cache", False)) if "force_cache" in settings else None,
        path_root=_resolve(root, settings.get("source_path_root", "snapshot/etc/sing-box")),
        registry_path=_resolve(root, settings.get("protocol_registry", "protocols/registry.yaml")),
    )
    source_stats = processor.process_all()

    static_root = _resolve(root, settings.get("static_parts", "snapshot/etc/sing-box/config.parts"))
    excluded = set(settings.get("exclude_static_parts", ["30-auto-generated"]))
    merged = merge_parts(static_root, generated_dir, excluded)
    if settings.get("migrate_1_14", True):
        merged, migration_changes = migrate.migrate_config(
            merged,
            str(_resolve(root, settings.get("snapshot_runtime_root", "snapshot")).as_posix()),
            str(_resolve(root, settings.get("state_runtime_root", "state/local")).as_posix()),
            str(_resolve(root, settings.get("srs_output", "state/rules")).as_posix()),
        )
    else:
        migration_changes = []

    issues = validate_config(merged)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in errors)
        raise PipelineError(f"structural validation failed: {details}")

    artifact_dir = build_dir / "artifacts"
    output = publish_artifact(
        artifact_dir,
        "config.json",
        merged,
        {
            "routing": routing_stats,
            "config": config_stats,
            "subscriptions": source_stats,
            "srs": len(srs_results),
            "migration": migration_changes,
        },
    )
    return {
        "output": output,
        "routing": routing_stats,
        "config": config_stats,
        "srs": len(srs_results),
        "subscriptions": source_stats,
        "migration": migration_changes,
        "warnings": [f"{issue.code}: {issue.message}" for issue in issues],
    }
