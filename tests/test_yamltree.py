import unittest

from sbx.tui.yamltree import (
    Node,
    add_key,
    append_item,
    delete,
    display_path,
    dump_value,
    flatten,
    get,
    parse_value,
    set_value,
)


class YamlTreeTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "root": {
                "name": "example",
                "items": [{"id": 1}, {"id": 2}],
                "enabled": True,
            }
        }

    def test_flatten(self):
        rows = flatten(self.data)
        labels = [node.label for node in rows]
        self.assertIn("/", labels)
        self.assertIn("root.name", labels)
        self.assertIn("root.items[1].id", labels)
        kinds = {node.label: node.kind for node in rows}
        self.assertEqual(kinds["root"], "map")
        self.assertEqual(kinds["root.items"], "list")
        self.assertEqual(kinds["root.name"], "scalar")

    def test_display_path(self):
        self.assertEqual(display_path(()), "/")
        self.assertEqual(display_path(("a", "b")), "a.b")
        self.assertEqual(display_path(("a", 0, "b")), "a[0].b")

    def test_get_set_delete(self):
        self.assertEqual(get(self.data, ("root", "name")), "example")
        set_value(self.data, ("root", "name"), "changed")
        self.assertEqual(self.data["root"]["name"], "changed")
        delete(self.data, ("root", "enabled"))
        self.assertNotIn("enabled", self.data["root"])

    def test_add_key_and_item(self):
        add_key(self.data, ("root",), "extra", 42)
        self.assertEqual(self.data["root"]["extra"], 42)
        append_item(self.data, ("root", "items"), {"id": 3})
        self.assertEqual(len(self.data["root"]["items"]), 3)

    def test_wrong_container_type(self):
        with self.assertRaises(ValueError):
            add_key(self.data, ("root", "items"), "x", 1)
        with self.assertRaises(ValueError):
            append_item(self.data, ("root",), {"id": 3})
        with self.assertRaises(ValueError):
            delete(self.data, ())

    def test_parse_and_dump(self):
        self.assertEqual(parse_value("42"), 42)
        self.assertEqual(parse_value("a: 1"), {"a": 1})
        self.assertEqual(parse_value(""), None)
        self.assertEqual(dump_value({"a": 1}).strip(), "a: 1")
        self.assertEqual(parse_value(dump_value("plain")), "plain")


if __name__ == "__main__":
    unittest.main()