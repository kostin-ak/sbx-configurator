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
    TabbedContent,
    TabPane,
    TextArea,
)

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from . import routing as routing_helpers
from . import rules as rule_helpers
from . import transforms as transform_helpers
from . import yamltree
from .profiles import list_profiles
from .services import SBXCTL_ACTIONS, SourcePreview, artifact_info, list_imports, read_logs
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


class DeviceModal(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, store: ConfigStore, name: str | None = None) -> None:
        super().__init__()
        self.store = store
        self.name = name

    def compose(self) -> ComposeResult:
        device = {}
        if self.name:
            device = routing_helpers.devices(self.store).get(self.name, {}) or {}
        with Container(classes="modal"):
            yield Static("Device", classes="modal-title")
            yield Label("Name")
            yield Input(value=self.name or "", id="name")
            yield Label("IPv4 (a.b.c.d/32)")
            yield Input(value=str(device.get("ipv4", "")), id="ipv4")
            yield Label("IPv6 (optional)")
            yield Input(value=str(device.get("ipv6", "")), id="ipv6")
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
        if self.name and self.name != name:
            routing_helpers.remove_device(self.store, self.name)
        try:
            routing_helpers.upsert_device(
                self.store,
                name,
                self.query_one("#ipv4", Input).value.strip(),
                self.query_one("#ipv6", Input).value.strip(),
            )
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=8)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class GroupModal(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, store: ConfigStore, name: str | None = None) -> None:
        super().__init__()
        self.store = store
        self.name = name

    def compose(self) -> ComposeResult:
        members = ""
        if self.name:
            entry = routing_helpers.groups(self.store).get(self.name, {}) or {}
            members = ", ".join(entry.get("members", []) or [])
        known = ", ".join(sorted(routing_helpers.devices(self.store).keys()))
        with Container(classes="modal wide"):
            yield Static("Group", classes="modal-title")
            yield Label("Name")
            yield Input(value=self.name or "", id="name")
            yield Label(f"Members (comma separated) — devices: {known}")
            yield Input(value=members, id="members")
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
        members = [item.strip() for item in self.query_one("#members", Input).value.split(",") if item.strip()]
        if self.name and self.name != name:
            routing_helpers.remove_group(self.store, self.name)
        try:
            routing_helpers.upsert_group(self.store, name, members)
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=8)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class PolicyModal(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, store: ConfigStore, alias: str | None = None) -> None:
        super().__init__()
        self.store = store
        self.alias = alias

    def compose(self) -> ComposeResult:
        categories = ""
        if self.alias:
            for item in routing_helpers.policies(self.store):
                if isinstance(item, dict) and item.get("alias") == self.alias:
                    categories = ", ".join(item.get("categories", []) or [])
                    break
        available = ", ".join(routing_helpers.category_names(self.store))
        with Container(classes="modal wide"):
            yield Static("Policy", classes="modal-title")
            yield Label("Alias (device or group name)")
            yield Input(value=self.alias or "", id="alias")
            yield Label(f"Categories (comma separated) — available: {available}")
            yield Input(value=categories, id="categories")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save":
            self.dismiss(False)
            return
        alias = self.query_one("#alias", Input).value.strip()
        if not alias:
            self.app.notify("alias is required", severity="error")
            return
        categories = [item.strip() for item in self.query_one("#categories", Input).value.split(",") if item.strip()]
        if self.alias and self.alias != alias:
            routing_helpers.remove_policy(self.store, self.alias)
        try:
            routing_helpers.upsert_policy(self.store, alias, categories)
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=10)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class TransformModal(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, store: ConfigStore, document: Document, index: int | None = None) -> None:
        super().__init__()
        self.store = store
        self.document = document
        self.index = index

    def compose(self) -> ComposeResult:
        entry = {}
        items = self.document.data.get("transforms") or []
        if self.index is not None and 0 <= self.index < len(items):
            entry = items[self.index]
        params = ""
        if entry.get("params"):
            import yaml as pyyaml

            params = pyyaml.safe_dump(entry.get("params"), allow_unicode=True, sort_keys=False)
        with Container(classes="modal wide"):
            yield Static("Transform", classes="modal-title")
            yield Label("Action")
            yield Select(
                [("rename", "rename"), ("exclude", "exclude"), ("patch", "patch"), ("random_patch", "random_patch")],
                value=str(entry.get("action", "rename")),
                id="action",
            )
            yield Label("Pattern (regex)")
            yield Input(value=str(entry.get("pattern", "")), id="pattern")
            yield Label("Replacement (rename)")
            yield Input(value=str(entry.get("replacement", "")), id="replacement")
            yield Label("Params (YAML, for patch/random_patch)")
            yield TextArea(params, id="params")
            yield Label("Stop after this rule")
            yield Switch(value=bool(entry.get("stop", False)), id="stop")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save":
            self.dismiss(False)
            return
        action = str(self.query_one("#action", Select).value)
        pattern = self.query_one("#pattern", Input).value
        replacement = self.query_one("#replacement", Input).value
        try:
            params = transform_helpers.parse_params(self.query_one("#params", TextArea).text)
            transform_helpers.upsert_transform(
                self.store,
                self.document,
                self.index,
                action,
                pattern,
                replacement,
                params,
                bool(self.query_one("#stop", Switch).value),
            )
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=10)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class TransformsModal(ModalScreen[bool]):
    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, store: ConfigStore, document: Document) -> None:
        super().__init__()
        self.store = store
        self.document = document

    def compose(self) -> ComposeResult:
        with Container(classes="modal wide"):
            yield Static(str(self.document.data.get("metadata", {}).get("name", "subscription")), classes="modal-title")
            yield DataTable(id="transforms-table", cursor_type="row")
            with Horizontal(classes="modal-buttons"):
                yield Button("Add", id="transform-add", variant="primary")
                yield Button("Edit", id="transform-edit")
                yield Button("Up", id="transform-up")
                yield Button("Down", id="transform-down")
                yield Button("Delete", id="transform-delete", variant="error")
                yield Button("Close", id="transform-close")

    def on_mount(self) -> None:
        table = self.query_one("#transforms-table", DataTable)
        table.add_columns("Action", "Pattern", "Extra")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#transforms-table", DataTable)
        table.clear()
        for entry in transform_helpers.transforms(self.document):
            extra = entry.get("replacement") or entry.get("params") or ""
            table.add_row(str(entry.get("action", "")), str(entry.get("pattern", ""))[:60], str(extra)[:60])

    def _index(self) -> int | None:
        table = self.query_one("#transforms-table", DataTable)
        return table.cursor_row if table.row_count else None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        identifier = event.button.id
        if identifier == "transform-close":
            self.dismiss(True)
            return
        if identifier == "transform-add":
            self.app.push_screen(TransformModal(self.store, self.document), self._saved)
            return
        index = self._index()
        if index is None:
            self.app.notify("select a transform first", severity="warning")
            return
        if identifier == "transform-edit":
            self.app.push_screen(TransformModal(self.store, self.document, index), self._saved)
        elif identifier == "transform-delete":
            try:
                transform_helpers.remove_transform(self.store, self.document, index)
            except Exception as error:  # noqa: BLE001
                self.app.notify(str(error), severity="error", timeout=8)
                return
            self.refresh_rows()
        elif identifier in {"transform-up", "transform-down"}:
            delta = -1 if identifier == "transform-up" else 1
            try:
                transform_helpers.move_transform(self.store, self.document, index, delta)
            except Exception as error:  # noqa: BLE001
                self.app.notify(str(error), severity="error", timeout=8)
                return
            self.refresh_rows()

    def _saved(self, saved: bool | None) -> None:
        if saved:
            self.refresh_rows()


class CategoryModal(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, store: ConfigStore, name: str | None = None) -> None:
        super().__init__()
        self.store = store
        self.name = name

    def compose(self) -> ComposeResult:
        entry = {}
        if self.name:
            for item in rule_helpers.categories(self.store):
                if isinstance(item, dict) and item.get("name") == self.name:
                    entry = item
                    break
        rules_text = ""
        if entry.get("rules"):
            import yaml as pyyaml

            rules_text = pyyaml.safe_dump(list(entry["rules"]), allow_unicode=True, sort_keys=False)
        with Container(classes="modal wide"):
            yield Static("Category", classes="modal-title")
            yield Label("Name")
            yield Input(value=str(entry.get("name", "")), id="name")
            yield Label("Display")
            yield Input(value=str(entry.get("display", "")), id="display")
            yield Label("Rules (YAML list)")
            yield TextArea(rules_text, language="yaml", id="rules")
            yield Label("Disable default rules")
            yield Switch(value=bool(entry.get("disable_default", False)), id="disable-default")
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
        try:
            rules = rule_helpers.parse_rules(self.query_one("#rules", TextArea).text)
            rule_helpers.upsert_category(
                self.store,
                self.name,
                name,
                self.query_one("#display", Input).value.strip(),
                rules,
                bool(self.query_one("#disable-default", Switch).value),
            )
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=10)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class RuleSetModal(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, store: ConfigStore, tag: str | None = None) -> None:
        super().__init__()
        self.store = store
        self.tag = tag

    def compose(self) -> ComposeResult:
        entry = {}
        if self.tag:
            for item in rule_helpers.rule_sets(self.store):
                if isinstance(item, dict) and item.get("tag") == self.tag:
                    entry = item
                    break
        with Container(classes="modal wide"):
            yield Static("Rule set", classes="modal-title")
            yield Label("Tag")
            yield Input(value=str(entry.get("tag", "")), id="tag")
            yield Label("Type")
            yield Select([("remote", "remote"), ("local", "local")], value=str(entry.get("type", "remote")), id="type")
            yield Label("Format")
            yield Select([("binary", "binary"), ("source", "source")], value=str(entry.get("format", "binary")), id="format")
            yield Label("URL")
            yield Input(value=str(entry.get("url", "")), id="url")
            yield Label("Download detour")
            yield Input(value=str(entry.get("download_detour", "direct")), id="detour")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save":
            self.dismiss(False)
            return
        tag = self.query_one("#tag", Input).value.strip()
        if not tag:
            self.app.notify("tag is required", severity="error")
            return
        try:
            rule_helpers.upsert_rule_set(
                self.store,
                self.tag,
                tag,
                str(self.query_one("#type", Select).value),
                str(self.query_one("#format", Select).value),
                self.query_one("#url", Input).value.strip(),
                self.query_one("#detour", Input).value.strip(),
            )
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=10)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ImportModal(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self.store = store

    def compose(self) -> ComposeResult:
        files = list_imports(self.store.profile)
        options = [(path.name, str(path)) for path in files]
        with Container(classes="modal"):
            yield Static("Import subscription", classes="modal-title")
            if not options:
                yield Static(f"Put a subscription YAML into {self.store.profile.config_dir / 'imports'}")
            else:
                yield Select(options, id="import-file")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                if options:
                    yield Button("Import", id="import", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "import":
            self.dismiss(False)
            return
        value = self.query_one("#import-file", Select).value
        if value in (None, Select.BLANK):
            self.dismiss(False)
            return
        self.dismiss(str(value))

    def action_cancel(self) -> None:
        self.dismiss(False)


class TextValueModal(ModalScreen[str]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        self.title_text = title
        self.text = text

    def compose(self) -> ComposeResult:
        with Container(classes="modal wide"):
            yield Static(self.title_text, classes="modal-title")
            yield TextArea(self.text, language="yaml", id="value")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save":
            self.dismiss(None)
            return
        self.dismiss(self.query_one("#value", TextArea).text)

    def action_cancel(self) -> None:
        self.dismiss(None)


class KeyValueModal(ModalScreen[tuple]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title_text = title

    def compose(self) -> ComposeResult:
        with Container(classes="modal wide"):
            yield Static(self.title_text, classes="modal-title")
            yield Label("Key")
            yield Input(id="key")
            yield Label("Value (YAML)")
            yield TextArea("", language="yaml", id="value")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save":
            self.dismiss(None)
            return
        key = self.query_one("#key", Input).value.strip()
        if not key:
            self.app.notify("key is required", severity="error")
            return
        self.dismiss((key, self.query_one("#value", TextArea).text))

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------- panes


class DashboardPane(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="actions"):
            yield Select([], id="profile-select", prompt="Profile")
            yield Button("Lint", id="dashboard-lint")
        yield Static("", id="dashboard-summary")
        with Horizontal(classes="actions"):
            yield Button("Build", id="build", variant="primary")
            yield Button("Deploy", id="deploy")
            yield Button("Reload", id="reload")
        yield RichLog(id="dashboard-log", highlight=True, markup=True)

    def on_mount(self) -> None:
        self.refresh_profile_select()
        self.refresh_summary()

    def refresh_profile_select(self) -> None:
        select = self.query_one("#profile-select", Select)
        options = [(profile.name, profile.name) for profile in list_profiles(self.app.root)]
        select.set_options(options)
        select.value = self.app.profile.name

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "profile-select":
            return
        value = event.value
        if value in (None, Select.BLANK):
            return
        self.app.switch_profile(str(value))

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
        elif event.button.id == "dashboard-lint":
            self.app.action_lint()
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
            yield Button("Transforms", id="source-transforms")
            yield Button("Names", id="source-names")
            yield Button("Export", id="source-export")
            yield Button("Import", id="source-import")
            yield Button("All on", id="source-all-on")
            yield Button("All off", id="source-all-off")

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
        if identifier in {"source-all-on", "source-all-off"}:
            enabled = identifier == "source-all-on"
            self.app.push_screen(
                ConfirmModal(f"{'Enable' if enabled else 'Disable'} every subscription?"),
                lambda ok: self.app.set_all_sources(enabled) if ok else None,
            )
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
        elif identifier == "source-transforms":
            self.app.push_screen(TransformsModal(self.app.store, document), lambda _: self.app.reload_config())
        elif identifier == "source-names":
            self.app.preview_names(str(document.data.get("metadata", {}).get("name", "")))
        elif identifier == "source-export":
            self.app.export_source(str(document.data.get("metadata", {}).get("name", "")))
        elif identifier == "source-import":
            self.app.push_screen(ImportModal(self.app.store), self._imported)

    def _imported(self, path: str | None) -> None:
        if path:
            self.app.import_source(path)

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
        with TabbedContent():
            with TabPane("Devices", id="tab-devices"):
                yield DataTable(id="devices-table", cursor_type="row")
                with Horizontal(classes="actions"):
                    yield Button("Add", id="device-add", variant="primary")
                    yield Button("Edit", id="device-edit")
                    yield Button("Delete", id="device-delete", variant="error")
            with TabPane("Groups", id="tab-groups"):
                yield DataTable(id="groups-table", cursor_type="row")
                with Horizontal(classes="actions"):
                    yield Button("Add", id="group-add", variant="primary")
                    yield Button("Edit", id="group-edit")
                    yield Button("Delete", id="group-delete", variant="error")
            with TabPane("Policies", id="tab-policies"):
                yield DataTable(id="policies-table", cursor_type="row")
                with Horizontal(classes="actions"):
                    yield Button("Add", id="policy-add", variant="primary")
                    yield Button("Edit", id="policy-edit")
                    yield Button("Delete", id="policy-delete", variant="error")
                yield Static("", id="routing-hint")

    def on_mount(self) -> None:
        self.query_one("#devices-table", DataTable).add_columns("Name", "IPv4", "IPv6")
        self.query_one("#groups-table", DataTable).add_columns("Name", "Members")
        self.query_one("#policies-table", DataTable).add_columns("Alias", "Categories")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        devices = self.query_one("#devices-table", DataTable)
        devices.clear()
        groups = self.query_one("#groups-table", DataTable)
        groups.clear()
        policies = self.query_one("#policies-table", DataTable)
        policies.clear()
        store = self.app.store
        try:
            for name, entry in routing_helpers.devices(store).items():
                item = entry if isinstance(entry, dict) else {}
                devices.add_row(str(name), str(item.get("ipv4", "")), str(item.get("ipv6", "")), key=str(name))
            for name, entry in routing_helpers.groups(store).items():
                item = entry if isinstance(entry, dict) else {}
                groups.add_row(str(name), ", ".join(item.get("members", []) or []), key=str(name))
            for policy in routing_helpers.policies(store):
                if isinstance(policy, dict):
                    policies.add_row(
                        str(policy.get("alias", "?")),
                        ", ".join(policy.get("categories", []) or []),
                        key=str(policy.get("alias", "")),
                    )
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error")
        self.query_one("#routing-hint", Static).update(
            "Policies map a device or group alias to categories. "
            "Available categories: " + ", ".join(routing_helpers.category_names(store))
        )

    def _selected(self, table_id: str) -> str | None:
        table = self.query_one(f"#{table_id}", DataTable)
        if table.row_count == 0:
            return None
        key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
        return str(key) if key is not None else None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        identifier = event.button.id or ""
        kind, _, action = identifier.partition("-")
        if action == "add":
            modal = {"device": DeviceModal, "group": GroupModal, "policy": PolicyModal}[kind]
            self.app.push_screen(modal(self.app.store), self._saved)
            return
        table_id = {"device": "devices-table", "group": "groups-table", "policy": "policies-table"}[kind]
        name = self._selected(table_id)
        if not name:
            self.app.notify(f"select a {kind} first", severity="warning")
            return
        if action == "edit":
            modal = {"device": DeviceModal, "group": GroupModal, "policy": PolicyModal}[kind]
            self.app.push_screen(modal(self.app.store, name), self._saved)
        elif action == "delete":
            self.app.push_screen(ConfirmModal(f"Delete {kind} {name}?"), lambda ok: self._delete(kind, name) if ok else None)

    def _delete(self, kind: str, name: str) -> None:
        try:
            if kind == "device":
                routing_helpers.remove_device(self.app.store, name)
            elif kind == "group":
                routing_helpers.remove_group(self.app.store, name)
            else:
                routing_helpers.remove_policy(self.app.store, name)
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=8)
            return
        self.refresh_rows()
        self.app.reload_config()

    def _saved(self, saved: bool | None) -> None:
        if saved:
            self.refresh_rows()
            self.app.reload_config()


class RulesPane(Vertical):
    def compose(self) -> ComposeResult:
        with TabbedContent():
            with TabPane("Categories", id="tab-categories"):
                yield DataTable(id="categories-table", cursor_type="row")
                with Horizontal(classes="actions"):
                    yield Button("Add", id="category-add", variant="primary")
                    yield Button("Edit", id="category-edit")
                    yield Button("Delete", id="category-delete", variant="error")
            with TabPane("Rule sets", id="tab-rulesets"):
                yield DataTable(id="rulesets-table", cursor_type="row")
                with Horizontal(classes="actions"):
                    yield Button("Add", id="ruleset-add", variant="primary")
                    yield Button("Edit", id="ruleset-edit")
                    yield Button("Delete", id="ruleset-delete", variant="error")

    def on_mount(self) -> None:
        self.query_one("#categories-table", DataTable).add_columns("Name", "Display", "Rules", "Rule sets")
        self.query_one("#rulesets-table", DataTable).add_columns("Tag", "Type", "Format", "URL")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        categories = self.query_one("#categories-table", DataTable)
        categories.clear()
        rulesets = self.query_one("#rulesets-table", DataTable)
        rulesets.clear()
        store = self.app.store
        try:
            for entry in rule_helpers.categories(store):
                if not isinstance(entry, dict):
                    continue
                categories.add_row(
                    str(entry.get("name", "")),
                    str(entry.get("display", "")),
                    str(len(entry.get("rules", []) or [])),
                    ", ".join(rule_helpers.category_rule_sets(entry))[:70],
                    key=str(entry.get("name", "")),
                )
            for entry in rule_helpers.rule_sets(store):
                if not isinstance(entry, dict):
                    continue
                rulesets.add_row(
                    str(entry.get("tag", "")),
                    str(entry.get("type", "")),
                    str(entry.get("format", "")),
                    str(entry.get("url", ""))[:70],
                    key=str(entry.get("tag", "")),
                )
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error")

    def _selected(self, table_id: str) -> str | None:
        table = self.query_one(f"#{table_id}", DataTable)
        if table.row_count == 0:
            return None
        key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
        return str(key) if key is not None else None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        identifier = event.button.id or ""
        kind, _, action = identifier.partition("-")
        if action == "add":
            modal = {"category": CategoryModal, "ruleset": RuleSetModal}[kind]
            self.app.push_screen(modal(self.app.store), self._saved)
            return
        table_id = {"category": "categories-table", "ruleset": "rulesets-table"}[kind]
        name = self._selected(table_id)
        if not name:
            self.app.notify(f"select a {kind} first", severity="warning")
            return
        if action == "edit":
            modal = {"category": CategoryModal, "ruleset": RuleSetModal}[kind]
            self.app.push_screen(modal(self.app.store, name), self._saved)
        elif action == "delete":
            self.app.push_screen(ConfirmModal(f"Delete {kind} {name}?"), lambda ok: self._delete(kind, name) if ok else None)

    def _delete(self, kind: str, name: str) -> None:
        try:
            if kind == "category":
                rule_helpers.remove_category(self.app.store, name)
            else:
                rule_helpers.remove_rule_set(self.app.store, name)
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=8)
            return
        self.refresh_rows()
        self.app.reload_config()

    def _saved(self, saved: bool | None) -> None:
        if saved:
            self.refresh_rows()
            self.app.reload_config()


class SelectorsPane(Vertical):
    def compose(self) -> ComposeResult:
        yield DataTable(id="selectors-table", cursor_type="row")
        with Horizontal(classes="actions"):
            yield Button("Add", id="selector-add", variant="primary")
            yield Button("Edit", id="selector-edit")
            yield Button("Delete", id="selector-delete", variant="error")
            yield Button("Preview", id="selector-preview")

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
        if identifier == "selector-preview":
            document = self.app.store.selectors()
            entry = document.data["templates"][index]
            self.app.preview_selector(str(entry.get("filter", ".*")), str(entry.get("prefer", "")))
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
            yield Button("Open in vim", id="yaml-vim")
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
        elif event.button.id == "yaml-vim":
            self.app.open_in_editor(path)
        elif event.button.id == "yaml-save":
            text = self.query_one("#yaml-editor", TextArea).text
            try:
                self.app.store.save_text(path, text)
            except Exception as error:  # noqa: BLE001
                self.app.notify(str(error), severity="error", timeout=10)
                return
            self.app.notify(f"saved {path.name}")
            self.app.reload_config()


class VisualPane(Vertical):
    def __init__(self) -> None:
        super().__init__()
        self._document: Document | None = None
        self._rows: list[yamltree.Node] = []
        self._pending: yamltree.Node | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="actions"):
            yield Select([], id="visual-file", prompt="Select file")
            yield Button("Load", id="visual-load")
            yield Button("Edit", id="visual-edit", variant="primary")
            yield Button("Add key", id="visual-add-key")
            yield Button("Add item", id="visual-add-item")
            yield Button("Delete", id="visual-delete", variant="error")
            yield Button("Reload", id="visual-reload")
        yield DataTable(id="visual-table", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one("#visual-table", DataTable)
        table.add_columns("Path", "Type", "Value")
        self.refresh_files()

    def refresh_files(self) -> None:
        select = self.query_one("#visual-file", Select)
        options = [(self.app.store.relative(path), str(path)) for path in self.app.store.files()]
        select.set_options(options)

    def current_path(self) -> Path | None:
        select = self.query_one("#visual-file", Select)
        if select.value in (None, Select.BLANK):
            return None
        return Path(str(select.value))

    def load_file(self, path: Path) -> None:
        try:
            document = self.app.store.load(path)
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error")
            return
        self._document = document
        self._rows = yamltree.flatten(document.data)
        table = self.query_one("#visual-table", DataTable)
        table.clear()
        for index, node in enumerate(self._rows):
            table.add_row(node.label, node.kind, node.preview, key=str(index))
        select = self.query_one("#visual-file", Select)
        select.value = str(path)

    def selected(self) -> yamltree.Node | None:
        table = self.query_one("#visual-table", DataTable)
        if table.row_count == 0:
            return None
        key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
        try:
            return self._rows[int(str(key))]
        except (ValueError, IndexError):
            return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        identifier = event.button.id
        if identifier == "visual-reload":
            self.refresh_files()
            return
        path = self.current_path()
        if path is None:
            self.app.notify("select a file first", severity="warning")
            return
        if identifier == "visual-load":
            self.load_file(path)
            return
        node = self.selected()
        if node is None:
            self.app.notify("select a row first", severity="warning")
            return
        self._pending = node
        if identifier == "visual-edit":
            value = self._document.data if not node.path else yamltree.get(self._document.data, node.path)
            self.app.push_screen(TextValueModal(f"Edit {node.label}", yamltree.dump_value(value)), self._apply_edit)
        elif identifier == "visual-add-key":
            self.app.push_screen(KeyValueModal(f"Add key to {node.label}"), self._apply_add_key)
        elif identifier == "visual-add-item":
            self.app.push_screen(TextValueModal(f"Add item to {node.label}", ""), self._apply_add_item)
        elif identifier == "visual-delete":
            if not node.path:
                self.app.notify("the root cannot be removed", severity="warning")
                return
            self.app.push_screen(ConfirmModal(f"Delete {node.label}?"), self._apply_delete)

    def _apply_edit(self, text: str | None) -> None:
        if text is None or self._pending is None or self._document is None:
            return
        try:
            value = yamltree.parse_value(text)
            if not self._pending.path:
                if not isinstance(value, dict):
                    raise ValueError("the root must be a mapping")
                self._document.data = value
            else:
                yamltree.set_value(self._document.data, self._pending.path, value)
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=10)
            return
        self._save()

    def _apply_add_key(self, result: tuple | None) -> None:
        if not result or self._pending is None or self._document is None:
            return
        key, text = result
        try:
            yamltree.add_key(self._document.data, self._pending.path, key, yamltree.parse_value(text))
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=10)
            return
        self._save()

    def _apply_add_item(self, text: str | None) -> None:
        if text is None or self._pending is None or self._document is None:
            return
        try:
            yamltree.append_item(self._document.data, self._pending.path, yamltree.parse_value(text))
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=10)
            return
        self._save()

    def _apply_delete(self, confirmed: bool | None) -> None:
        if not confirmed or self._pending is None or self._document is None:
            return
        try:
            yamltree.delete(self._document.data, self._pending.path)
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=10)
            return
        self._save()

    def _save(self) -> None:
        assert self._document is not None
        try:
            self.app.store.save(self._document)
        except Exception as error:  # noqa: BLE001
            self.app.notify(str(error), severity="error", timeout=10)
            return
        self.load_file(self._document.path)
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
            yield Select([(action, action) for action in SBXCTL_ACTIONS], value="status", id="sbxctl-action")
            yield Button("Run sbxctl", id="sbxctl-run")
        with Horizontal(classes="actions"):
            yield Button("Deploy artifact", id="deploy-run", variant="primary")
            yield Button("Router logs", id="deploy-logs")
        yield RichLog(id="deploy-log", highlight=True, markup=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        host = self.query_one("#deploy-host", Input).value.strip()
        password = self.query_one("#deploy-password", Input).value
        if event.button.id == "deploy-run":
            restart = bool(self.query_one("#deploy-restart", Switch).value)
            self.app.deploy(host, password, restart)
        elif event.button.id == "deploy-logs":
            self.app.fetch_remote_logs(host, password)
        elif event.button.id == "sbxctl-run":
            action = str(self.query_one("#sbxctl-action", Select).value)
            self.app.run_sbxctl(host, password, action)
