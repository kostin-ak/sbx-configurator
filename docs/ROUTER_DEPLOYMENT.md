# Router deployment

The router keeps immutable releases and a single `current` symlink:

```text
/data/sbx/
├── releases/0.2.0/          # source tree of a release
├── current -> releases/0.2.0
├── snapshot/                # static parts, shared by releases
├── build/                   # generated artifact (config.json + manifest)
├── state/                   # subscription caches, rules, logs, probe dirs
├── keys/                    # private keys and confs (mode 700)
└── inbox/                   # drop zone for new key files
```

Every release links `snapshot`, `build` and `state` into the shared tree, so
switching releases never copies state.

## Stages

`/root/sbxctl` exposes each pipeline stage separately:

```sh
/root/sbxctl status                # release, PID, TUN, ports, artifact hash
/root/sbxctl fetch                 # subscription caches only (+ backup)
/root/sbxctl sync                  # inbox/ -> keys/, validate, rebuild
/root/sbxctl srs                   # compile SRS rule-sets only
/root/sbxctl build [--no-srs]      # artifact + structural/sing-box checks
/root/sbxctl check                 # checks on the current artifact
/root/sbxctl apply [--no-build]    # build (optional), restart, health check
/root/sbxctl refresh [--no-restart]# fetch + build --no-srs + check + restart
/root/sbxctl restart | start | stop
/root/sbxctl releases
/root/sbxctl rollback [VERSION]
/root/sbxctl probe [awg3|warp|links|all]
/root/sbxctl logs [N]
/root/sbxctl backup
```

`apply` keeps `config.json.prev`; if the service does not open 7890/9090 within
60 seconds, the previous artifact is restored and the service is restarted again.

## Autostart

`router/sing-box-extended.init` is a procd service. It runs `sing-box check`
before start, so a broken artifact never replaces a working service. Enable it
once:

```sh
cp /data/sbx/current/router/sing-box-extended.init /etc/init.d/sing-box-extended
chmod +x /etc/init.d/sing-box-extended
/etc/init.d/sing-box-extended enable
```

## Scheduled refresh

The subscription caches are refreshed without any build:

```text
20 5 * * * /root/sbxctl fetch >> /data/sbx/state/main/refresh.log 2>&1
```

`fetch` only downloads the caches: no parsing, no merging, no restart. A failed
subscription keeps its previous cache and does not block the rest.

## Builds on a weak router

A full build parses every node, compiles rule-sets and merges JSON. On a
single-core MIPS router this saturates the CPU for several minutes and can push
the device into swap or a reboot, which takes the network down. Build on a
workstation instead and push the finished artifact:

```bash
# workstation
python -m sbx.cli build --check
ROUTER_HOST=<router> ROUTER_PASSWORD=<password> \
  python tools/push_artifact.py --artifact build/artifacts/config.json

# router: validate and activate
/root/sbxctl deploy-artifact /data/sbx/inbox/config.json --restart
```

`push_artifact.py` uploads the file, verifies its SHA-256 on the device and calls
`sbxctl deploy-artifact`, which runs `sing-box check` before replacing anything.
`--restart` activates it immediately; without it the service keeps running and
the new artifact is used on the next restart.

`sbxctl refresh` (fetch + build + restart) still exists for maintenance windows,
but do not schedule it on a low-memory device.

## Releases

```sh
.venv/bin/python tools/make_release.py --version 0.2.0
.venv/bin/python tools/audit_release.py artifacts/sbx-0.2.0.sbxpack
ROUTER_HOST=<router> ROUTER_PASSWORD=<password> \
  .venv/bin/python tools/upgrade_router_release.py --version 0.2.0 --pack artifacts/sbx-0.2.0.sbxpack
```

The uploader verifies the SHA-256 of every file, extracts the pack into
`/data/sbx/releases/<version>`, switches `current` atomically and runs
`/root/sbxctl build`. It never restarts the service; that is `sbxctl apply`.

## Rollback

```sh
/root/sbxctl rollback          # previous release + restart
/root/sbxctl rollback 0.1.0    # explicit version
```

## Memory

A 1300-node config needs roughly 100-110 MB RSS on MIPS. The fork is started
with the default worker count; for weaker devices add `workers` and
`preallocated_buffers_per_pool` to the endpoints and lower the log level.

## Notes

- The `in-mixed` inbound (127.0.0.1:7890) is routed `direct` on purpose: it is a
  plain HTTP proxy for LAN clients, not a second tunnel.
- The service runs from `/data/sbx/current/build/artifacts/config.json`; the
  artifact is rebuilt in place, so `current` only changes the code and the
  static parts.
- Keep `snapshot/` and `state/` out of Git. They contain keys, UUIDs and
  subscription caches.
