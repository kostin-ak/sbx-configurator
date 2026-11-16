"""Network-free stubs for remote rule-sets during isolated tests."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any


def stub_remote_rule_sets(config: dict[str, Any], output_dir: Path, compiler: Path) -> tuple[dict[str, Any], list[str]]:
    """Return a test config where every remote rule-set is an empty local file."""

    result = deepcopy(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    changes: list[str] = []
    rule_sets = result.get("route", {}).get("rule_set", [])
    for item in rule_sets:
        if not isinstance(item, dict) or item.get("type") != "remote":
            continue
        tag = str(item.get("tag", "")).replace("/", "_")
        if not tag:
            raise ValueError("remote rule-set without tag")
        source_path = output_dir / f".{tag}.source.json"
        binary_path = output_dir / f"{tag}.srs"
        source_path.write_text(
            json.dumps({"version": 1, "rules": [{}]}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [str(compiler), "rule-set", "compile", str(source_path), "-o", str(binary_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        source_path.unlink(missing_ok=True)
        if completed.returncode:
            raise RuntimeError(f"cannot compile rule-set stub {tag}: {completed.stderr.strip()}")
        item.clear()
        item.update({"tag": tag, "type": "local", "format": "binary", "path": str(binary_path)})
        changes.append(f"stubbed remote rule-set {tag}")
    return result, changes
