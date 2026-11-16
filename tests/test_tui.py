import shutil
import tempfile
import unittest
import json
from pathlib import Path

from ruamel.yaml import YAML

from sbx.tui.profiles import Profile
from sbx.tui.store import ConfigStore, StoreError
from sbx.tui import routing as routing_helpers
from sbx.tui import transforms as transform_helpers
from sbx.tui import services

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


def seed_snapshot(profile: Profile) -> None:
    target = profile.root / "snapshot/etc/sing-box/configs"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "examples/snapshot/etc/sing-box/configs/example_links.txt", target / "example_links.txt")


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


class RoutingHelperTests(unittest.TestCase):
    def test_devices_groups_policies_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            store = ConfigStore(profile)

            routing_helpers.upsert_device(store, "Phone", "192.168.1.50/32")
            routing_helpers.upsert_group(store, "Family", ["Phone"])
            routing_helpers.upsert_policy(store, "Family", ["proxy", "youtube"])

            self.assertIn("Phone", routing_helpers.devices(store))
            self.assertEqual(routing_helpers.groups(store)["Family"]["members"], ["Phone"])
            policy = [item for item in routing_helpers.policies(store) if item.get("alias") == "Family"][0]
            self.assertEqual(policy["categories"], ["proxy", "youtube"])
            self.assertIn("proxy", routing_helpers.category_names(store))

            routing_helpers.remove_policy(store, "Family")
            self.assertFalse(any(item.get("alias") == "Family" for item in routing_helpers.policies(store)))

    def test_invalid_policy_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            store = ConfigStore(profile)
            with self.assertRaises(Exception):
                routing_helpers.upsert_policy(store, "Laptop", ["no-such-category"])


class TransformHelperTests(unittest.TestCase):
    def test_transforms_are_editable(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            store = ConfigStore(profile)
            document = store.load(profile.subscriptions_dir / "10-example.yaml")
            initial = len(transform_helpers.transforms(document))

            transform_helpers.upsert_transform(
                store, document, None, "rename", r"\s+", " "
            )
            self.assertEqual(len(transform_helpers.transforms(document)), initial + 1)
            transform_helpers.move_transform(store, document, initial, -1)
            self.assertEqual(transform_helpers.transforms(document)[initial - 1]["pattern"], r"\s+")
            transform_helpers.remove_transform(store, document, initial - 1)
            self.assertEqual(len(transform_helpers.transforms(document)), initial)

    def test_params_must_be_mapping(self):
        self.assertEqual(transform_helpers.parse_params(""), {})
        self.assertEqual(transform_helpers.parse_params("a: 1"), {"a": 1})
        with self.assertRaises(ValueError):
            transform_helpers.parse_params("- 1")


class ServicesTests(unittest.TestCase):
    def test_preview_names_applies_transforms_and_naming(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            seed_snapshot(profile)
            pairs = services.preview_names(profile, "Example")
            self.assertTrue(pairs)
            self.assertTrue(any("Example" in renamed for _, renamed in pairs))

    def test_preview_selector_filters_artifact_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            profile.artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact = {
                "outbounds": [
                    {"type": "vless", "tag": "🇩🇪DE Example TCP 01"},
                    {"type": "vless", "tag": "🇩🇪DE Example WL WS 02"},
                    {"type": "selector", "tag": "🚀 Proxy", "outbounds": []},
                ],
                "endpoints": [],
            }
            profile.artifact.write_text(json.dumps(artifact), encoding="utf-8")
            tags = services.preview_selector(profile, r"^(?!.*WL).*$")
            self.assertEqual(tags, ["🇩🇪DE Example TCP 01"])


@unittest.skipUnless(HAS_TUI, "textual is not installed")
class AppSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncio

        asyncio.get_running_loop().slow_callback_duration = 30

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
