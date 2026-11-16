import unittest

from sbx.validate import validate_config


def base_config(**extra):
    config = {
        "inbounds": [{"type": "mixed", "tag": "in", "listen_port": 7890}],
        "outbounds": [{"type": "direct", "tag": "direct"}],
        "route": {"final": "direct"},
    }
    config.update(extra)
    return config


class CycleValidationTests(unittest.TestCase):
    def test_selector_detour_cycle_is_reported(self):
        config = base_config(
            outbounds=[
                {"type": "direct", "tag": "direct"},
                {"type": "selector", "tag": "proxy", "outbounds": ["direct", "awg"]},
            ],
            endpoints=[
                {"type": "wireguard", "tag": "awg", "address": ["10.0.0.2/32"], "private_key": "k",
                 "peers": [], "detour": "proxy"},
            ],
        )
        issues = validate_config(config)
        self.assertTrue(any(issue.code == "outbound-cycle" for issue in issues), issues)

    def test_bridge_detour_is_valid(self):
        config = base_config(
            outbounds=[
                {"type": "direct", "tag": "direct"},
                {"type": "vless", "tag": "node", "server": "example.com", "server_port": 443, "uuid": "u"},
                {"type": "selector", "tag": "proxy", "outbounds": ["direct", "node", "awg"]},
                {"type": "selector", "tag": "bridge", "outbounds": ["node"]},
            ],
            endpoints=[
                {"type": "wireguard", "tag": "awg", "address": ["10.0.0.2/32"], "private_key": "k",
                 "peers": [], "detour": "bridge"},
            ],
        )
        issues = validate_config(config)
        self.assertFalse(any(issue.code == "outbound-cycle" for issue in issues), issues)

    def test_missing_detour_target_is_reported(self):
        config = base_config(
            endpoints=[
                {"type": "wireguard", "tag": "awg", "address": ["10.0.0.2/32"], "private_key": "k",
                 "peers": [], "detour": "absent-selector"},
            ],
        )
        issues = validate_config(config)
        self.assertTrue(any(issue.code == "broken-detour" for issue in issues), issues)


if __name__ == "__main__":
    unittest.main()
