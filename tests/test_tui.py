import shutil
import tempfile
import unittest
from pathlib import Path

from ruamel.yaml import YAML

from sbx.tui.profiles import Profile
from sbx.tui.store import ConfigStore, StoreError

ROOT = Path(__file__).resolve().parents[1]

HAS_TUI = True
try:
    import textual  # noqa: F401
except Exception:  # noqa: BLE001
    HAS_TUI = False


def make_profile(tmp: Path) -> Profile:
    target = tmp / "config"
    shutil.copytree(ROOT / "config", target)
    return Profile(
        name="test",
        root=tmp,
        config_dir=target,
        pipeline=target / "pipeline.yaml",
        secrets=target / "secrets" / "local.yaml",
        build_dir=tmp / "build",
    )


class StoreTests(unittest.TestCase):
    def test_round_trip_preserves_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            store = ConfigStore(profile)
            path = profile.subscriptions_dir / "10-example.yaml"
            text = path.read_text(encoding="utf-8")
            path.write_text(text + "\n# keep this comment\n", encoding="utf-8")

            document = store.load(path)
            document.data["metadata"]["name"] = "Renamed"
            store.save(document)

            updated = path.read_text(encoding="utf-8")
            self.assertIn("# keep this comment", updated)
            self.assertIn("Renamed", updated)
            self.assertEqual(document.error, None)

    def test_invalid_edit_is_rolled_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            store = ConfigStore(profile)
            path = profile.subscriptions_dir / "10-example.yaml"
            original = path.read_text(encoding="utf-8")

            document = store.load(path)
            document.data["kind"] = "Broken"
            with self.assertRaises(StoreError):
                store.save(document)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertIsNotNone(document.error)

    def test_raw_editor_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            store = ConfigStore(profile)
            path = profile.subscriptions_dir / "10-example.yaml"
            original = path.read_text(encoding="utf-8")
            with self.assertRaises(Exception):
                store.save_text(path, "kind: [unclosed\n")
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_archive_moves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            store = ConfigStore(profile)
            path = profile.subscriptions_dir / "10-example.yaml"
            target = store.archive(path)
            self.assertFalse(path.exists())
            self.assertTrue(target.exists())

    def test_secrets_entries_are_flattened(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            profile.secrets.parent.mkdir(parents=True, exist_ok=True)
            YAML().dump({"subscriptions": {"demo": {"url": "https://example.com"}}}, profile.secrets)
            store = ConfigStore(profile)
            entries = dict(store.secrets_entries())
            self.assertEqual(entries["subscriptions.demo.url"], "https://example.com")


@unittest.skipUnless(HAS_TUI, "textual is not installed")
class AppSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_starts(self):
        from sbx.tui.app import SbxTui

        app = SbxTui("default", ROOT)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(app.title, "sbx · default")

    async def test_tabs_modals_and_yaml_editor(self):
        from textual.widgets import TabbedContent, TextArea

        from sbx.tui.app import SbxTui
        from sbx.tui.screens import SubscriptionModal

        app = SbxTui("default", ROOT)
        async with app.run_test() as pilot:
            await pilot.pause()
            for tab in ("sources", "routing", "selectors", "protocols", "secrets", "yaml", "build", "logs", "deploy"):
                app.action_open_tab(tab)
                await pilot.pause()

            app.open_yaml(ROOT / "config/selectors.yaml")
            await pilot.pause()
            editor = app.query_one(TextArea)
            self.assertIn("templates", editor.text)

            app.push_screen(SubscriptionModal(app.store))
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(app.query_one(TabbedContent).active, "yaml")


if __name__ == "__main__":
    unittest.main()
