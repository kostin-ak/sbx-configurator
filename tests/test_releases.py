import os
import tempfile
import unittest
from pathlib import Path

from sbx.pack import create_pack
from sbx.releases import activate_pack, rollback


@unittest.skipIf(os.name == "nt", "symlink activation is tested in WSL/Linux")
class ReleaseTests(unittest.TestCase):
    def test_activation_and_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            releases = root / "releases"
            current = root / "current"
            packs = []
            for version in ("0.1.0", "0.2.0"):
                source = root / f"src-{version}"
                source.mkdir()
                (source / "version.txt").write_text(version, encoding="utf-8")
                packs.append(create_pack(source, root / f"{version}.sbxpack", version))
            first = activate_pack(packs[0], releases, current)
            self.assertEqual(current.resolve(), releases / "0.1.0")
            second = activate_pack(packs[1], releases, current)
            self.assertEqual(second["previous"], str(releases / "0.1.0"))
            rolled_back = rollback(current)
            self.assertEqual(current.resolve(), releases / "0.1.0")
            self.assertEqual(rolled_back["previous"], str(releases / "0.2.0"))
            rollback(current)
            self.assertEqual(current.resolve(), releases / "0.2.0")


if __name__ == "__main__":
    unittest.main()
