"""Tests for TUI batch operations and profile bundles.

They live in a separate module so the core test job can skip them when the
optional TUI dependencies are absent.
"""

import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

HAS_TUI = True
try:
    from ruamel.yaml import YAML  # noqa: F401

    from sbx.tui.profiles import Profile, get_profile
    from sbx.tui.store import ConfigStore
    from sbx.tui import batch as batch_helpers
    from sbx.tui import bundles as bundle_helpers
except Exception:  # noqa: BLE001
    HAS_TUI = False
    Profile = None
    ConfigStore = None
    batch_helpers = None
    bundle_helpers = None

TUI_REQUIRED = unittest.skipUnless(HAS_TUI, "TUI dependencies are not installed (pip install .[tui])")


def make_profile(base: Path, name: str = "test", config_source: Path | None = None) -> Profile:
    config_dir = base / "config"
    shutil.copytree(config_source or (ROOT / "config"), config_dir)
    return Profile(
        name=name,
        root=base,
        config_dir=config_dir,
        pipeline=config_dir / "pipeline.yaml",
        secrets=config_dir / "secrets" / "local.yaml",
        build_dir=base / "build",
    )


@TUI_REQUIRED
class BatchTests(unittest.TestCase):
    def test_clone_keeps_transforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            store = ConfigStore(profile)
            target = batch_helpers.clone_subscription(store, "Example", "Example copy")
            self.assertTrue(target.is_file())
            data = yaml.safe_load(target.read_text(encoding="utf-8"))
            self.assertEqual(data["metadata"]["name"], "Example copy")
            self.assertTrue(data.get("transforms"))

    def test_clone_rejects_duplicate_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            store = ConfigStore(profile)
            with self.assertRaises(ValueError):
                batch_helpers.clone_subscription(store, "Example", "Example")

    def test_enable_disable_many(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            store = ConfigStore(profile)
            updated, errors = batch_helpers.set_enabled(store, ["Example", "System"], False)
            self.assertEqual(updated, 2)
            self.assertEqual(errors, [])
            for document in store.subscriptions():
                self.assertFalse((document.data.get("metadata") or {}).get("enabled", True))

    def test_archive_many(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            store = ConfigStore(profile)
            removed, errors = batch_helpers.archive_many(store, ["Example"])
            self.assertEqual(removed, 1)
            self.assertEqual(errors, [])
            self.assertFalse((profile.subscriptions_dir / "10-example.yaml").exists())
            self.assertTrue((profile.config_dir / ".trash").is_dir())


@TUI_REQUIRED
class BundleTests(unittest.TestCase):
    def test_export_excludes_secrets_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            profile.secrets.parent.mkdir(parents=True, exist_ok=True)
            profile.secrets.write_text("subscriptions: {}\n", encoding="utf-8")
            bundle = bundle_helpers.export_bundle(profile)
            self.assertTrue(bundle.is_file())
            with tarfile.open(bundle) as archive:
                names = archive.getnames()
            self.assertIn("config/pipeline.yaml", names)
            self.assertIn("config/subscriptions.d/10-example.yaml", names)
            self.assertNotIn("config/secrets/local.yaml", names)

    def test_export_can_include_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(Path(tmp))
            profile.secrets.parent.mkdir(parents=True, exist_ok=True)
            profile.secrets.write_text("subscriptions: {}\n", encoding="utf-8")
            bundle = bundle_helpers.export_bundle(profile, include_secrets=True)
            with tarfile.open(bundle) as archive:
                self.assertIn("config/secrets/local.yaml", archive.getnames())

    def test_import_as_new_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "source"
            source_root.mkdir()
            source = make_profile(source_root)
            bundle = bundle_helpers.export_bundle(source)

            target_root = Path(tmp) / "target"
            target_root.mkdir()
            imported = bundle_helpers.import_bundle(target_root, bundle, "imported")
            self.assertEqual(imported.name, "imported")
            self.assertTrue((imported.config_dir / "pipeline.yaml").is_file())
            self.assertEqual(get_profile("imported", target_root).name, "imported")

    def test_unsafe_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evil = root / "evil.txt"
            evil.write_text("boom", encoding="utf-8")
            bundle = root / "evil.tar.gz"
            with tarfile.open(bundle, "w:gz") as archive:
                archive.add(evil, arcname="config/../../evil.txt")
            with self.assertRaises(Exception):
                bundle_helpers.import_bundle(root, bundle, "evil")

    def test_import_without_pipeline_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "empty.txt"
            payload.write_text("x", encoding="utf-8")
            bundle = root / "empty.tar.gz"
            with tarfile.open(bundle, "w:gz") as archive:
                archive.add(payload, arcname="config/readme.txt")
            with self.assertRaises(Exception):
                bundle_helpers.import_bundle(root, bundle, "empty")
            self.assertFalse((root / "profiles" / "empty").exists())


if __name__ == "__main__":
    unittest.main()