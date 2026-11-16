import tempfile
import unittest
from pathlib import Path

from sbx.folders import load_folder

CONF = """[Interface]
PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Address = 10.0.0.2/32
MTU = 1420
Jc = 3
Jmin = 10
Jmax = 20
H1 = 1-2

[Peer]
PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
Endpoint = awg.example.com:51820
AllowedIPs = 0.0.0.0/0
"""

LINKS = """# comment
vless://11111111-2222-4333-8444-555555555555@example.com:443?security=tls&type=ws&path=%2Fws#Node
"""


class FolderSourceTests(unittest.TestCase):
    def test_wireguard_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "awg3_example_slot1.conf").write_text(CONF, encoding="utf-8")
            result = load_folder({"path": str(root), "parser": "wireguard-conf"})
            self.assertEqual(result["files"], 1)
            self.assertEqual(len(result["endpoints"]), 1)
            self.assertEqual(result["endpoints"][0]["tag"], "example")
            self.assertTrue(result["report"][0]["ok"])

    def test_sidecar_meta_sets_flag_and_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "awg3_example_slot1.conf").write_text(CONF, encoding="utf-8")
            (root / "awg3_example_slot1.yaml").write_text("country: SE\ntag: example\n", encoding="utf-8")
            endpoint = load_folder({"path": str(root), "parser": "wireguard-conf"})["endpoints"][0]
            self.assertEqual(endpoint["tag"], "🇸🇪example")

    def test_links_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "links.txt").write_text(LINKS, encoding="utf-8")
            result = load_folder({"path": str(root), "parser": "share-links"})
            self.assertEqual(len(result["outbounds"]), 1)
            self.assertEqual(result["outbounds"][0]["type"], "vless")
            self.assertTrue(result["report"][0]["ok"])

    def test_broken_file_is_reported_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.conf").write_text("[Interface]\nAddress = 10.0.0.2/32\n", encoding="utf-8")
            result = load_folder({"path": str(root), "parser": "wireguard-conf"})
            self.assertEqual(result["endpoints"], [])
            self.assertEqual(len(result["failed"]), 1)

    def test_missing_folder_raises(self):
        with self.assertRaises(Exception):
            load_folder({"path": "/nonexistent/sbx/keys", "parser": "auto"})


if __name__ == "__main__":
    unittest.main()