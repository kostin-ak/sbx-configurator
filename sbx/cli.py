"""Command line entry point for safe local pipeline operations."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

import yaml

from . import __version__
from .artifact import atomic_write_json, publish_artifact
from .diff import masked_json, semantic_diff, summary
from .pack import create_pack, extract_pack, verify_pack
from .releases import activate_pack, rollback
from .runtime import make_proxy_only
from .snapshot import validate_snapshot
from .srs import compile_rules
from .validate import binary_check, validate_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def root_of(args: argparse.Namespace) -> Path:
    return Path(args.root) if getattr(args, "root", None) else PROJECT_ROOT


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def doctor(args: argparse.Namespace) -> int:
    root = root_of(args)
    print(f"project: {root}")
    print(f"python: {platform.python_version()} ({sys.executable})")
    print(f"platform: {platform.platform()}")
    binary = root / "bin" / "sing-box-extended"
    print(f"sing-box-extended: {'present' if binary.is_file() else 'not downloaded'}")
    snapshot = root / "snapshot"
    count, errors = validate_snapshot(snapshot)
    if count:
        print(f"snapshot: {count} files, {'valid' if not errors else 'invalid'}")
    elif (snapshot / "etc/sing-box/config.parts").is_dir() and not getattr(args, "require_snapshot_manifest", False):
        print("snapshot: staged subset without manifest")
        errors = []
    else:
        print("snapshot: not captured")
    for error in errors:
        print(f"error: {error}")
    if errors or (args.require_binary and not binary.is_file()):
        return 1
    return 0


def snapshot_manifest(args: argparse.Namespace) -> int:
    count, errors = validate_snapshot(root_of(args) / "snapshot")
    print(f"checked {count} files")
    for error in errors:
        print(error)
    return 1 if errors or not count else 0


def report(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    issues = validate_config(config)
    print(json.dumps(summary(config), ensure_ascii=False, indent=2))
    for issue in issues:
        print(f"{issue.severity}: {issue.code}: {issue.message}")
    return 1 if any(issue.severity == "error" for issue in issues) else 0


def check(args: argparse.Namespace) -> int:
    root = root_of(args)
    config = args.config or root / "build/local/config.json"
    binary = args.binary or root / "bin/sing-box-extended"
    workdir = args.workdir or root / "state/local"
    issues = validate_config(load_config(config))
    for issue in issues:
        print(f"{issue.severity}: {issue.code}: {issue.message}")
    if any(issue.severity == "error" for issue in issues):
        return 1
    code, output = binary_check(binary, config, workdir)
    if output:
        print(output)
    return code


def diff(args: argparse.Namespace) -> int:
    old = load_config(args.old)
    new = load_config(args.new)
    print(json.dumps(semantic_diff(old, new), ensure_ascii=False, indent=2))
    return 0


def proxy_only(args: argparse.Namespace) -> int:
    root = root_of(args)
    source = args.config or root / "build/local/config.json"
    result, changes = make_proxy_only(
        load_config(source),
        listen=args.listen,
        port=args.port,
        clash_port=args.clash_port,
        offline_rule_sets=args.offline_rule_sets,
        compiler=args.compiler or root / "bin/sing-box-extended",
        stub_dir=args.stub_dir or root / "state/rule-set-stubs",
        local_direct=not args.no_local_direct,
    )
    output = args.output or root / "build/proxy-only/config.json"
    publish_artifact(output.parent, output.name, result, {"source": str(source), "mode": "proxy-only"})
    for change in changes:
        print(f"- {change}")
    print(f"Wrote proxy-only config: {output}")
    return 0


def pack(args: argparse.Namespace) -> int:
    output = create_pack(args.source, args.output, args.version, args.name)
    manifest = verify_pack(output)
    print(f"Created {output}")
    print(f"Files: {len(manifest['files'])}")
    return 0


def pack_verify(args: argparse.Namespace) -> int:
    manifest = verify_pack(args.pack)
    print(json.dumps({key: value for key, value in manifest.items() if key != "files"}, ensure_ascii=False, indent=2))
    print(f"Files: {len(manifest['files'])}")
    return 0


def pack_extract(args: argparse.Namespace) -> int:
    manifest = extract_pack(args.pack, args.destination)
    print(f"Staged {manifest['name']} {manifest['version']} in {args.destination}")
    return 0


def pack_activate(args: argparse.Namespace) -> int:
    result = activate_pack(args.pack, args.releases, args.current)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def release_rollback(args: argparse.Namespace) -> int:
    result = rollback(args.current)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build(args: argparse.Namespace) -> int:
    from .pipeline import build as build_pipeline
    from .diff import semantic_diff

    root = root_of(args)
    result = build_pipeline(root, args.pipeline, compile_srs=False if args.no_srs else None)
    print(f"artifact: {result['output']}")
    print(f"routing: {result['routing']}")
    for subscription in result["subscriptions"]:
        print(f"subscription {subscription['name']}: {subscription['nodes']} nodes, {subscription['selectors']} selectors")
    for change in result["migration"]:
        print(f"migration: {change}")
    for warning in result["warnings"]:
        print(f"warning: {warning}")
    if args.diff_old:
        old = load_config(args.diff_old)
        new = load_config(result["output"])
        difference = semantic_diff(old, new)
        difference_path = root / "build/artifacts/diff.json"
        from .artifact import atomic_write_json
        atomic_write_json(difference_path, difference)
        print(f"semantic diff: {difference_path}")
    if args.check:
        code, output = binary_check(
            args.binary or root / "bin/sing-box-extended",
            result["output"],
            args.workdir or root / "state/local",
        )
        if output:
            print(output)
        if code:
            return code
    return 0


def srs(args: argparse.Namespace) -> int:
    """Compile SRS rule-sets only, without touching the artifact or service."""
    root = root_of(args)
    pipeline_path = args.pipeline or root / "config/pipeline.yaml"
    config = yaml.safe_load(pipeline_path.read_text(encoding="utf-8")) or {}
    settings = config.get("settings", {})

    def resolve(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else root / path

    results = compile_rules(
        args.input or resolve(settings.get("srs_input", "snapshot/etc/sing-box/configs/rules")),
        args.output or resolve(settings.get("srs_output", "state/rules")),
        args.binary or resolve(settings.get("singbox_binary", "bin/sing-box-extended")),
    )
    for result in results:
        print(f"{result['output']}: {result['path']}")
    print(f"Compiled {len(results)} rule-sets")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sbxctl")
    parser.add_argument("--root", type=Path, help="project root, defaults to this checkout")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser("doctor", help="inspect local prerequisites")
    command.add_argument("--require-binary", action="store_true")
    command.add_argument("--require-snapshot-manifest", action="store_true")
    command.set_defaults(handler=doctor)

    command = sub.add_parser("snapshot-manifest", help="verify snapshot hashes")
    command.set_defaults(handler=snapshot_manifest)

    command = sub.add_parser("report", help="print secret-free configuration report")
    command.add_argument("config", type=Path)
    command.set_defaults(handler=report)

    command = sub.add_parser("build", help="build a new artifact without restarting anything")
    command.add_argument("--pipeline", type=Path)
    command.add_argument("--check", action="store_true")
    command.add_argument("--no-srs", action="store_true", help="skip SRS rule-set compilation")
    command.add_argument("--binary", type=Path)
    command.add_argument("--workdir", type=Path)
    command.add_argument("--diff-old", type=Path)
    command.set_defaults(handler=build)

    command = sub.add_parser("srs", help="compile SRS rule-sets only")
    command.add_argument("--pipeline", type=Path)
    command.add_argument("--input", type=Path)
    command.add_argument("--output", type=Path)
    command.add_argument("--binary", type=Path)
    command.set_defaults(handler=srs)

    command = sub.add_parser("check", help="run structural and sing-box checks without restart")
    command.add_argument("--config", type=Path)
    command.add_argument("--binary", type=Path)
    command.add_argument("--workdir", type=Path)
    command.set_defaults(handler=check)

    command = sub.add_parser("diff", help="compare configurations semantically")
    command.add_argument("old", type=Path)
    command.add_argument("new", type=Path)
    command.set_defaults(handler=diff)

    command = sub.add_parser("proxy-only", help="generate isolated runtime configuration")
    command.add_argument("--config", type=Path)
    command.add_argument("--output", type=Path)
    command.add_argument("--listen", default="127.0.0.1")
    command.add_argument("--port", type=int, default=7891)
    command.add_argument("--clash-port", type=int)
    command.add_argument("--offline-rule-sets", action="store_true")
    command.add_argument("--compiler", type=Path)
    command.add_argument("--stub-dir", type=Path)
    command.add_argument("--no-local-direct", action="store_true")
    command.set_defaults(handler=proxy_only)

    command = sub.add_parser("pack", help="create a deterministic versioned .sbxpack")
    command.add_argument("source", type=Path)
    command.add_argument("output", type=Path)
    command.add_argument("--version", required=True)
    command.add_argument("--name", default="sbx-core")
    command.set_defaults(handler=pack)

    command = sub.add_parser("pack-verify", help="verify pack hashes")
    command.add_argument("pack", type=Path)
    command.set_defaults(handler=pack_verify)

    command = sub.add_parser("pack-extract", help="stage a verified pack without activation")
    command.add_argument("pack", type=Path)
    command.add_argument("destination", type=Path)
    command.set_defaults(handler=pack_extract)

    command = sub.add_parser("pack-activate", help="activate a verified local release with rollback metadata")
    command.add_argument("pack", type=Path)
    command.add_argument("releases", type=Path)
    command.add_argument("current", type=Path)
    command.set_defaults(handler=pack_activate)

    command = sub.add_parser("rollback", help="restore the previous local release")
    command.add_argument("current", type=Path)
    command.set_defaults(handler=release_rollback)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
