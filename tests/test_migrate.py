import unittest

from sbx.migrate import migrate_config


class MigrationTests(unittest.TestCase):
    def test_legacy_fields_and_references_are_migrated(self):
        source = {
            "inbounds": [{"type": "tun", "tag": "tun-in", "sniff": True, "sniff_override_destination": True}],
            "route": {"rules": [{"ip_is_private": True, "outbound": "DIRECT"}]},
            "experimental": {"cache_file": {"enabled": True, "store_rdrc": True}},
            "outbounds": [{"type": "direct", "tag": "direct"}],
        }
        result, changes = migrate_config(source, "/snapshot", "/state")
        self.assertNotIn("sniff", result["inbounds"][0])
        self.assertNotIn("sniff_override_destination", result["inbounds"][0])
        self.assertEqual(result["route"]["rules"][0], {"inbound": "tun-in", "action": "sniff"})
        self.assertEqual(result["route"]["rules"][1]["outbound"], "direct")
        self.assertTrue(result["experimental"]["cache_file"]["store_dns"])
        self.assertNotIn("store_rdrc", result["experimental"]["cache_file"])
        self.assertEqual(len(changes), 4)

    def test_paths_are_relocated_recursively(self):
        source = {
            "outbounds": [{"type": "mieru", "server": "example.com"}],
            "route": {"rule_set": [{"path": "/etc/sing-box/rules/custom.srs"}]},
            "log": {"output": "/etc/sing-box/sing-box.log"},
        }
        result, _ = migrate_config(source, "/snapshot", "/state")
        self.assertEqual(result["route"]["rule_set"][0]["path"], "/snapshot/etc/sing-box/rules/custom.srs")
        self.assertEqual(result["log"]["output"], "/state/logs/sing-box.log")

    def test_source_is_not_mutated(self):
        source = {"inbounds": [{"tag": "tun-in", "sniff": True}]}
        migrate_config(source, "/snapshot", "/state")
        self.assertTrue(source["inbounds"][0]["sniff"])

    def test_list_inbound_match_does_not_break_sniff_detection(self):
        source = {
            "inbounds": [{"tag": "tun-in", "sniff": True}],
            "route": {"rules": [{"inbound": ["tun-in"], "action": "hijack-dns"}]},
        }
        result, _ = migrate_config(source, "/snapshot", "/state")
        self.assertEqual(result["route"]["rules"][0]["action"], "sniff")

    def test_local_runtime_paths_are_not_snapshot_mutations(self):
        source = {
            "log": {"output": "/etc/sing-box/sing-box.log"},
            "experimental": {"clash_api": {"external_ui": "ui"}},
        }
        result, _ = migrate_config(source, "/snapshot", "/state/local")
        self.assertEqual(result["log"]["output"], "/state/local/logs/sing-box.log")
        self.assertEqual(result["experimental"]["clash_api"]["external_ui"], "/state/local/ui")


if __name__ == "__main__":
    unittest.main()
