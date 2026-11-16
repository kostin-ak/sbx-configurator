import unittest

from sbx.naming import NamingSpec, apply_naming, split_flag, stable_id, transport_label, unified_tag


class NamingTests(unittest.TestCase):
    def test_split_flag(self):
        self.assertEqual(split_flag("🇩🇪 [Z] Berlin"), ("🇩🇪", "DE"))
        self.assertEqual(split_flag("🇷🇺 Москва"), ("🇷🇺", "RU"))
        self.assertEqual(split_flag("📱 Белые списки 1"), ("", ""))

    def test_transport_label(self):
        self.assertEqual(transport_label({"transport": {"type": "ws"}}), "WS")
        self.assertEqual(transport_label({"transport": {"type": "grpc"}}), "gRPC")
        self.assertEqual(transport_label({"tls": {"reality": {"enabled": True}}}), "TCP")
        reality = [{"tag": "🇩🇪 x", "tls": {"reality": {"enabled": True}}, "transport": {"type": "tcp"}}]
        apply_naming(reality, "P", {"enabled": True})
        self.assertIn("TCP-R", reality[0]["tag"])
        self.assertEqual(transport_label({"type": "hysteria2", "tls": {"enabled": True}}), "HY2")

    def test_stable_id_is_stable(self):
        node = {"server": "example.com", "server_port": 443}
        self.assertEqual(stable_id(node), stable_id({"server": "example.com", "server_port": 443}))
        self.assertNotEqual(stable_id(node), stable_id({"server": "example.com", "server_port": 8443}))

    def test_disabled_keeps_original_tag(self):
        nodes = [{"tag": "🇩🇪 raw name", "transport": {"type": "ws"}}]
        self.assertEqual(apply_naming(nodes, "Provider")[0]["tag"], "🇩🇪 raw name")

    def test_template_with_sequence_index(self):
        nodes = [
            {"tag": "🇫🇮 [Z] A", "server": "a.example", "server_port": 443, "transport": {"type": "grpc"}},
            {"tag": "🇫🇮 [Z] B", "server": "b.example", "server_port": 443, "transport": {"type": "ws"}},
        ]
        apply_naming(nodes, "Provider", {"enabled": True})
        self.assertEqual(nodes[0]["tag"], "🇫🇮FI Provider gRPC 01")
        self.assertEqual(nodes[1]["tag"], "🇫🇮FI Provider WS 02")

    def test_template_keeps_whitelist_marker(self):
        nodes = [{"tag": "🇩🇪 Германия, Extra Whitelist2", "server": "a.example", "server_port": 443,
                  "transport": {"type": "ws"}}]
        apply_naming(nodes, "Provider", {"enabled": True})
        self.assertEqual(nodes[0]["tag"], "🇩🇪DE Provider WL WS 01")

    def test_custom_fields_and_fallback(self):
        nodes = [
            {"tag": "🇫🇮 [Z] Berlin · V19", "server": "a.example", "server_port": 443, "transport": {"type": "grpc"}},
            {"tag": "🇫🇮 [Z] Paris", "server": "b.example", "server_port": 443, "transport": {"type": "ws"}},
        ]
        apply_naming(
            nodes,
            "Provider",
            {
                "enabled": True,
                "template": "{flag}{cc} {provider} {transport} {num}",
                "fallback_template": "{flag}{cc} {provider} {transport} {index:02d}",
                "fields": {"num": r"V(\d+)"},
            },
        )
        self.assertEqual(nodes[0]["tag"], "🇫🇮FI Provider gRPC 19")
        self.assertEqual(nodes[1]["tag"], "🇫🇮FI Provider WS 02")

    def test_regex_mode(self):
        nodes = [{"tag": "🇩🇪 [Z] Berlin"}]
        apply_naming(
            nodes,
            "Provider",
            {"enabled": True, "mode": "regex", "pattern": r"\s*\[[^\]]*\]\s*", "replacement": " "},
        )
        self.assertEqual(nodes[0]["tag"], "🇩🇪 Berlin")

    def test_stable_index(self):
        nodes = [{"tag": "🇫🇮 [Z] A", "server": "a.example", "server_port": 443, "transport": {"type": "grpc"}}]
        apply_naming(nodes, "Provider", {"enabled": True, "index": "stable"})
        expected = stable_id(nodes[0])
        self.assertTrue(nodes[0]["tag"].endswith(str(expected)))

    def test_nodes_without_flag_keep_name(self):
        nodes = [{"tag": "📱 Example node 1"}]
        self.assertEqual(apply_naming(nodes, "Provider", {"enabled": True})[0]["tag"], "📱 Example node 1")

    def test_duplicates_get_a_suffix(self):
        nodes = [
            {"tag": "🇫🇮 [Z] Same", "server": "a.example", "server_port": 443, "transport": {"type": "grpc"}},
            {"tag": "🇫🇮 [Z] Same", "server": "b.example", "server_port": 443, "transport": {"type": "grpc"}},
        ]
        apply_naming(nodes, "Provider", {"enabled": True, "index": "none"})
        self.assertNotEqual(nodes[0]["tag"], nodes[1]["tag"])
        self.assertIn("(2)", nodes[1]["tag"])

    def test_unified_tag_helper(self):
        node = {"tag": "🇩🇪 Германия, Extra Whitelist2", "transport": {"type": "ws"}}
        self.assertEqual(unified_tag(node, "Provider", 7), "🇩🇪DE Provider WL WS 07")


if __name__ == "__main__":
    unittest.main()