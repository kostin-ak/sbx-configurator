import unittest

from sbx.awg import parse_wireguard_conf

SAMPLE = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Address = 10.0.0.2/32, fd00::2/128
DNS = 1.1.1.1
MTU = 1420

Jc = 3
Jmin = 69
Jmax = 276
S1 = 27
S2 = 27
S3 = 19
S4 = 20
H1 = 100000000-100000100
I1 = <b 0x0000000000000000>
HeaderProtectionKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
ContentPaddingAddition = 0-112

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
Endpoint = awg.example.com:44553
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""


class WireGuardConfTests(unittest.TestCase):
    def test_interface_and_peer(self):
        endpoint = parse_wireguard_conf(SAMPLE, "example")
        self.assertEqual(endpoint["type"], "wireguard")
        self.assertEqual(endpoint["tag"], "example")
        self.assertFalse(endpoint["system"])
        self.assertEqual(endpoint["address"], ["10.0.0.2/32", "fd00::2/128"])
        self.assertEqual(endpoint["private_key"], "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
        self.assertEqual(endpoint["mtu"], 1420)
        peer = endpoint["peers"][0]
        self.assertEqual(peer["address"], "awg.example.com")
        self.assertEqual(peer["port"], 44553)
        self.assertEqual(peer["allowed_ips"], ["0.0.0.0/0", "::/0"])
        self.assertEqual(peer["persistent_keepalive_interval"], 25)

    def test_amnezia_fields_are_mapped(self):
        amnezia = parse_wireguard_conf(SAMPLE, "x")["amnezia"]
        self.assertEqual(amnezia["jc"], 3)
        self.assertEqual(amnezia["jmin"], 69)
        self.assertEqual(amnezia["jmax"], 276)
        self.assertEqual(amnezia["s1"], 27)
        self.assertEqual(amnezia["h1"], "100000000-100000100")
        self.assertEqual(amnezia["i1"], "<b 0x0000000000000000>")
        self.assertEqual(amnezia["header_protection_key"], "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
        self.assertEqual(amnezia["content_padding_addition"], "0-112")

    def test_missing_peer_is_rejected(self):
        with self.assertRaises(Exception):
            parse_wireguard_conf("[Interface]\nPrivateKey = key\nAddress = 10.0.0.2/32\n", "x")


if __name__ == "__main__":
    unittest.main()