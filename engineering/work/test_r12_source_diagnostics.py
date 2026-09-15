"""Focused source-failure diagnostics; temporary fixtures only, no science run."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from work.generator_runtime_r12 import provenance


class SourceDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r12-source-diagnostics-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_checked_reports_path_and_full_expected_actual_hashes(self):
        path = self.root / "source.py"
        raw = b"# source fixture\n"
        path.write_bytes(raw)
        actual = hashlib.sha256(raw).hexdigest()
        self.assertEqual(provenance.checked(path, actual), raw)
        expected = "1" * 64
        with self.assertRaises(ValueError) as error:
            provenance.checked(path, expected)
        message = str(error.exception)
        for detail in (str(path), "no silent rebind", f"expected_sha256={expected}",
                       f"actual_sha256={actual}"):
            self.assertIn(detail, message)
        self.assertEqual(path.read_bytes(), raw)

    def test_checked_retains_path_and_before_after_read_size_guards(self):
        with self.assertRaisesRegex(ValueError, "absolute non-traversing"):
            provenance.checked(Path("relative.py"))
        path = self.root / "source.py"
        path.write_bytes(b"12")
        with patch.object(provenance, "LIMIT", 1), \
                self.assertRaisesRegex(ValueError, "bounded source file"):
            provenance.checked(path)
        with patch.object(provenance, "LIMIT", 2), \
                patch.object(Path, "read_bytes", return_value=b"123"), \
                self.assertRaisesRegex(ValueError, "bounded source file required after read"):
            provenance.checked(path)

    def test_loaded_module_reports_path_hashes_and_missing_capture(self):
        bundle = SimpleNamespace(source_sha256=provenance.SCIENCE_SHA,
                                 identity={"runtime": {}})
        identity = provenance.execution_identity(bundle)
        path = provenance.__file__
        expected = identity["sources"][path]
        for actual in ("2" * 64, None):
            with self.subTest(actual=actual), \
                    patch.object(provenance, "_R12_EXECUTED_SHA256", actual), \
                    self.assertRaises(ValueError) as error:
                provenance.execution_identity(bundle)
            for detail in ("module=work.generator_runtime_r12.provenance", f"path={path}",
                           f"expected_sha256(current file)={expected}",
                           f'actual_sha256(loaded module)={actual or "<missing capture>"}'):
                self.assertIn(detail, str(error.exception))
        self.assertEqual(provenance.execution_identity(bundle), identity)

    def test_inventory_reports_changed_missing_and_added_files(self):
        source_root = self.root / "r11"
        source_root.mkdir()
        raw = b"# sealed fixture\n"
        expected = hashlib.sha256(raw).hexdigest()
        pins = {}
        for index in range(49):
            path = source_root / f"source_{index:02d}.py"
            path.write_bytes(raw)
            pins[str(path)] = expected
        identity = {"r11_sources": pins}
        science_sha = provenance.sha(identity)
        seal = self.root / "seal.json"
        seal_raw = json.dumps({"source_identity": identity,
                               "source_sha256": science_sha}).encode()
        seal.write_bytes(seal_raw)
        changed = source_root / "source_00.py"
        added = source_root / "additional.py"
        with patch.object(provenance, "R11", source_root), \
                patch.object(provenance, "SEAL", seal), \
                patch.object(provenance, "SEAL_SHA", hashlib.sha256(seal_raw).hexdigest()), \
                patch.object(provenance, "SCIENCE_SHA", science_sha):
            for case in ("changed", "missing", "added"):
                if case == "changed":
                    changed.write_bytes(b"# changed fixture\n")
                    path, wanted = changed, expected
                    observed = hashlib.sha256(changed.read_bytes()).hexdigest()
                elif case == "missing":
                    changed.unlink()
                    path, wanted, observed = changed, expected, "<missing file>"
                else:
                    changed.write_bytes(raw)
                    added.write_bytes(raw)
                    path, wanted, observed = added, "<not inventoried>", expected
                with self.subTest(case=case), self.assertRaises(ValueError) as error:
                    provenance.load_science()
                for detail in ("sealed R11 inventory changed", f"path={path}",
                               f"expected_sha256={wanted}", f"actual_sha256={observed}"):
                    self.assertIn(detail, str(error.exception))


if __name__ == "__main__":
    unittest.main()
