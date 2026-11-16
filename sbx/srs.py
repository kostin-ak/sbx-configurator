"""Reproducible SRS compilation with an explicit sing-box compiler."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml


SUPPORTED_TYPES = (
    "domain", "domain_suffix", "domain_keyword", "domain_regex", "geosite",
    "ip_cidr", "ip_suffix", "source_ip_cidr", "source_port", "port",
    "process_name", "process_path", "package_name", "wifi_ssid", "wifi_bssid",
)


def _read_items(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith(("#", "//"))
    }


def build_source_json(manifest_path: Path) -> dict[str, Any] | None:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    output_name = manifest.get("output")
    if not output_name:
        raise ValueError(f"missing output in {manifest_path}")
    combined: dict[str, list[str]] = {}
    for rule_type in SUPPORTED_TYPES:
        files = manifest.get("rules", {}).get(rule_type, [])
        if isinstance(files, str):
            files = [files]
        items: set[str] = set()
        for filename in files:
            items.update(_read_items(manifest_path.parent / filename))
        if items:
            combined[rule_type] = sorted(items)
    if not combined:
        return None
    return {"output": output_name, "source": {"version": 1, "rules": [combined]}}


def compile_rules(input_root: Path, output_root: Path, compiler: Path) -> list[dict[str, Any]]:
    if not input_root.is_dir():
        raise FileNotFoundError(input_root)
    if not compiler.is_file():
        raise FileNotFoundError(compiler)
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for manifest_path in sorted(input_root.rglob("srs-build.yaml")):
        built = build_source_json(manifest_path)
        if built is None:
            continue
        output_name = built["output"]
        output_path = output_root / (output_name if output_name.endswith(".srs") else f"{output_name}.srs")
        temporary = output_root / f".{output_name}.source.json"
        temporary.write_text(json.dumps(built["source"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            completed = subprocess.run(
                [str(compiler), "rule-set", "compile", str(temporary), "-o", str(output_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode:
                raise RuntimeError(f"SRS compilation failed for {output_name}: {completed.stderr.strip()}")
        finally:
            temporary.unlink(missing_ok=True)
        results.append({"output": output_name, "path": str(output_path)})
    if not results:
        raise RuntimeError(f"no SRS manifests produced rules in {input_root}")
    return results
