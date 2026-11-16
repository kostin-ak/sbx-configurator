import tempfile
import unittest
from pathlib import Path

from sbx.assembly import deep_merge, merge_parts


class AssemblyTests(unittest.TestCase):
    def test_duplicate_new_tag_is_merged_within_one_update(self):
        target = {"outbounds": []}
        deep_merge(target, {"outbounds": [
            {"tag": "a", "type": "selector", "outbounds": ["x"]},
            {"tag": "a", "type": "selector", "outbounds": ["y"]},
        ]})
        self.assertEqual(len(target["outbounds"]), 1)
        self.assertEqual(target["outbounds"][0]["outbounds"], ["x", "y"])

    def test_disabled_directory_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "disabled.disable").mkdir(parents=True)
            (root / "disabled.disable/bad.json").write_text('{"outbounds": [{"type": "block", "tag": "bad"}]}')
            (root / "good.json").write_text('{"outbounds": [{"type": "direct", "tag": "direct"}]}')
            result = merge_parts(root, root / "generated")
            self.assertEqual(len(result["outbounds"]), 1)
            self.assertEqual(result["outbounds"][0]["tag"], "direct")


if __name__ == "__main__":
    unittest.main()
