import base64
import unittest

from sbx.links import parse_link


class LinkParserTests(unittest.TestCase):
    def test_vless_xhttp_transport_is_preserved(self):
        uri = "vless://9b65b7e1-04c8-4717-8f45-2aa61fd25937@example.com:443?security=tls&type=xhttp&host=example.com&path=%2Fxhttp&mode=stream-up&xPaddingBytes=100-1000#xhttp"
        node = parse_link(uri)
        self.assertEqual(node["transport"]["type"], "xhttp")
        self.assertEqual(node["transport"]["path"], "/xhttp")
        self.assertEqual(node["transport"]["host"], "example.com")
        self.assertEqual(node["transport"]["mode"], "stream-up")
        self.assertEqual(node["transport"]["x_padding_bytes"], "100-1000")

    def test_vless_encryption_is_preserved(self):
        uri = "vless://9b65b7e1-04c8-4717-8f45-2aa61fd25937@example.com:443?security=tls&type=tcp&encryption=mlkem768x25519plus.native.0rtt.exampleKey#encrypted"
        node = parse_link(uri)
        self.assertEqual(node["encryption"], "mlkem768x25519plus.native.0rtt.exampleKey")

    def test_vless_encryption_none_is_omitted(self):
        uri = "vless://9b65b7e1-04c8-4717-8f45-2aa61fd25937@example.com:443?security=tls&type=tcp&encryption=none#plain"
        node = parse_link(uri)
        self.assertNotIn("encryption", node)

    def test_vless_httpupgrade_transport_is_preserved(self):
        uri = "vless://9b65b7e1-04c8-4717-8f45-2aa61fd25937@example.com:443?security=tls&type=httpupgrade&host=example.com&path=%2Fupgrade#upgrade"
        node = parse_link(uri)
        self.assertEqual(node["transport"]["type"], "httpupgrade")
        self.assertEqual(node["transport"]["path"], "/upgrade")
        self.assertEqual(node["transport"]["host"], "example.com")

    def test_vless_xhttp_defaults_padding_when_absent(self):
        uri = "vless://9b65b7e1-04c8-4717-8f45-2aa61fd25937@example.com:443?security=tls&type=xhttp&path=%2F#xhttp"
        node = parse_link(uri)
        self.assertEqual(node["transport"]["x_padding_bytes"], "100-1000")

    def test_vless_xhttp_reads_padding_from_extra(self):
        extra = base64.urlsafe_b64encode(b'{"xPaddingBytes":"250-500","noGRPCHeader":true}').decode().rstrip("=")
        uri = f"vless://9b65b7e1-04c8-4717-8f45-2aa61fd25937@example.com:443?security=tls&type=xhttp&extra={extra}#xhttp"
        node = parse_link(uri)
        self.assertEqual(node["transport"]["x_padding_bytes"], "250-500")
        self.assertTrue(node["transport"]["no_grpc_header"])

    def test_vless_ws_omits_empty_host_header(self):
        uri = "vless://9b65b7e1-04c8-4717-8f45-2aa61fd25937@example.com:443?security=tls&type=ws&path=%2Fws#ws"
        node = parse_link(uri)
        self.assertEqual(node["transport"]["type"], "ws")
        self.assertNotIn("headers", node["transport"])

    def test_vless_ws_keeps_host_header(self):
        uri = "vless://9b65b7e1-04c8-4717-8f45-2aa61fd25937@example.com:443?security=tls&type=ws&path=%2Fws&host=cdn.example.com#ws"
        node = parse_link(uri)
        self.assertEqual(node["transport"]["headers"], {"Host": "cdn.example.com"})

    def test_hysteria2_is_parsed(self):
        uri = "hysteria2://secret@example.com:8443/?obfs=salamander&obfs-password=pass&sni=example.com&insecure=1#hy2"
        node = parse_link(uri)
        self.assertEqual(node["type"], "hysteria2")
        self.assertEqual(node["server"], "example.com")
        self.assertEqual(node["server_port"], 8443)
        self.assertEqual(node["password"], "secret")
        self.assertEqual(node["obfs"], {"type": "salamander", "password": "pass"})
        self.assertTrue(node["tls"]["insecure"])


if __name__ == "__main__":
    unittest.main()
