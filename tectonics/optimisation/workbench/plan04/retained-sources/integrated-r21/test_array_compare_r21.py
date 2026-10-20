"""Focused bounded-array behavioural checks; no scientific runtime imports."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
A = load("array_compare_r21", HERE / "array_compare_r21.py")
C = load("array_test_comparator", HERE.parent / "causal-r20" / "compare_arms_r20.py")


class Arrays(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.before, self.after = self.root / "before", self.root / "after"
        for folder in (self.before, self.after):
            (folder / "arrays").mkdir(parents=True)
        self.old_block = A.BLOCK_BYTES
        A.BLOCK_BYTES = 24

    def tearDown(self):
        A.BLOCK_BYTES = self.old_block
        self.temp.cleanup()

    def compare(self, before, after, *, name="test", ids=None, layouts=None):
        docs = []
        for folder, data in ((self.before, before), (self.after, after)):
            data = np.asarray(data, dtype="<f8")
            data.tofile(folder / "arrays" / "0000.bin")
            docs.append({"arrays": [{"name": name, "dtype": "<f8", "shape": list(data.shape),
                                     "file": "0000.bin"}]})
        bound = {name: ("bound", "independent fixture")}
        result = A.compare(C, *docs, self.before, self.after, bound, bound,
                           *(ids or (None, None)), layouts=layouts)
        return result

    def test_boundaries_and_actual_change(self):
        before = np.arange(17, dtype="<f8")
        after = before.copy()
        after[[2, 3, 16]] += 0.25
        rows, review = self.compare(before, after)
        self.assertEqual(rows["test"]["changed"], 3)
        self.assertEqual(rows["test"]["max_abs"], 0.25)
        self.assertEqual(len(review), 1)

    def test_row_join_crosses_blocks(self):
        before = np.arange(20, dtype="<f8").reshape(4, 5)
        after = before[[2, 0, 3, 1]]
        rows, review = self.compare(before, after, name="exterior-fv:state",
                                    ids=(["a", "b", "c", "d"], ["c", "a", "d", "b"]))
        self.assertTrue(rows["exterior-fv:state"]["equal"])
        self.assertEqual(rows["exterior-fv:state"]["paired"], "cell_id")
        self.assertEqual(review, [])

    def test_layout_absence_prevents_equal_acceptance(self):
        rows, review = self.compare([1.0, 2.0], [1.0, 2.0], layouts=({}, {}))
        self.assertIsNone(rows["test"]["equal"])
        self.assertTrue(rows["test"]["bytes_equal"])
        self.assertIn("no independent row-layout evidence", review[0])

    def test_fixed_domain_and_transport_correspondence(self):
        domain = {"kind": "fixed-domain", "identity": {"plan": "proved-plan"}, "axis": None}
        rows, review = self.compare([1, 2], [1, 2], layouts=({"test": domain}, {"test": domain}))
        self.assertTrue(rows["test"]["equal"])
        self.assertEqual(review, [])
        changed = dict(domain, identity={"plan": "another-plan"})
        rows, review = self.compare([1, 2], [1, 2], layouts=({"test": domain}, {"test": changed}))
        self.assertIsNone(rows["test"]["equal"])
        self.assertTrue(review)
        left = {"kind": "transport-cell", "identity": ["a", "b"], "axis": 0}
        right = {"kind": "transport-cell", "identity": ["b", "a"], "axis": 0}
        rows, review = self.compare([[1, 2], [3, 4]], [[3, 4], [1, 2]],
                                   layouts=({"test": left}, {"test": right}))
        self.assertTrue(rows["test"]["equal"])
        self.assertEqual(review, [])

    def test_nonfinite_and_signed_zero(self):
        rows, review = self.compare([np.nan, 1], [np.nan, 1])
        self.assertIsNone(rows["test"]["equal"])
        self.assertEqual(rows["test"]["nonfinite"], [1, 1])
        self.assertIn("no finite equality", review[0])
        rows, review = self.compare([-0.0], [0.0])
        self.assertFalse(rows["test"]["equal"])
        self.assertEqual(rows["test"]["changed"], 1)
        self.assertEqual(len(review), 1)

    def test_large_ulp_distance_no_signed_overflow(self):
        rows, _ = self.compare([-np.finfo(float).max], [np.finfo(float).max])
        self.assertEqual(rows["test"]["max_ulps"], C.ulps(-np.finfo(float).max, np.finfo(float).max))
        self.assertGreater(rows["test"]["max_ulps"], 2**63)

    def test_empty_and_truncated(self):
        rows, review = self.compare([], [])
        self.assertTrue(rows["test"]["equal"])
        self.assertEqual(review, [])
        path = self.before / "arrays" / "0000.bin"
        with self.assertRaisesRegex(ValueError, "shortened"):
            list(A.blocks(path, np.dtype("<f8"), [1]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
