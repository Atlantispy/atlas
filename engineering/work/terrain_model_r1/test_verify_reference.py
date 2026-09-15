"""Strict logical parity and post-receipt drift checks, without a terrain run."""
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import verify_reference as v


class VerificationReceiptTests(unittest.TestCase):
    def test_strict_parity_distinguishes_signed_zero_and_numeric_types(self):
        for first, second in ((0.0, -0.0), (True, 1), (1, 1.0)):
            with self.subTest(first=first, second=second):
                self.assertNotEqual(v.canonical_bytes(first), v.canonical_bytes(second))

    def test_strict_parity_ignores_mapping_order_only(self):
        self.assertEqual(v.canonical_bytes({"a": [1, 2], "b": 3}),
                         v.canonical_bytes({"b": 3, "a": [1, 2]}))
        self.assertNotEqual(v.canonical_bytes([1, 2]), v.canonical_bytes([2, 1]))

    def test_strict_parity_rejects_nonfinite_values(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                v.canonical_bytes({"result": value})

    def test_readback_is_strict_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            v.write_new_json(path, {"result": -0.0})
            self.assertEqual(v.canonical_bytes(v.load_json(path)), b'{"result":-0.0}')
            with self.assertRaises(FileExistsError):
                v.write_new_json(path, {})

    def test_readback_rejects_signed_zero_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(v, "load_json", return_value={"result": 0.0}):
                with self.assertRaisesRegex(ValueError, "Readback failed"):
                    v.write_new_json(Path(directory) / "receipt.json", {"result": -0.0})

    def test_post_receipt_drift_check_accepts_unchanged_bindings(self):
        pin = {"path": "fixture", "sha256": "a"}
        with patch.object(v, "collect", return_value=["source"]), \
             patch.object(v, "implementation_pins", return_value=["code"]), \
             patch.object(v, "file_pin", return_value=pin):
            v.assert_unchanged("workspace", ["source"], "here", ["code"], [pin])

    def test_post_receipt_drift_check_rejects_source_or_new_code(self):
        for source, code in ((["changed"], ["code"]), (["source"], ["code", "new"])):
            with self.subTest(source=source, code=code), \
                 patch.object(v, "collect", return_value=source), \
                 patch.object(v, "implementation_pins", return_value=code):
                with self.assertRaisesRegex(ValueError, "Source/implementation changed"):
                    v.assert_unchanged("workspace", ["source"], "here", ["code"])

    def test_post_receipt_drift_check_rejects_product_change(self):
        with patch.object(v, "collect", return_value=["source"]), \
             patch.object(v, "implementation_pins", return_value=["code"]), \
             patch.object(v, "file_pin", return_value={"path": "fixture", "sha256": "b"}):
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                v.assert_unchanged("workspace", ["source"], "here", ["code"],
                                   [{"path": "fixture", "sha256": "a"}])


if __name__ == "__main__":
    unittest.main()
