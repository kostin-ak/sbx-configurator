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
| **Dashboard** | profile switcher, profile export/import, artifact hash/size, subscription counts, Lint, Build/Deploy/Reload |
| **Sources** | add/edit/toggle/archive subscriptions, clone, batch operations, enable/disable all, fetch a URL into the cache, preview parsed nodes and types, edit transforms, preview resulting names, export/import a subscription |
| **Routing** | devices, groups and policies with add/edit/delete forms and category hints |
| **Rules** | categories (name, display, YAML rules, `disable_default`) and rule-sets (tag, type, format, URL, detour) |
| **Selectors** | add/edit/delete selector templates (`tag`, `type`, `filter`, `prefer`) |
| **Protocols** | native outbounds/endpoints, jump to the YAML file |
| **Secrets** | every value of `config/secrets/local.yaml`, masked by default, edit one key at a time |
| **YAML** | raw editor for **any** file under `config/`: every line is editable, comments survive |
| **Visual** | the same files as a path/type/value table: edit any node as YAML, add keys/items, delete |
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

## Text editor and vim

The YAML tab is a `TextArea` with YAML syntax highlighting (tree-sitter via
`textual[syntax]`), line numbers and the usual selection/undo shortcuts.

For **real vim** press **Open in vim**: the TUI suspends, `$EDITOR` (or
`$VISUAL`, `vim` by default) opens the file with the full editor you already
use, and on exit the file is validated and reloaded. This is genuine vim
compatibility, not a re-implementation: macros, plugins, `:commands`, search and
syntax highlighting all come from your editor.

```bash
EDITOR=nvim run-tui.sh      # or set VISUAL
```

If the editor is not installed, the button reports it instead of failing the
app.

## Visual editor

The Visual tab renders the selected file as a flattened table:

```text
/                       map     3 key(s)
metadata                map     2 key(s)
metadata.name           scalar  Example
transforms[0].pattern   scalar  ([🇦-🇿]{2})
```

- **Edit** replaces the selected node with YAML text (scalars, mappings, lists);
- **Add key** adds an entry to the selected mapping;
- **Add item** appends to the selected list;
- **Delete** removes the selected node (the root cannot be deleted).

Every operation goes through the same validated save as the text editor:
round-trip YAML, atomic write, `.bak`, and rollback if the profile stops
loading. The Visual tab works for *every* file, including ones without a
dedicated form; subscriptions, routing, rules, selectors, protocols and secrets
have specialised forms in their own tabs.

## Batch operations

**Batch…** on the Sources tab opens a multi-select list and applies one action
to every ticked subscription: enable, disable or archive. The operation reports
the number of updated entries and any per-source errors; saving still validates
the whole profile after each file.

**Clone** duplicates a subscription with its transforms and naming settings
under a new name and the next free numeric prefix, which is handy for keeping a
known-good copy before experimenting.

## Profile bundles

The Dashboard can export the whole profile to `exports/<profile>-<stamp>.tar.gz`
and import a bundle from `imports/*.tar.gz` as a new profile under
`profiles/<name>`.

- **Export** excludes `config/secrets/local.yaml` unless *Include secrets* is
  enabled; `.bak`, `.trash` and caches are always skipped.
- The bundle contains a `manifest.json` with the profile name, timestamp and the
  file list.
- **Import** rejects absolute paths and `..` members, requires
  `config/pipeline.yaml`, validates the extracted tree with `load_config` and
  removes it again if validation fails.
- Imported profiles appear in the Dashboard profile switcher immediately.

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

- apply a transform/naming template to many sources at once;
- editing rule-set references directly from the category form.
