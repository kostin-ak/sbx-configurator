import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sbx.artifact import atomic_write_json, publish_artifact
from sbx.diff import semantic_diff
from sbx.offline import stub_remote_rule_sets
from sbx.pack import create_pack, extract_pack, verify_pack
from sbx.runtime import make_proxy_only
from sbx.secrets import mask_config
from sbx.validate import validate_config


class CoreTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_atomic_artifact_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = publish_artifact(root, "config.json", {"outbounds": []})
            self.assertTrue(output.is_file())
            manifest = json.loads((root / "config.json.manifest.json").read_text())
            self.assertEqual(manifest["format"], 1)
            self.assertEqual(manifest["size"], output.stat().st_size)

    def test_proxy_only_removes_tun_and_hijack(self):
        config = {
            "inbounds": [{"type": "tun", "tag": "tun-in"}, {"type": "mixed", "tag": "in-mixed", "listen_port": 7890}],
            "outbounds": [{"type": "direct", "tag": "direct"}],
            "route": {"rules": [{"inbound": ["tun-in"], "action": "sniff"}, {"protocol": "dns", "action": "hijack-dns"}]},
            "experimental": {"clash_api": {"external_controller": "0.0.0.0:9090"}},
        }
        result, changes = make_proxy_only(config, port=7891, clash_port=9091)
        self.assertEqual(result["inbounds"][0]["listen_port"], 7891)
        self.assertEqual(result["route"]["rules"], [{"ip_cidr": ["127.0.0.0/8", "::1/128"], "outbound": "direct"}])
        self.assertEqual(result["experimental"]["clash_api"]["external_controller"], "127.0.0.1:9091")
        self.assertIn("removed TUN inbound", changes)
        self.assertIn("removed DNS hijack rule", changes)
        self.assertIn("routed loopback directly for deterministic tests", changes)

    def test_offline_stub_replaces_remote_rule_set(self):
        config = {"route": {"rule_set": [{"tag": "geo", "type": "remote", "url": "https://example/geo.srs"}]}}
        compiler = Path(self.tempdir.name) / "compiler"
        with patch("sbx.offline.subprocess.run") as mocked_run:
            mocked_run.return_value.returncode = 0
            result, changes = stub_remote_rule_sets(config, Path(self.tempdir.name) / "stubs", compiler)
        self.assertEqual(result["route"]["rule_set"][0]["type"], "local")
        self.assertIn("stubbed remote rule-set geo", changes)

    def test_validator_finds_missing_reference(self):
        issues = validate_config({"outbounds": [{"type": "selector", "tag": "s", "outbounds": ["missing"]}], "route": {}})
        self.assertTrue(any(issue.code == "broken-selector" for issue in issues))

    def test_secret_masking(self):
        masked = mask_config({"password": "abcdef123456", "nested": {"uuid": "12345678-abcd"}})
        self.assertEqual(masked["password"], "abcd***3456")
        self.assertEqual(masked["nested"]["uuid"], "1234***abcd")

    def test_semantic_diff(self):
        old = {"outbounds": [{"type": "vless", "tag": "a"}], "route": {"rules": []}}
        new = {"outbounds": [{"type": "mieru", "tag": "b"}], "route": {"rules": [{}]}}
        result = semantic_diff(old, new)
        self.assertTrue(result["changed"])
        self.assertEqual(result["outbounds"]["vless"]["removed"], ["a"])
        self.assertEqual(result["outbounds"]["mieru"]["added"], ["b"])

    def test_pack_roundtrip_and_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "hello.txt").write_text("hello", encoding="utf-8")
            archive = create_pack(source, root / "test.sbxpack", "1.2.3")
            manifest = verify_pack(archive)
            self.assertEqual(manifest["version"], "1.2.3")
            destination = root / "stage"
            extract_pack(archive, destination)
            self.assertEqual((destination / "hello.txt").read_text(), "hello")
            (destination / "hello.txt").write_text("modified", encoding="utf-8")
            with self.assertRaises(ValueError):
                with archive.open("rb") as stream:
                    import zipfile
                    from io import BytesIO
                    data = bytearray(stream.read())
                    index = data.find(b"hello")
                    data[index:index + 5] = b"xxxxx"
                    tampered = root / "tampered.sbxpack"
                    tampered.write_bytes(data)
                    verify_pack(tampered)


if __name__ == "__main__":
    unittest.main()
