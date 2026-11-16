import unittest

from sbx.naming import apply_naming, split_flag, stable_id, transport_label, unified_tag


class NamingTests(unittest.TestCase):
    def test_split_flag(self):
        self.assertEqual(split_flag("🇩🇪 [Z] Berlin"), ("🇩🇪", "DE"))
        self.assertEqual(split_flag("🇷🇺 Москва"), ("🇷🇺", "RU"))
        self.assertEqual(split_flag("📱 Example node 1"), ("", ""))

    def test_transport_label(self):
        self.assertEqual(transport_label({"transport": {"type": "ws"}}), "WS")
        self.assertEqual(transport_label({"transport": {"type": "grpc"}}), "gRPC")
        self.assertEqual(transport_label({"tls": {"reality": {"enabled": True}}}), "TCP-R")
        self.assertEqual(transport_label({"type": "hysteria2", "tls": {"enabled": True}}), "HY2")

    def test_stable_id_is_stable(self):
        node = {"server": "example.com", "server_port": 443}
        self.assertEqual(stable_id(node), stable_id({"server": "example.com", "server_port": 443}))
        self.assertNotEqual(stable_id(node), stable_id({"server": "example.com", "server_port": 8443}))

    def test_unified_tag_keeps_whitelist_marker(self):
        node = {"tag": "🇩🇪 Германия, Extra Whitelist2", "transport": {"type": "ws"}}
        self.assertRegex(unified_tag(node, "ExampleVPN", 937), r"^🇩🇪DE ExampleVPN WL WS 0937$")

    def test_nodes_without_flag_keep_name(self):
        nodes = [{"tag": "📱 Example node 1"}]
        self.assertEqual(apply_naming(nodes, "ExampleProvider")[0]["tag"], "📱 Example node 1")

    def test_apply_naming_is_unique_and_stable(self):
        nodes = [
            {"tag": "🇫🇮 [Z] A", "server": "a.example", "server_port": 443, "transport": {"type": "grpc"}},
            {"tag": "🇫🇮 [Z] B", "server": "b.example", "server_port": 443, "transport": {"type": "ws"}},
            {"tag": "🇫🇮 [Z] C", "server": "c.example", "server_port": 443, "transport": {"type": "xhttp"}},
        ]
        first = [node["tag"] for node in apply_naming(nodes, "ExampleProvider")]
        self.assertEqual(len(set(first)), 3)
        self.assertTrue(all(tag.startswith("🇫🇮FI ExampleProvider ") for tag in first))
        # renaming the same set again must produce identical names (refresh-stable)
        nodes_again = [
            {"tag": "🇫🇮 [Z] A", "server": "a.example", "server_port": 443, "transport": {"type": "grpc"}},
            {"tag": "🇫🇮 [Z] B", "server": "b.example", "server_port": 443, "transport": {"type": "ws"}},
            {"tag": "🇫🇮 [Z] C", "server": "c.example", "server_port": 443, "transport": {"type": "xhttp"}},
        ]
        self.assertEqual([node["tag"] for node in apply_naming(nodes_again, "ExampleProvider")], first)


if __name__ == "__main__":
    unittest.main()