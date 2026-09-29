"""Focused packaging guards; no package install or scientific run."""
import base64
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import prepare_python as payload

# prepare() refuses every platform except Windows CPython 3.12, the only supported packaging route.
SUPPORTED = sys.platform == "win32" and sys.version_info[:2] == (3, 12)
WINDOWS_ONLY = unittest.skipUnless(SUPPORTED, "packaging payload check for Windows CPython 3.12 only; a skip "
                                   "here is not validation of the Windows executable")


class PackagingGuards(unittest.TestCase):
    def test_requirement_closure_deduplicates_shared_core(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "core.txt").write_text("--only-binary=:all:\nnumpy==2.4.6\n")
            (root / "a.txt").write_text("-r core.txt\npsutil==7.2.2\n")
            (root / "b.txt").write_text("-r core.txt\nmatplotlib==3.11.2\n")
            self.assertEqual(payload.requirements([root / "a.txt", root / "b.txt"]),
                             {"matplotlib": "3.11.2", "numpy": "2.4.6", "psutil": "7.2.2"})

    def test_requirements_refuse_cycles_conflicts_escape_and_unpinned(self):
        for text in ("-r input.txt", "-r ../escape.txt", "demo>=1", "demo==1\ndemo==2"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "input.txt"
                path.write_text("--only-binary=:all:\n" + text)
                with self.assertRaises(ValueError):
                    payload.requirements([path])

    def test_record_only_omits_recognised_venv_launchers(self):
        self.assertIsNone(payload.record_path("../../Scripts/demo.exe"))
        for name in ("../secret", "/absolute", "C:/secret", "demo\\file", "../../Scripts/sub/file"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                payload.record_path(name)

    @WINDOWS_ONLY
    def test_nonempty_destination_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("base", "site", "output"):
                (root / name).mkdir()
            keep = root / "output/keep.txt"
            keep.write_text("preserve")
            with self.assertRaisesRegex(ValueError, "overwrite"):
                payload.prepare(root / "base", root / "site", [], root / "output")
            self.assertEqual(keep.read_text(), "preserve")

    def test_ancestor_junction_is_rejected(self):
        with patch.object(Path, "is_junction", lambda path: path.name == "linked"):
            with self.assertRaisesRegex(ValueError, "Linked"):
                payload.checked_path(Path("linked/child/file"))

    @WINDOWS_ONLY
    def test_wheel_drift_refused_without_source_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base, site, output = root / "base", root / "site", root / "output"
            base.mkdir(); site.mkdir()
            for name in payload.ROOT_FILES:
                (base / name).write_bytes(b"fixture")
            for name in ("Lib", "DLLs", "tcl"):
                (base / name).mkdir()
            info = site / "demo-1.dist-info"
            info.mkdir()
            (info / "METADATA").write_text("Metadata-Version: 2.1\nName: demo\nVersion: 1\n")
            (info / "WHEEL").write_text("Wheel-Version: 1.0\n")
            (info / "LICENSE").write_text("Fixture licence")
            original = site / "demo.py"
            original.write_bytes(b"changed")
            encoded = base64.urlsafe_b64encode(hashlib.sha256(b"correct").digest()).rstrip(b"=").decode()
            (info / "RECORD").write_text("demo.py,sha256=" + encoded + ",7\n"
                "demo-1.dist-info/METADATA,,\ndemo-1.dist-info/WHEEL,,\n"
                "demo-1.dist-info/LICENSE,,\ndemo-1.dist-info/RECORD,,\n")
            requirement = root / "requirements.txt"
            requirement.write_text("--only-binary=:all:\ndemo==1\n")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                payload.prepare(base, site, [requirement], output)
            self.assertEqual(original.read_bytes(), b"changed")

    @unittest.skipIf(SUPPORTED, "the supported platform runs the payload checks above")
    def test_unsupported_platform_refuses_before_touching_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(ValueError, "Run with Windows CPython 3.12"):
                payload.prepare(root / "base", root / "site", [], root / "output")
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
