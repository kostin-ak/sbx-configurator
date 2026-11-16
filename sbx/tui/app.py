"""Textual application entry point."""

from __future__ import annotations

import argparse
import sys

from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, TabbedContent, TabPane

from . import services
from .profiles import get_profile, list_profiles, project_root
from .screens import (
    BuildPane,
    DashboardPane,
    DeployPane,
    InfoModal,
    LogsPane,
    ProtocolsPane,
    RoutingPane,
    SecretsPane,
    SelectorsPane,
    SourcesPane,
    YamlPane,
)
from .store import ConfigStore


class SbxTui(App):
    CSS = """
    Screen { background: $surface; }
    .actions { height: auto; padding: 1 0; }
    DataTable { height: 1fr; }
    TextArea { height: 1fr; }
    .modal {
        width: 70; height: auto; padding: 1 2;
        background: $panel; border: round $primary;
    }
    .modal.wide { width: 110; }
    .modal-title { text-style: bold; margin-bottom: 1; }
    .modal-body { height: 24; }
    .modal-buttons { height: auto; align-horizontal: right; padding-top: 1; }
    #dashboard-summary { padding: 1 2; }
    #build-log, #logs-view, #deploy-log, #dashboard-log { height: 1fr; border: round $border; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("b", "build", "Build"),
        ("r", "reload_config", "Reload"),
        ("f1", "help", "Help"),
    ]

    def __init__(self, profile_name: str = "default", root=None) -> None:
        super().__init__()
        self.profile = get_profile(profile_name, root)
        self.store = ConfigStore(self.profile)
        self.title = f"sbx · {self.profile.name}"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent():
            with TabPane("Dashboard", id="dashboard"):
                yield DashboardPane()
            with TabPane("Sources", id="sources"):
                yield SourcesPane()
            with TabPane("Routing", id="routing"):
                yield RoutingPane()
            with TabPane("Selectors", id="selectors"):
                yield SelectorsPane()
            with TabPane("Protocols", id="protocols"):
                yield ProtocolsPane()
            with TabPane("Secrets", id="secrets"):
                yield SecretsPane()
            with TabPane("YAML", id="yaml"):
                yield YamlPane()
            with TabPane("Build", id="build"):
                yield BuildPane()
            with TabPane("Logs & Probe", id="logs"):
                yield LogsPane()
            with TabPane("Deploy", id="deploy"):
                yield DeployPane()
        yield Footer()

    # ------------------------------------------------------------------ helpers
    def services_load(self):
        return services.load_profile(self.profile)

    def _log(self, pane_id: str, message: str) -> None:
        from textual.widgets import RichLog

        try:
            self.query_one(f"#{pane_id}", RichLog).write(message)
        except Exception:
            pass

    def action_open_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def reload_config(self) -> None:
        self.store.reload()
        for pane_type in (DashboardPane, SourcesPane, RoutingPane, SelectorsPane, ProtocolsPane, SecretsPane):
            try:
                pane = self.query_one(pane_type)
            except Exception:
                continue
            for method in ("refresh_summary", "refresh_rows", "refresh_files"):
                callback = getattr(pane, method, None)
                if callback:
                    try:
                        callback()
                    except Exception as error:  # noqa: BLE001
                        self.notify(str(error), severity="error")
        try:
            self.query_one(YamlPane).refresh_files()
        except Exception:
            pass
        self.notify("configuration reloaded")

    def open_yaml(self, path) -> None:
        from pathlib import Path

        path = Path(path)
        self.action_open_tab("yaml")
        try:
            self.query_one(YamlPane).refresh_files()
            self.query_one(YamlPane).load_file(path)
        except Exception as error:  # noqa: BLE001
            self.notify(str(error), severity="error")

    # ------------------------------------------------------------------- actions
    def action_build(self) -> None:
        self.action_open_tab("build")
        self._log("build-log", "[b]building…[/b]")
        self._run_build()

    @work(thread=True, exclusive=True)
    def _run_build(self) -> None:
        result = None
        try:
            result = services.run_build(
                self.profile,
                on_line=lambda line: self.call_from_thread(self._log, "build-log", line),
            )
        except Exception as error:  # noqa: BLE001
            self.call_from_thread(self._log, "build-log", f"[red]{error}[/red]")
            self.call_from_thread(self.notify, str(error), severity="error")
            return
        self.call_from_thread(self._after_build, result)

    def _after_build(self, result) -> None:
        if result.ok:
            manifest = result.manifest or {}
            self._log("build-log", "[green]build ok[/green]")
            if manifest:
                nodes = manifest.get("nodes") or {}
                total = sum(value for value in nodes.values() if isinstance(value, int))
                self._log("build-log", f"nodes: {total}  subscriptions: {len(nodes)}")
            summary = result.diff.get("summary") if isinstance(result.diff, dict) else None
            if summary:
                self._log("build-log", f"diff: {summary}")
            self.notify("build passed")
        else:
            self._log("build-log", "[red]build failed[/red]")
            self.notify("build failed", severity="error")
        for pane_type in (DashboardPane, RoutingPane):
            try:
                getattr(self.query_one(pane_type), "refresh_summary", lambda: None)()
            except Exception:
                pass

    def preview_source(self, name: str) -> None:
        if not name:
            return
        self._preview(name, save_cache=False)

    def fetch_source(self, name: str) -> None:
        if not name:
            return
        self._preview(name, save_cache=True)

    def preview_names(self, name: str) -> None:
        if not name:
            return
        self._run_preview_names(name)

    @work(thread=True, exclusive=False)
    def _run_preview_names(self, name: str) -> None:
        try:
            pairs = services.preview_names(self.profile, name)
        except Exception as error:  # noqa: BLE001
            self.call_from_thread(self.notify, str(error), severity="error", timeout=10)
            return
        lines = [f"names for {name}", ""]
        lines.extend(f"{original}\n  → {renamed}" for original, renamed in pairs)
        self.call_from_thread(self.push_screen, InfoModal("\n".join(lines)))

    def preview_selector(self, filter_pattern: str, prefer: str = "") -> None:
        self._run_preview_selector(filter_pattern, prefer)

    @work(thread=True, exclusive=False)
    def _run_preview_selector(self, filter_pattern: str, prefer: str) -> None:
        try:
            tags = services.preview_selector(self.profile, filter_pattern, prefer)
        except Exception as error:  # noqa: BLE001
            self.call_from_thread(self.notify, str(error), severity="error", timeout=10)
            return
        lines = [f"selector: {filter_pattern}", f"members: {len(tags)}", ""]
        lines.extend(tags)
        self.call_from_thread(self.push_screen, InfoModal("\n".join(lines)))

    def fetch_remote_logs(self, host: str, password: str) -> None:
        self._log("deploy-log", f"[b]fetching logs from {host or '?'}…[/b]")
        self._run_remote_logs(host, password)

    @work(thread=True, exclusive=False)
    def _run_remote_logs(self, host: str, password: str) -> None:
        try:
            text = services.remote_logs(host, password)
        except Exception as error:  # noqa: BLE001
            self.call_from_thread(self._log, "deploy-log", f"[red]{error}[/red]")
            return
        for line in text.splitlines():
            self.call_from_thread(self._log, "deploy-log", line)

    @work(thread=True, exclusive=False)
    def _preview(self, name: str, save_cache: bool) -> None:
        try:
            if save_cache:
                preview = services.fetch_to_cache(self.profile, name)
            else:
                preview = services.preview_source(self.profile, name)
        except Exception as error:  # noqa: BLE001
            self.call_from_thread(self.notify, str(error), severity="error", timeout=10)
            return
        text = self._format_preview(preview)
        self.call_from_thread(self.push_screen, InfoModal(text))

    @staticmethod
    def _format_preview(preview) -> str:
        lines = [
            f"{preview.name}  [{preview.kind}]",
            f"nodes: {preview.total}",
            "types: " + ", ".join(f"{key}={value}" for key, value in sorted(preview.types.items())),
            "",
            "sample:",
        ]
        lines.extend(f"  {tag}" for tag in preview.tags)
        if preview.errors:
            lines.append("")
            lines.append("errors:")
            lines.extend(f"  {error}" for error in preview.errors)
        return "\n".join(lines)

    def run_probe(self, target: str) -> None:
        self.action_open_tab("logs")
        self._log("logs-view", f"[b]probe {target}…[/b]")
        self._run_probe(target)

    @work(thread=True, exclusive=True)
    def _run_probe(self, target: str) -> None:
        try:
            output = services.run_probe(self.profile, target)
        except Exception as error:  # noqa: BLE001
            self.call_from_thread(self._log, "logs-view", f"[red]{error}[/red]")
            return
        for line in output.splitlines():
            self.call_from_thread(self._log, "logs-view", line)

    def deploy(self, host: str, password: str, restart: bool) -> None:
        self._log("deploy-log", f"[b]deploying to {host or '?'}…[/b]")
        self._run_deploy(host, password, restart)

    @work(thread=True, exclusive=True)
    def _run_deploy(self, host: str, password: str, restart: bool) -> None:
        try:
            output = services.deploy(self.profile, host, password, restart)
        except Exception as error:  # noqa: BLE001
            self.call_from_thread(self._log, "deploy-log", f"[red]{error}[/red]")
            self.call_from_thread(self.notify, str(error), severity="error")
            return
        for line in output.splitlines():
            self.call_from_thread(self._log, "deploy-log", line)
        self.call_from_thread(self.notify, "deploy finished")

    def action_help(self) -> None:
        self.push_screen(
            InfoModal(
                "Keys:\n"
                "  q  quit\n"
                "  b  build & check\n"
                "  r  reload configuration\n"
                "  F1 this help\n\n"
                "Tabs: Dashboard, Sources, Routing, Selectors, Protocols, Secrets,\n"
                "YAML (raw editor), Build, Logs & Probe, Deploy."
            )
        )


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TUI configurator for the sbx pipeline")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--root", default=None)
    parser.add_argument("--list-profiles", action="store_true")
    args = parser.parse_args(argv)

    if args.list_profiles:
        for profile in list_profiles(project_root()):
            print(f"{profile.name:12s} {profile.root}")
        return 0

    app = SbxTui(args.profile, args.root)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
