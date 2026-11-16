# Folder sources: keys, confs and raw links

Sometimes a provider gives you ready-made configs instead of a subscription URL:
WireGuard / AmneziaWG `.conf` files or a handful of share links. The pipeline can
read them straight from a folder and mix them with regular subscriptions.

## Layout

Files live outside the release packs so private keys never end up in a
`.sbxpack`:

```text
/data/sbx/keys/           # router, mode 700
├── awg3/*.conf           # AmneziaWG / WireGuard configs
├── warp/*.conf           # WARP configs
└── links/*.txt           # share links, one per line
```

Locally you can keep the same tree in `keys/` (ignored by Git). Paths are
resolved through secrets so the same config works on a workstation and on the
router:

```yaml
# config/secrets/local.yaml
keys:
  awg3: /data/sbx/keys/awg3
  warp: /data/sbx/keys/warp
  links: /data/sbx/keys/links
```

## Subscription

```yaml
apiVersion: sbx.shtorm/1
kind: Subscription
metadata:
  name: AWG
  enabled: true
fetch:
  folder:
    path: ${secret:keys.awg3}
    parser: wireguard-conf     # wireguard-conf | share-links | auto
    include: ["*.conf"]
    recursive: false
    system: false              # userspace stack, no extra TUN
naming:
  enabled: true
selectors:
  global: true
  local: []
```

`parser: auto` picks by extension: `.conf` → `wireguard-conf`, `.txt`/`.list`
→ `share-links`. A missing folder is an error unless you set `optional: true`.

Plain links work the same way:

```yaml
fetch:
  folder:
    path: ${secret:keys.links}
    parser: share-links
    include: ["*.txt", "*.list"]
```

`links/example.txt`:

```text
# comments start with #
hysteria2://PASSWORD@hy2.example.com:443/?obfs=salamander&obfs-password=OBFS&sni=hy2.example.com#Example
```

## Naming

The tag is the file name without a known prefix and the `_slotN` suffix:
`awg3_berlin_slot1.conf` → `berlin`. An optional sidecar next to the file
overrides it:

```yaml
# awg3/berlin_slot1.yaml
tag: berlin
country: DE
provider: AWG
```

With `country` the node gets a flag and can be renamed by the subscription
`naming` template (see [NAMING.md](NAMING.md)).

## WireGuard / AmneziaWG

`sbx/awg.py` converts a wg-quick file into a sing-box `wireguard` endpoint. All
AmneziaWG 3.x fields are mapped: `Jc/Jmin/Jmax`, `S1-S4`, `H1-H4`, `I1-I5`,
`HeaderProtectionKey`, `ContentPaddingAddition`.

WireGuard in sing-box 1.11+ is an **endpoint**, not an outbound. Endpoints are
valid members of selectors, so they appear in the Clash UI and in the generated
routing exactly like normal nodes.

`system: false` keeps the endpoint in the userspace stack, which is what you
want on a router: no extra interface, no extra privileges.

### When the ISP drops WireGuard

Some ISPs only allow UDP to a small set of ports (DNS, NTP, QUIC) and silently
drop everything else. In that case a direct WireGuard handshake never reaches
the server, no matter which client you use. The only ways around it are:

1. use an endpoint that listens on an allowed port (usually **UDP/443**);
2. wrap the handshake into a working outbound with `detour`:

```yaml
fetch:
  folder:
    detour: 🔗 WG Bridge
```

The detour target must not contain the endpoint itself, otherwise sing-box
fails at startup with `circular outbound dependency`. `sbx/validate.py` rejects
such configs during the build.

The endpoint binds during startup, so the selected node of the bridge must be
reachable at that moment. A dead bridge node makes the whole service fail with
`post-start endpoint`. Keep the bridge's first member alive and use
`sbxctl apply`, which rolls the artifact back if the service does not come up.

## Probes

`tools/probe_folder.py` starts one temporary sing-box process per node and
measures latency without touching the running service:

```sh
python3 tools/probe_folder.py --folder keys/awg3 --binary bin/sing-box-extended
```

On the router the same is available as `sbxctl probe awg3`.

## Security

- `keys/` is ignored by Git and never packed into a release.
- Directories are `700`, files are `600`.
- Private keys are never printed by the parser or the probe.