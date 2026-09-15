"""Tiny temporary-fixture tests; no historical producer or world data is used."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np

import compare


class CompareProductsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="history-a-compare-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference, self.candidate = self.root / "reference", self.root / "candidate"
        self.reference.mkdir()
        self.candidate.mkdir()
        self.arrays = {}
        for name in compare.ARRAY_NAMES:
            if name == "approved_peak_reference_names":
                value = np.array(["Peak A", "Peak B"], dtype="<U40")
            elif name == "structural_model_domain_mask":
                value = np.array([[True, False], [False, True]], dtype=np.bool_)
            elif name.endswith("_id"):
                value = np.arange(6, dtype=np.int16).reshape(2, 3)
            elif name in ("x_km", "y_km", "approved_peak_reference_uncertainty_km"):
                value = np.array([0.0, 1.25], dtype=np.float64)
            elif name == "approved_peak_reference_xy_km":
                value = np.arange(4, dtype=np.float64).reshape(2, 2)
            else:
                value = np.arange(6, dtype=np.float64).reshape(2, 3)
            self.arrays[name] = value
        for directory in (self.reference, self.candidate):
            for suffix in compare.JSON_PRODUCTS:
                self.write_json(directory, suffix, {"kind": suffix, "ordered": [1, 2], "nested": {"flag": True}})
            self.write_arrays(directory, self.arrays)

    def path(self, directory: Path, suffix: str) -> Path:
        return directory / (compare.PREFIX + suffix)

    def write_json(self, directory: Path, suffix: str, value: object) -> None:
        self.path(directory, suffix).write_text(json.dumps(value), encoding="utf-8")

    def write_arrays(self, directory: Path, arrays: dict, *, lineage: bool = True) -> None:
        np.savez_compressed(self.path(directory, "structural-fields.npz"), **arrays)
        if lineage:
            self.write_json(directory, "lineage.json", {"array_hashes": {
                name: hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()
                for name, array in arrays.items()
            }, "status": "REVIEW_ONLY"})

    def run_comparison(self) -> dict:
        return compare.compare_products(self.reference, self.candidate)

    def archive_rewrite(self, edit) -> None:
        path = self.path(self.candidate, "structural-fields.npz")
        with zipfile.ZipFile(path) as archive:
            members = [(info.filename, archive.read(info)) for info in archive.infolist()]
        with warnings.catch_warnings(), zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            warnings.simplefilter("ignore", UserWarning)
            for name, payload in edit(members):
                archive.writestr(name, payload)

    def test_exact_seventeen_arrays_and_six_json_pass(self) -> None:
        result = self.run_comparison()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["files"]), 7)
        self.assertEqual(set(result["arrays"]), set(compare.ARRAY_NAMES))
        for role in ("reference", "candidate"):
            self.assertEqual(result["lineage_array_hashes"][role]["status"], "PASS")
        for name, record in result["arrays"].items():
            self.assertEqual(record["candidate"]["sha256"], hashlib.sha256(np.ascontiguousarray(self.arrays[name]).tobytes()).hexdigest())
        json.dumps(result, allow_nan=False)

    def test_png_differences_are_not_compared_or_visual_pass(self) -> None:
        for directory, value in ((self.reference, b"not-an-image"), (self.candidate, b"different")):
            (directory / "checkpoint1-history-a-review.png").write_bytes(value)
        result = self.run_comparison()
        self.assertEqual(result["status"], "PASS")
        self.assertIn("not compared or conferred", result["scope"])

    def test_json_object_order_and_format_are_not_semantic(self) -> None:
        self.write_json(self.candidate, "events.json", {"nested": {"flag": True}, "ordered": [1, 2], "kind": "events.json"})
        self.assertEqual(self.run_comparison()["status"], "PASS")

    def test_npz_member_order_is_not_semantic(self) -> None:
        self.write_arrays(self.candidate, dict(reversed(list(self.arrays.items()))))
        self.assertEqual(self.run_comparison()["status"], "PASS")

    def test_fortran_layout_compares_c_order_content(self) -> None:
        values = {name: np.asfortranarray(value) if value.ndim == 2 else value for name, value in self.arrays.items()}
        self.write_arrays(self.candidate, values)
        self.assertEqual(self.run_comparison()["status"], "PASS")

    def test_json_scalar_types_are_strict(self) -> None:
        for left, right in ((True, 1), (1, 1.0), (False, 0), (None, "None")):
            with self.subTest(left=left, right=right):
                self.write_json(self.reference, "events.json", {"value": left})
                self.write_json(self.candidate, "events.json", {"value": right})
                result = self.run_comparison()
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["files"][compare.PREFIX + "events.json"]["differences"][0]["path"], "/value")

    def test_json_signed_zero_is_strict(self) -> None:
        self.write_json(self.reference, "events.json", {"v": 0.0})
        self.write_json(self.candidate, "events.json", {"v": -0.0})
        self.assertEqual(self.run_comparison()["status"], "FAIL")

    def test_ordered_lists_and_object_inventory_are_strict(self) -> None:
        for value in ({"kind": "events.json", "ordered": [2, 1], "nested": {"flag": True}},
                      {"kind": "events.json", "ordered": [1, 2]},
                      {"kind": "events.json", "ordered": [1, 2, 3], "nested": {"flag": True}}):
            with self.subTest(value=value):
                self.write_json(self.candidate, "events.json", value)
                self.assertEqual(self.run_comparison()["status"], "FAIL")

    def test_duplicate_json_keys_rejected(self) -> None:
        for payload in ('{"a":1,"a":1}', '{"outer":{"a":1,"a":2}}'):
            with self.subTest(payload=payload):
                self.path(self.candidate, "events.json").write_text(payload, encoding="utf-8")
                result = self.run_comparison()
                self.assertEqual(result["status"], "FAIL")
                self.assertIn("Duplicate JSON key", str(result["files"][compare.PREFIX + "events.json"]["errors"]))

    def test_nonfinite_json_constants_and_overflow_rejected(self) -> None:
        for token in ("NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"):
            with self.subTest(token=token):
                self.path(self.candidate, "events.json").write_text('{"v":' + token + '}', encoding="utf-8")
                self.assertEqual(self.run_comparison()["status"], "FAIL")

    def test_missing_reference_and_candidate_files_fail_closed(self) -> None:
        for directory in (self.reference, self.candidate):
            with self.subTest(directory=directory):
                path = self.path(directory, "sections.geojson")
                original = path.read_bytes()
                path.unlink()
                self.assertEqual(self.run_comparison()["status"], "FAIL")
                path.write_bytes(original)

    def test_array_value_difference_has_no_tolerance(self) -> None:
        values = dict(self.arrays)
        values["x_km"] = values["x_km"].copy()
        values["x_km"][1] = np.nextafter(values["x_km"][1], np.inf)
        self.write_arrays(self.candidate, values)
        result = self.run_comparison()
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["arrays"]["x_km"]["raw_contiguous_bytes_exact"])

    def test_array_signed_zero_bits_matter(self) -> None:
        values = dict(self.arrays)
        values["x_km"] = np.array([-0.0, 1.25], dtype=np.float64)
        self.write_arrays(self.candidate, values)
        self.assertFalse(self.run_comparison()["arrays"]["x_km"]["raw_contiguous_bytes_exact"])

    def test_identical_nan_payload_passes_but_different_payload_fails(self) -> None:
        values = dict(self.arrays)
        values["x_km"] = np.array([0x7ff8000000000001, 0x3ff0000000000000], dtype=np.uint64).view(np.float64)
        for directory in (self.reference, self.candidate):
            self.write_arrays(directory, values)
        self.assertEqual(self.run_comparison()["status"], "PASS")
        values["x_km"] = values["x_km"].copy()
        values["x_km"].view(np.uint64)[0] += np.uint64(1)
        self.write_arrays(self.candidate, values)
        self.assertEqual(self.run_comparison()["status"], "FAIL")

    def test_array_shape_and_dtype_are_strict(self) -> None:
        for value in (self.arrays["fault_block_id"].reshape(-1), self.arrays["fault_block_id"].astype(np.int32)):
            with self.subTest(shape=value.shape, dtype=value.dtype):
                values = dict(self.arrays)
                values["fault_block_id"] = value
                self.write_arrays(self.candidate, values)
                self.assertEqual(self.run_comparison()["status"], "FAIL")

    def test_unicode_width_and_byte_order_are_strict(self) -> None:
        for name, value in (("approved_peak_reference_names", self.arrays["approved_peak_reference_names"].astype("<U41")),
                            ("x_km", self.arrays["x_km"].astype(">f8"))):
            with self.subTest(name=name):
                values = dict(self.arrays)
                values[name] = value
                self.write_arrays(self.candidate, values)
                result = self.run_comparison()
                self.assertEqual(result["status"], "FAIL")
                self.assertFalse(result["arrays"][name]["dtype_exact"])

    def test_missing_extra_and_duplicate_npz_members_rejected(self) -> None:
        for edit in (lambda rows: rows[1:], lambda rows: rows + [("extra.npy", rows[0][1])], lambda rows: rows + [rows[0]]):
            with self.subTest(edit=edit):
                self.write_arrays(self.candidate, self.arrays)
                self.archive_rewrite(edit)
                self.assertEqual(self.run_comparison()["status"], "FAIL")

    def test_identically_missing_keys_in_both_archives_still_fail(self) -> None:
        values = dict(self.arrays)
        values.pop("x_km")
        for directory in (self.reference, self.candidate):
            self.write_arrays(directory, values)
        self.assertEqual(self.run_comparison()["status"], "FAIL")

    def test_object_array_rejected_without_pickle(self) -> None:
        values = dict(self.arrays)
        values["x_km"] = np.array([{"unsafe": True}], dtype=object)
        self.write_arrays(self.candidate, values, lineage=False)
        with mock.patch("pickle.load", side_effect=AssertionError("pickle used")), mock.patch("pickle.loads", side_effect=AssertionError("pickle used")):
            result = self.run_comparison()
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("Object/pickle array forbidden", result["arrays"]["x_km"]["error"])

    def test_corrupt_archive_fails_closed(self) -> None:
        path = self.path(self.candidate, "structural-fields.npz")
        path.write_bytes(path.read_bytes()[:-12])
        self.assertEqual(self.run_comparison()["status"], "FAIL")

    def test_corrupt_compressed_member_fails_closed(self) -> None:
        path = self.path(self.candidate, "structural-fields.npz")
        with zipfile.ZipFile(path) as archive:
            info = archive.infolist()[0]
        data = bytearray(path.read_bytes())
        offset = info.header_offset + 30 + len(info.filename.encode())
        extra_length = int.from_bytes(data[info.header_offset + 28:info.header_offset + 30], "little")
        data[offset + extra_length + max(0, info.compress_size // 2)] ^= 0x40
        path.write_bytes(data)
        self.assertEqual(self.run_comparison()["status"], "FAIL")

    def test_trailing_npy_payload_rejected(self) -> None:
        self.archive_rewrite(lambda rows: [(name, payload + b"x" if name == "x_km.npy" else payload) for name, payload in rows])
        result = self.run_comparison()
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("payload length mismatch", result["arrays"]["x_km"]["error"])

    def test_oversized_declared_shape_rejected_before_allocation(self) -> None:
        stream = io.BytesIO()
        np.lib.format.write_array_header_1_0(stream, {"descr": "<f8", "fortran_order": False, "shape": (10**12,)})
        self.archive_rewrite(lambda rows: [(name, stream.getvalue() if name == "x_km.npy" else payload) for name, payload in rows])
        result = self.run_comparison()
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("payload length mismatch", result["arrays"]["x_km"]["error"])

    def test_lineage_missing_extra_wrong_hash_and_type_fail_even_if_both_match(self) -> None:
        lineage = json.loads(self.path(self.reference, "lineage.json").read_text(encoding="utf-8"))
        for kind in ("missing", "extra", "hash", "type"):
            with self.subTest(kind=kind):
                changed = json.loads(json.dumps(lineage))
                if kind == "missing":
                    changed["array_hashes"].pop("x_km")
                elif kind == "extra":
                    changed["array_hashes"]["unknown"] = "0" * 64
                elif kind == "hash":
                    changed["array_hashes"]["x_km"] = "0" * 64
                else:
                    changed["array_hashes"]["x_km"] = 1
                for directory in (self.reference, self.candidate):
                    self.write_json(directory, "lineage.json", changed)
                result = self.run_comparison()
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["lineage_array_hashes"]["candidate"]["status"], "FAIL")

    def test_lineage_nonobject_fails_closed(self) -> None:
        for directory in (self.reference, self.candidate):
            self.write_json(directory, "lineage.json", {"array_hashes": []})
        self.assertEqual(self.run_comparison()["status"], "FAIL")

    def test_changed_file_identity_fails_closed(self) -> None:
        original = compare._identity
        target = self.path(self.candidate, "events.json")
        calls = 0

        def identity(path):
            nonlocal calls
            result = original(path)
            if path == target:
                calls += 1
                if calls > 1:
                    result["sha256"] = "0" * 64
            return result

        with mock.patch.object(compare, "_identity", side_effect=identity):
            result = self.run_comparison()
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["files"][compare.PREFIX + "events.json"]["candidate_unchanged"])

    def test_comparison_does_not_modify_or_add_files(self) -> None:
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(self.run_comparison()["status"], "PASS")
        after = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_difference_report_is_bounded_and_counts_all(self) -> None:
        self.write_json(self.reference, "events.json", list(range(100)))
        self.write_json(self.candidate, "events.json", list(range(1, 101)))
        entry = self.run_comparison()["files"][compare.PREFIX + "events.json"]
        self.assertEqual(entry["difference_count"], 100)
        self.assertEqual(len(entry["differences"]), compare.MAX_DIFFERENCES)
        self.assertTrue(entry["differences_truncated"])


if __name__ == "__main__":
    unittest.main()
