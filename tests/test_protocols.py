import hashlib
import unittest
from pathlib import Path

from sbx.protocols import ProtocolRegistry
from sbx.transforms import _random_value, apply_node_rules


class ProtocolAndTransformTests(unittest.TestCase):
    def setUp(self):
        self.registry = ProtocolRegistry(Path(__file__).resolve().parents[1] / "protocols/registry.yaml")

    def test_extended_outbound_is_valid(self):
        self.registry.validate({
            "type": "mieru", "tag": "m", "server": "example.com", "server_port": 27017,
            "username": "u", "password": "p",
        }, "outbounds")

    def test_warp_must_be_endpoint(self):
        with self.assertRaisesRegex(ValueError, "belongs to endpoints"):
            self.registry.validate({"type": "warp", "tag": "w"}, "outbounds")

    def test_required_native_fields(self):
        with self.assertRaisesRegex(ValueError, "server_port"):
            self.registry.validate({"type": "sudoku", "tag": "s", "server": "example.com", "key": "k"}, "outbounds")

    def test_rename_stop_prevents_later_rules(self):
        node = {"type": "vless", "tag": "old"}
        result = apply_node_rules(node, [
            {"action": "rename", "pattern": "old", "replacement": "new", "stop": True},
            {"action": "exclude", "pattern": "new"},
        ])
        self.assertEqual(result["tag"], "new")

    def test_random_patch_matches_legacy_seed_namespacing(self):
        seed = "_server_tag_tls_utls_fingerprint"
        digest = int(hashlib.md5(seed.encode()).hexdigest(), 16)
        expected = ["firefox", "safari", "ios", "edge"][digest % 4]
        params = {"tls": {"utls": {"fingerprint": ["firefox", "safari", "ios", "edge"]}}}
        self.assertEqual(_random_value(params, "_server_tag")["tls"]["utls"]["fingerprint"], expected)


if __name__ == "__main__":
    unittest.main()
