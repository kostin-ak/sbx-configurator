import json
import tempfile
import unittest
from pathlib import Path

import yaml

from sbx.loader import load_config, load_routing


ROOT = Path(__file__).resolve().parents[1]


def empty_secrets() -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
    handle.write("{}\n")
    handle.close()
    return Path(handle.name)


class LoaderTests(unittest.TestCase):
    def test_examples_load(self):
        loaded = load_config(ROOT / "config", empty_secrets())
        self.assertEqual(loaded.stats, {"subscriptions": 2, "native_outbounds": 0, "native_endpoints": 0})
        names = [item["name"] for item in loaded.subscriptions["subscriptions"]]
        self.assertEqual(names, ["Example", "System"])
        self.assertNotIn("${secret:", json.dumps(loaded.subscriptions, ensure_ascii=False))

    def test_disabled_examples_do_not_require_secrets(self):
        loaded = load_config(ROOT / "config", empty_secrets())
        names = [item["name"] for item in loaded.subscriptions["subscriptions"]]
        self.assertNotIn("AWG", names)
        self.assertNotIn("Links", names)

    def test_examples_use_placeholders(self):
        text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "config/subscriptions.d").glob("*.yaml"))
        self.assertIn("${secret:keys.", text)
        self.assertIn("/etc/sing-box/configs/", text)

    @unittest.skipUnless((ROOT / "snapshot/etc/sing-box/configs/routing.yaml").is_file(), "requires a captured snapshot")
    def test_v2_routing_matches_legacy_model(self):
        legacy = yaml.safe_load((ROOT / "snapshot/etc/sing-box/configs/routing.yaml").read_text(encoding="utf-8"))
        translated = load_routing(ROOT / "config")
        for key in ("devices", "groups", "categories", "policies", "pre_rules", "post_rules", "rule_sets"):
            self.assertEqual(translated[key], legacy[key])


if __name__ == "__main__":
    unittest.main()