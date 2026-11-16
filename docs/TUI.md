# TUI configurator

`sbx-tui` is a terminal UI over the same pipeline the CLI uses. It edits the YAML
files in place, keeps comments, validates every save and never restarts the
router on its own.

## Install

The core stays dependency-light. The TUI lives behind an extra:

```bash
pip install -e ".[tui]"
sbx-tui --list-profiles
sbx-tui
```

A "light" install without the extra keeps `sbxctl`, the pipeline and the tests
working; `sbx-tui` is simply not available.

## Run

```bat
run-tui.bat
```

`run-tui.bat` uses a Windows `.venv` when it exists and otherwise runs the TUI
inside WSL (`WSL_DISTRO` defaults to `archlinux`, the repo is translated to
`/mnt/<drive>/...`). Arguments are forwarded, e.g.
`run-tui.bat --profile home`.

On Linux/macOS/WSL:

```bash
./run-tui.sh
```

## Profiles

One project can host several setups:

```text
config/                 # default profile
profiles/
└── home/
    └── config/         # named profile, same layout
```

```bash
sbx-tui --profile home
sbx-tui --list-profiles      # default + every profiles/<name>
```

`profiles/<name>/config` is a full copy of `config/`; `create_profile()` in
`sbx/tui/profiles.py` does that when you add a profile from code.

## Tabs

| Tab | What it does |
|---|---|
| **Dashboard** | profile switcher, artifact hash/size, subscription counts, Lint, Build/Deploy/Reload |
| **Sources** | add/edit/toggle/archive subscriptions, enable/disable all, fetch a URL into the cache, preview parsed nodes and types, edit transforms, preview resulting names, export/import a subscription |
| **Routing** | devices, groups and policies with add/edit/delete forms and category hints |
| **Rules** | categories (name, display, YAML rules, `disable_default`) and rule-sets (tag, type, format, URL, detour) |
| **Selectors** | add/edit/delete selector templates (`tag`, `type`, `filter`, `prefer`) |
| **Protocols** | native outbounds/endpoints, jump to the YAML file |
| **Secrets** | every value of `config/secrets/local.yaml`, masked by default, edit one key at a time |
| **YAML** | raw editor for **any** file under `config/`: every line is editable, comments survive |
| **Build** | runs `build --check`, streams the log, shows node counts and the semantic diff |
| **Logs & Probe** | tails the runtime log and runs `probe_folder.py` on `keys/awg3`, `keys/warp` or `keys/links` |
| **Deploy** | uploads the built artifact over SSH with a SHA-256 check, fetches router logs, runs whitelisted `sbxctl` actions; restart is opt-in |

Keys: `b` build, `r` reload, `F1` help, `q` quit.

## Saving rules

- `ruamel.yaml` round-trip: comments, key order and quoting are preserved.
- Writes are atomic (`tmp` + `rename`) and keep `<file>.bak`.
- After every save the whole profile is re-loaded through `sbx.loader`; if it
  does not validate, the previous content is restored and the error is shown.
- Deleting a subscription moves the file to `config/.trash/`, it is never
  unlinked.
- Secrets are displayed masked; the reveal toggle is explicit.

## Build and deploy

- Build runs in a subprocess with the same arguments as
  `python -m sbx.cli build --check`, so the result is identical to the CLI.
- Deploy calls `tools/push_artifact.py`: upload, remote SHA-256 verification,
  `sing-box check` on the device, atomic install.
- `Restart after install` is **off** by default. Nothing touches the running
  service unless you flip it.
- Builds are never executed on the router from the TUI.

## Lint

The Dashboard has a **Lint** button (and the CLI has `sbxctl lint`). It checks
what the schema cannot see:

- categories referencing unknown `rule_set` tags;
- policies referencing unknown categories, devices or groups;
- group members that do not exist;
- duplicate device addresses;
- `defaults.final` / `defaults.catch_all` pointing at unknown categories;
- duplicate selector names/tags and invalid regexes in selectors and transforms;
- a final `load_config` pass for schema errors.

Errors and warnings are listed in a modal; nothing is written.

## Why not on the router

A full build parses every node, compiles SRS rule-sets and merges JSON. On a
single-core MIPS router that saturates the CPU for minutes and can reboot the
device. The TUI runs on a workstation and talks to the router over SSH.

## Roadmap

- batch operations across subscriptions (clone definitions, apply a template);
- profile import/export as a bundle.
