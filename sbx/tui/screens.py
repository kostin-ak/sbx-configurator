"""Textual screens and modal dialogs for the sbx TUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    Switch,
    TextArea,
)

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .services import SourcePreview, artifact_info, read_logs
from .store import ConfigStore, Document, coerce, mask


def _slug(text: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in text)
    return "-".join(part for part in cleaned.split("-") if part) or "source"


# --------------------------------------------------------------------------- modals


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Container(classes="modal"):
            yield Static(self.question, classes="modal-title")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Confirm", id="confirm", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class InfoModal(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close"), ("enter", "close", "Close")]

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        with Container(classes="modal wide"):
            yield Static("Details", classes="modal-title")
            with VerticalScroll(classes="modal-body"):
                yield Static(self.text, markup=False)
            with Horizontal(classes="modal-buttons"):
                yield Button("Close", id="close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class SubscriptionModal(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, store: ConfigStore, document: Document | None = None) -> None:
        super().__init__()
        self.store = store
        self.document = document

    def compose(self) -> ComposeResult:
        data = self.document.data if self.document else {}
        metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
        fetch = data.get("fetch", {}) if isinstance(data, dict) else {}
        folder = fetch.get("folder", {}) if isinstance(fetch, dict) else {}
        with Container(classes="modal wide"):
            yield Static("Subscription", classes="modal-title")
            with VerticalScroll(classes="modal-body"):
                yield Label("Name")
                yield Input(value=str(metadata.get("name", "")), id="name")
                yield Label("Enabled")
                yield Switch(value=bool(metadata.get("enabled", True)), id="enabled")
                yield Label("URL")
                yield Input(value=str(fetch.get("url", "")), id="url", placeholder="https://…")
                yield Label("File")
                yield Input(value=str(fetch.get("file", "")), id="file", placeholder="/etc/sing-box/configs/…")
                yield Label("Folder")
                yield Input(value=str(folder.get("path", "")), id="folder", placeholder="${secret:keys.links}")
                yield Label("Folder parser")
                yield Input(value=str(folder.get("parser", "auto")), id="parser")
                yield Label("Detour (optional)")
                yield Input(value=str(folder.get("detour", "")), id="detour")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save":
            self.dismiss(False)
            return
        name = self.query_one("#name", Input).value.strip()
        if not name:
            self.app.notify("name is required", severity="error")
            return
        data = self.document.data if self.document else CommentedMap()
        if not isinstance(data, dict):
            data = CommentedMap()
        data.setdefault("apiVersion", "sbx.shtorm/1")
        data["kind"] = "Subscription"
        metadata = data.get("metadata")
        if not isinstance(metadata, dict):
            metadata = CommentedMap()
            data["metadata"] = metadata
        metadata["name"] = name
        metadata["enabled"] = bool(self.query_one("#enabled", Switch).value)
        fetch = data.get("fetch")
        if not isinstance(fetch, dict):
            fetch = CommentedMap()
            data["fetch"] = fetch
        for key in ("url", "file"):
            value = self.query_one(f"#{key}", Input).value.strip()
            if value:
                fetch[key] = value
            else:
                fetch.pop(key, None)
        folder_path = self.query_one("#folder", Input).value.strip()
        if folder_path:
            folder = fetch.get("folder")
            if not isinstance(folder, dict):
                folder = CommentedMap()
                fetch["folder"] = folder
            folder["path"] = folder_path
            parser = self.query_one("#parser", Input).value.strip() or "auto"
            folder["parser"] = parser
            detour = self.query_one("#detour", Input).value.strip()
            if detour:
                folder["detour"] = detour
            else:
                folder.pop("detour", None)
        else:
            fetch.pop("folder", None)
        try:
            if self.document:
                self.store.save(self.document)
            else:
                target = self.store.profile.subscriptions_dir / f"{_next_prefix(self.store)}-{_slug(name)}.yaml"
                self.store.create(target, data)
        except Exception as error:  # noqa: BLE001 - show in UI
            self.app.notify(str(error), severity="error", timeout=8)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class SelectorModal(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, store: ConfigStore, index: int | None = None) -> None:
        super().__init__()
        self.store = store
        self.index = index

    def _entry(self) -> dict[str, Any]:
        document = self.store.selectors()
        templates = document.data.setdefault("templates", CommentedSeq())
        if self.index is None:
            return CommentedMap()
        return templates[self.index]

    def compose(self) -> ComposeResult:
        entry = self._entry()
        with Container(classes="modal wide"):
            yield Static("Selector", classes="modal-title")
            with VerticalScroll(classes="modal-body"):
                yield Label("Name")
                yield Input(value=str(entry.get("name", "")), id="name")
                yield Label("Tag")
                yield Input(value=str(entry.get("tag", "")), id="tag")
                yield Label("Type")
                yield Input(value=str(entry.get("type", "selector")), id="type")
                yield Label("Filter (regex)")
                yield Input(value=str(entry.get("filter", "")), id="filter")
                yield Label("Prefer (regex, optional)")
                yield Input(value=str(entry.get("prefer", "")), id="prefer")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save":
            self.dismiss(False)
            return
        document = self.store.selectors()
        templates = document.data.setdefault("templates", CommentedSeq())
        entry = CommentedMap()
        entry["name"] = self.query_one("#name", Input).value.strip()
        entry["tag"] = self.query_one("#tag", Input).value.strip()
        entry["type"] = self.query_one("#type", Input).value.strip() or "selector"
        filter_value = self.query_one("#filter", Input).value.strip()
        if filter_value:
            entry["filter"] = filter_value
        prefer = self.query_one("#prefer", Input).value.strip()
        if prefer:
            entry["prefer"] = prefer
        if not entry["name"] or not entry["tag"]:
            self.app.notify("name and tag are required", severity="error")
            return
        if self.index is None:
            templates.append(entry)
        else:
            templates[self.index] = entry
        try:
            self.store.save(document)
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=8)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ValueModal(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, store: ConfigStore, path: tuple[str, ...], value: Any) -> None:
        super().__init__()
        self.store = store
        self.path = path
        self.value = value

    def compose(self) -> ComposeResult:
        with Container(classes="modal"):
            yield Static(".".join(self.path), classes="modal-title")
            yield Label("Value")
            yield Input(value=str(self.value if self.value is not None else ""), id="value")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save":
            self.dismiss(False)
            return
        document = self.store.secrets()
        if document is None:
            document = self.store.create(self.store.profile.secrets, CommentedMap())
        current = document.data
        for part in self.path[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = CommentedMap()
            current = current[part]
        current[self.path[-1]] = coerce(self.query_one("#value", Input).value)
        try:
            self.store.save(document)
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=8)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


def _next_prefix(store: ConfigStore) -> str:
    numbers = []
    for path in store.profile.subscriptions_dir.glob("*.yaml"):
        prefix = path.name.split("-", 1)[0]
        if prefix.isdigit():
            numbers.append(int(prefix))
    return f"{(max(numbers) + 10) if numbers else 10:02d}"


# ---------------------------------------------------------------------------- panes


class DashboardPane(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("", id="dashboard-summary")
        with Horizontal(classes="actions"):
            yield Button("Build", id="build", variant="primary")
            yield Button("Deploy", id="deploy")
            yield Button("Reload", id="reload")
        yield RichLog(id="dashboard-log", highlight=True, markup=True)

    def on_mount(self) -> None:
        self.refresh_summary()

    def refresh_summary(self) -> None:
        app = self.app
        profile = app.store.profile
        info = artifact_info(profile)
        lines = [
            f"Profile: [b]{profile.name}[/b]  ({profile.root})",
            f"Config: {profile.config_dir}",
            f"Pipeline: {profile.pipeline.name}",
            f"Artifact: {'yes' if info.get('exists') else 'no'}",
        ]
        if info.get("exists"):
            lines.append(f"SHA256: {info['sha256'][:16]}…  size: {info['size']} bytes")
        try:
            loaded = app.services_load()
            lines.append(
                f"Subscriptions: {loaded.stats['subscriptions']}  "
                f"native outbounds: {loaded.stats['native_outbounds']}  "
                f"endpoints: {loaded.stats['native_endpoints']}"
            )
        except Exception as error:  # noqa: BLE001
            lines.append(f"[red]config error: {error}[/red]")
        self.query_one("#dashboard-summary", Static).update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "build":
            self.app.action_build()
        elif event.button.id == "deploy":
            self.app.action_open_tab("deploy")
        elif event.button.id == "reload":
            self.app.reload_config()


class SourcesPane(Vertical):
    def compose(self) -> ComposeResult:
        yield DataTable(id="sources-table", cursor_type="row")
        with Horizontal(classes="actions"):
            yield Button("Add", id="source-add", variant="primary")
            yield Button("Edit", id="source-edit")
            yield Button("Toggle", id="source-toggle")
            yield Button("Delete", id="source-delete", variant="error")
            yield Button("Preview", id="source-preview")
            yield Button("Fetch", id="source-fetch")

    def on_mount(self) -> None:
        table = self.query_one("#sources-table", DataTable)
        table.add_columns("File", "Name", "Enabled", "Kind", "Value")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#sources-table", DataTable)
        table.clear()
        for document in self.app.store.subscriptions():
            data = document.data
            metadata = data.get("metadata", {})
            fetch = data.get("fetch", {})
            kind = "url" if fetch.get("url") else "file" if fetch.get("file") else "folder" if fetch.get("folder") else "?"
            value = str(fetch.get("url") or fetch.get("file") or (fetch.get("folder") or {}).get("path", ""))
            table.add_row(
                document.path.name,
                str(metadata.get("name", "?")),
                "yes" if metadata.get("enabled", True) else "no",
                kind,
                value,
                key=document.path.name,
            )

    def _selected(self) -> Document | None:
        table = self.query_one("#sources-table", DataTable)
        if table.cursor_row is None or table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
        for document in self.app.store.subscriptions():
            if document.path.name == row_key:
                return document
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        document = self._selected()
        identifier = event.button.id
        if identifier == "source-add":
            self.app.push_screen(SubscriptionModal(self.app.store), self._saved)
            return
        if document is None:
            self.app.notify("select a subscription first", severity="warning")
            return
        if identifier == "source-edit":
            self.app.push_screen(SubscriptionModal(self.app.store, document), self._saved)
        elif identifier == "source-toggle":
            metadata = document.data.setdefault("metadata", CommentedMap())
            metadata["enabled"] = not bool(metadata.get("enabled", True))
            self._save(document)
        elif identifier == "source-delete":
            self.app.push_screen(ConfirmModal(f"Archive {document.path.name}?"), self._delete)
        elif identifier == "source-preview":
            self.app.preview_source(str(document.data.get("metadata", {}).get("name", "")))
        elif identifier == "source-fetch":
            self.app.fetch_source(str(document.data.get("metadata", {}).get("name", "")))

    def _delete(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        document = self._selected()
        if document:
            target = self.app.store.archive(document.path)
            self.app.notify(f"archived to {target.name}")
            self.refresh_rows()
            self.app.reload_config()

    def _save(self, document: Document) -> None:
        try:
            self.app.store.save(document)
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=8)
            return
        self.refresh_rows()
        self.app.reload_config()

    def _saved(self, saved: bool | None) -> None:
        if saved:
            self.refresh_rows()
            self.app.reload_config()


class RoutingPane(Vertical):
    def compose(self) -> ComposeResult:
        yield DataTable(id="routing-table", cursor_type="row")
        with Horizontal(classes="actions"):
            yield Button("Open devices", id="open-devices")
            yield Button("Open groups", id="open-groups")
            yield Button("Open policies", id="open-policies")

    def on_mount(self) -> None:
        table = self.query_one("#routing-table", DataTable)
        table.add_columns("Kind", "Name", "Details")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#routing-table", DataTable)
        table.clear()
        try:
            loaded = self.app.services_load()
            routing = loaded.routing
        except Exception as error:  # noqa: BLE001
            table.add_row("error", str(error)[:80], "")
            return
        for name, item in (routing.get("devices") or {}).items():
            addresses = ", ".join(filter(None, [item.get("ipv4"), item.get("ipv6")])) if isinstance(item, dict) else str(item)
            table.add_row("device", name, addresses)
        for name, item in (routing.get("groups") or {}).items():
            members = ", ".join(item.get("members", []) if isinstance(item, dict) else [])
            table.add_row("group", name, members)
        for policy in routing.get("policies") or []:
            if isinstance(policy, dict):
                table.add_row("policy", str(policy.get("alias", "?")), ", ".join(policy.get("categories", [])))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {
            "open-devices": "devices.yaml",
            "open-groups": "groups.yaml",
            "open-policies": "policies.yaml",
        }
        filename = mapping.get(event.button.id or "")
        if filename:
            self.app.open_yaml(self.app.store.profile.routing_dir / filename)


class SelectorsPane(Vertical):
    def compose(self) -> ComposeResult:
        yield DataTable(id="selectors-table", cursor_type="row")
        with Horizontal(classes="actions"):
            yield Button("Add", id="selector-add", variant="primary")
            yield Button("Edit", id="selector-edit")
            yield Button("Delete", id="selector-delete", variant="error")

    def on_mount(self) -> None:
        table = self.query_one("#selectors-table", DataTable)
        table.add_columns("Name", "Tag", "Type", "Filter", "Prefer")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#selectors-table", DataTable)
        table.clear()
        try:
            document = self.app.store.selectors()
        except Exception as error:  # noqa: BLE001
            table.add_row("error", str(error)[:60], "", "", "")
            return
        for entry in document.data.get("templates", []):
            table.add_row(
                str(entry.get("name", "")),
                str(entry.get("tag", "")),
                str(entry.get("type", "selector")),
                str(entry.get("filter", ""))[:60],
                str(entry.get("prefer", "")),
            )

    def _index(self) -> int | None:
        table = self.query_one("#selectors-table", DataTable)
        return table.cursor_row if table.row_count else None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        identifier = event.button.id
        if identifier == "selector-add":
            self.app.push_screen(SelectorModal(self.app.store), self._saved)
            return
        index = self._index()
        if index is None:
            self.app.notify("select a selector first", severity="warning")
            return
        if identifier == "selector-edit":
            self.app.push_screen(SelectorModal(self.app.store, index), self._saved)
        elif identifier == "selector-delete":
            self.app.push_screen(ConfirmModal("Delete this selector?"), lambda ok: self._delete(index) if ok else None)

    def _delete(self, index: int) -> None:
        document = self.app.store.selectors()
        templates = document.data.get("templates", [])
        if 0 <= index < len(templates):
            templates.pop(index)
            try:
                self.app.store.save(document)
            except Exception as error:  # noqa: BLE001
                self.app.notify(str(error), severity="error", timeout=8)
                return
            self.refresh_rows()
            self.app.reload_config()

    def _saved(self, saved: bool | None) -> None:
        if saved:
            self.refresh_rows()
            self.app.reload_config()


class ProtocolsPane(Vertical):
    def compose(self) -> ComposeResult:
        yield DataTable(id="protocols-table", cursor_type="row")
        with Horizontal(classes="actions"):
            yield Button("Open YAML", id="protocol-open")

    def on_mount(self) -> None:
        table = self.query_one("#protocols-table", DataTable)
        table.add_columns("File", "Name", "Enabled", "Type", "Section")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#protocols-table", DataTable)
        table.clear()
        folder = self.app.store.profile.protocols_dir
        if not folder.is_dir():
            return
        for path in sorted(folder.glob("*.yaml")):
            try:
                document = self.app.store.load(path)
            except Exception:
                continue
            data = document.data
            metadata = data.get("metadata", {})
            protocol = data.get("protocol", {})
            table.add_row(
                path.name,
                str(metadata.get("name", "?")),
                "yes" if metadata.get("enabled", True) else "no",
                str(protocol.get("type", "?")),
                str(protocol.get("section", "?")),
                key=str(path),
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        table = self.query_one("#protocols-table", DataTable)
        if table.row_count == 0:
            return
        key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
        self.app.open_yaml(Path(str(key)))


class SecretsPane(Vertical):
    def compose(self) -> ComposeResult:
        yield DataTable(id="secrets-table", cursor_type="row")
        with Horizontal(classes="actions"):
            yield Button("Edit value", id="secret-edit", variant="primary")
            yield Button("Reveal", id="secret-reveal")

    def on_mount(self) -> None:
        table = self.query_one("#secrets-table", DataTable)
        table.add_columns("Key", "Value")
        self._reveal = False
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#secrets-table", DataTable)
        table.clear()
        for key, value in self.app.store.secrets_entries():
            table.add_row(key, value if self._reveal else mask(value), key=key)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "secret-reveal":
            self._reveal = not self._reveal
            self.refresh_rows()
            return
        table = self.query_one("#secrets-table", DataTable)
        if table.row_count == 0:
            return
        key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
        if key is None:
            return
        path = tuple(str(key).split("."))
        from .store import lookup

        document = self.app.store.secrets()
        value = lookup(document.data, path) if document else ""
        self.app.push_screen(ValueModal(self.app.store, path, value), self._saved)

    def _saved(self, saved: bool | None) -> None:
        if saved:
            self.refresh_rows()


class YamlPane(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="actions"):
            yield Select([], id="yaml-file", prompt="Select file")
            yield Button("Load", id="yaml-load")
            yield Button("Save", id="yaml-save", variant="primary")
            yield Button("Reload", id="yaml-reload")
        yield TextArea("", language="yaml", id="yaml-editor")

    def on_mount(self) -> None:
        self.refresh_files()

    def refresh_files(self) -> None:
        select = self.query_one("#yaml-file", Select)
        options = [(self.app.store.relative(path), str(path)) for path in self.app.store.files()]
        select.set_options(options)

    def current_path(self) -> Path | None:
        select = self.query_one("#yaml-file", Select)
        if select.value is None or select.value == Select.BLANK:
            return None
        return Path(str(select.value))

    def load_file(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error")
            return
        select = self.query_one("#yaml-file", Select)
        select.value = str(path)
        self.query_one("#yaml-editor", TextArea).text = text

    def on_button_pressed(self, event: Button.Pressed) -> None:
        path = self.current_path()
        if event.button.id == "yaml-reload":
            self.refresh_files()
            return
        if path is None:
            self.app.notify("select a file first", severity="warning")
            return
        if event.button.id == "yaml-load":
            self.load_file(path)
        elif event.button.id == "yaml-save":
            text = self.query_one("#yaml-editor", TextArea).text
            try:
                self.app.store.save_text(path, text)
            except Exception as error:  # noqa: BLE001
                self.app.notify(str(error), severity="error", timeout=10)
                return
            self.app.notify(f"saved {path.name}")
            self.app.reload_config()


class BuildPane(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="actions"):
            yield Button("Build & check", id="build-run", variant="primary")
            yield Button("Clear", id="build-clear")
        yield RichLog(id="build-log", highlight=True, markup=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "build-run":
            self.app.action_build()
        elif event.button.id == "build-clear":
            self.query_one("#build-log", RichLog).clear()


class LogsPane(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="actions"):
            yield Button("Refresh", id="logs-refresh")
            yield Select(
                [("all", "all"), ("awg3", "awg3"), ("warp", "warp"), ("links", "links")],
                value="all",
                id="probe-target",
            )
            yield Button("Probe", id="probe-run")
        yield RichLog(id="logs-view", highlight=True, markup=True)

    def on_mount(self) -> None:
        self.refresh_logs()

    def refresh_logs(self) -> None:
        view = self.query_one("#logs-view", RichLog)
        view.clear()
        view.write(read_logs(self.app.store.profile, lines=200))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "logs-refresh":
            self.refresh_logs()
        elif event.button.id == "probe-run":
            target = self.query_one("#probe-target", Select).value
            self.app.run_probe(str(target))


class DeployPane(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Router host")
        yield Input(placeholder="192.168.1.1 or router.home", id="deploy-host")
        yield Label("Password (kept in memory only)")
        yield Input(password=True, id="deploy-password")
        yield Label("Restart after install")
        yield Switch(value=False, id="deploy-restart")
        with Horizontal(classes="actions"):
            yield Button("Deploy artifact", id="deploy-run", variant="primary")
        yield RichLog(id="deploy-log", highlight=True, markup=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "deploy-run":
            host = self.query_one("#deploy-host", Input).value.strip()
            password = self.query_one("#deploy-password", Input).value
            restart = bool(self.query_one("#deploy-restart", Switch).value)
            self.app.deploy(host, password, restart)
