"""Probe folder-based nodes (WireGuard/AWG configs and share links) in isolation.

Runs one temporary sing-box process per node on a local mixed port, measures
latency to a 204 endpoint, prints a table and exits. The main service is never
touched.
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sbx.awg import parse_wireguard_conf  # noqa: E402
from sbx.folders import load_folder  # noqa: E402


def probe_node(node: dict, binary: Path, port: int, state: Path, url: str, timeout: float) -> tuple[bool, float, str]:
    kind = node.get("type")
    config = {
        "log": {"level": "error"},
        "dns": {"servers": [{"type": "udp", "tag": "local", "server": "77.88.8.8", "detour": "direct"}]},
        "inbounds": [{"type": "mixed", "tag": "in", "listen": "127.0.0.1", "listen_port": port}],
        "outbounds": [{"type": "direct", "tag": "direct"}],
        "route": {"final": node["tag"], "default_domain_resolver": "local"},
    }
    if kind in {"wireguard", "warp"}:
        node = dict(node)
        node["workers"] = 2
        node["preallocated_buffers_per_pool"] = 4
        config["endpoints"] = [node]
    else:
        node = dict(node)
        node["tag"] = "probe-out"
        config["outbounds"].append(node)
        config["route"]["final"] = "probe-out"

    work = Path(tempfile.mkdtemp(prefix="probe-", dir=str(state)))
    path = work / "config.json"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    log = work / "probe.log"
    process = subprocess.Popen([str(binary), "run", "-c", str(path), "-D", str(work / "state")],
                               stdout=open(log, "w"), stderr=subprocess.STDOUT)
    time.sleep(2.0)
    started = time.time()
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"})
        )
        response = opener.open(url, timeout=timeout)
        elapsed = (time.time() - started) * 1000
        ok = response.status in (200, 204)
        detail = f"{response.status}"
    except Exception as error:  # noqa: BLE001 - probe result
        ok = False
        elapsed = (time.time() - started) * 1000
        detail = type(error).__name__
    finally:
        try:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=5)
        except Exception:
            process.kill()
    if not ok:
        lines = [line.strip() for line in log.read_text(errors="replace").splitlines() if "ERROR" in line]
        if lines:
            detail = f"{detail}: {lines[-1].split('] ')[-1][:90]}"
    return ok, elapsed, detail


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe folder nodes without touching the service")
    parser.add_argument("--folder", type=Path, action="append", default=[])
    parser.add_argument("--file", type=Path, action="append", default=[])
    parser.add_argument("--binary", type=Path, default=ROOT / "bin" / "sing-box-extended")
    parser.add_argument("--state", type=Path, default=Path("/tmp/sbx-probe"))
    parser.add_argument("--url", default="http://www.gstatic.com/generate_204")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--port", type=int, default=18095)
    parser.add_argument("--parse-only", action="store_true", help="only parse files and print the report")
    args = parser.parse_args()

    args.state.mkdir(parents=True, exist_ok=True)
    nodes: list[dict] = []
    for folder in args.folder:
        loaded = load_folder({"path": folder, "parser": "auto", "include": ["*.conf", "*.txt", "*.list"]})
        nodes.extend(loaded["endpoints"])
        nodes.extend(loaded["outbounds"])
        for item in loaded["failed"]:
            print(f"{item['file']:32s} PARSE FAIL {item.get('error')}")
    for file in args.file:
        if file.suffix.lower() == ".conf":
            nodes.append(parse_wireguard_conf(file.read_text(encoding="utf-8", errors="replace"), file.stem))
        else:
            loaded = load_folder({"path": file.parent, "parser": "share-links", "include": [file.name]})
            nodes.extend(loaded["outbounds"])

    if not nodes:
        print("no nodes to probe")
        return 1
    if args.parse_only:
        for node in nodes:
            print(f"OK   {node.get('tag', '?'):28s} {node.get('type')} {node.get('peers', [{}])[0].get('address', node.get('server', ''))}")
        print(f"\nparsed: {len(nodes)}")
        return 0

    ok_count = 0
    for index, node in enumerate(nodes):
        ok, elapsed, detail = probe_node(node, args.binary, args.port + (index % 200), args.state, args.url, args.timeout)
        ok_count += ok
        status = "OK  " if ok else "FAIL"
        print(f"{status} {node.get('tag', '?'):28s} {elapsed:7.0f}ms  {detail}")
    print(f"\nreachable: {ok_count}/{len(nodes)}")
    return 0 if ok_count == len(nodes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
