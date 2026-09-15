"""Exact-output algorithm tests; preserved-original checks run when available."""
from __future__ import annotations

from collections import defaultdict
import importlib.util
import os
from pathlib import Path
import sys
import unittest

import numpy as np
import shapely

import build_stage6c_100m as candidate


def load_original():
    root = os.environ.get("DIADEM_ALGORITHM_REFERENCE_ENGINE")
    directory = Path(root) if root else Path(__file__).resolve().parents[3] / "original" / "engine"
    path = directory / "build_stage6c_100m.py"
    if not path.is_file():
        return None
    name = "_original_stage6c_topology_scoring"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ORIGINAL = load_original()


class ScoringAlgorithmTests(unittest.TestCase):
    @staticmethod
    def rules():
        result = [{"transform_code": "DEFERRED"}, {"transform_code": "BINARY"}]
        result.extend({"transform_code": "CONSTANT", "p0": p0} for p0 in (-1.0, -0.0, 0.4, 1.0, 2.0))
        for code in ("HIGH_BETTER", "LOW_BETTER"):
            result.extend({"transform_code": code, "p0": p0, "p1": p1}
                          for p0, p1 in ((0.0, 1.0), (-2.7, 19.3), (1.0, 1.0), (2.0, -1.0), (0.0, 1e-14)))
        result.extend({"transform_code": "RANGE_TRAPEZOID", "p0": p0, "p1": p1, "p2": p2, "p3": p3}
                      for p0, p1, p2, p3 in ((0.0, 0.0, 0.55, 1.0), (0.0, 0.45, 1.0, 1.0),
                                            (0.0, 0.25, 5.0, 15.0), (1.0, 1.0, 1.0, 1.0),
                                            (0.0, 1e-14, 0.9, 1.0), (2.0, -1.0, 0.5, 0.25)))
        return result

    def assert_exact(self, actual, expected):
        self.assertEqual(actual.dtype, expected.dtype)
        self.assertEqual(actual.shape, expected.shape)
        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_bulk_transforms_match_scalar_bits_including_branch_edges(self):
        random = np.random.default_rng(230904)
        values = np.concatenate((random.uniform(-20.0, 40.0, 1003),
                                 [-np.inf, np.inf, np.nan, -0.0, 0.0, 1.0, 1e-15]))
        for rule in self.rules():
            endpoints = [value for key, value in rule.items() if key.startswith("p")]
            extended = np.concatenate((values, endpoints,
                                       np.nextafter(endpoints, -np.inf), np.nextafter(endpoints, np.inf)))
            with self.subTest(rule=rule):
                expected = np.array([candidate.transform_score(float(value), rule) or 0.0 for value in extended])
                self.assert_exact(candidate._transform_scores_zero(extended, rule), expected)

    @unittest.skipUnless(ORIGINAL, "preserved original engine not available")
    def test_bulk_transforms_match_separately_imported_original(self):
        values = np.concatenate((np.random.default_rng(19).normal(size=157),
                                 [np.nan, -np.inf, np.inf, -0.0, 0.0, 1.0]))
        for rule in self.rules():
            expected = np.array([ORIGINAL.transform_score(float(value), rule) or 0.0 for value in values])
            self.assert_exact(candidate._transform_scores_zero(values, rule), expected)

    def test_candidate_scores_reference_selection_and_input_preservation(self):
        random = np.random.default_rng(777)
        inputs = [random.uniform(-2.0, 45.0, 100) for _ in range(3)]
        inputs[0][:5] = [np.nan, np.inf, -np.inf, 0.0, -0.0]
        domain = random.uniform(0, 1, 100)
        valid = random.random(100) > 0.3
        before = [value.tobytes() for value in (*inputs, domain, valid)]
        all_rules = self.rules()
        for index in range(len(all_rules)):
            policy = {"components": dict(zip(("TERRAIN_SUPPORT", "HYDROLOGY_SUPPORT", "FLOOD_COMPATIBILITY"),
                                              (all_rules[index], all_rules[(index + 3) % len(all_rules)],
                                               all_rules[(index + 7) % len(all_rules)])))}
            actual = candidate.candidate_cell_scores(*inputs, domain, valid, policy, algorithm="vectorized")
            expected = candidate.candidate_cell_scores(*inputs, domain, valid, policy, algorithm="reference")
            self.assert_exact(actual, expected)
            if ORIGINAL:
                self.assert_exact(actual, ORIGINAL.candidate_cell_scores(*inputs, domain, valid, policy))
        self.assertEqual(before, [value.tobytes() for value in (*inputs, domain, valid)])

    def test_non_numeric_dtype_uses_scalar_semantics(self):
        values = np.array(["-1.0", "0.4", "nan", "inf"], dtype=object)
        rule = {"transform_code": "LOW_BETTER", "p0": 0.0, "p1": 1.0}
        expected = np.array([candidate.transform_score(float(value), rule) or 0.0 for value in values])
        self.assert_exact(candidate._transform_scores_zero(values, rule), expected)
        with self.assertRaises(TypeError):
            candidate._transform_scores_zero(np.array([None], dtype=object), rule)

    def test_empty_nonfinite_unknown_and_invalid_selection(self):
        unknown = {"transform_code": "UNKNOWN"}
        self.assert_exact(candidate._transform_scores_zero(np.array([]), unknown), np.array([]))
        self.assert_exact(candidate._transform_scores_zero(np.array([np.nan, np.inf]), unknown), np.zeros(2))
        with self.assertRaisesRegex(ValueError, "Unknown transform"):
            candidate._transform_scores_zero(np.array([0.0]), unknown)
        with self.assertRaisesRegex(ValueError, "Unsupported candidate scoring algorithm"):
            candidate.candidate_cell_scores(*(np.zeros(1),) * 4, np.ones(1, dtype=bool), {}, algorithm="invalid")

    def test_integer_and_boolean_inputs_match_float_conversion(self):
        rule = {"transform_code": "HIGH_BETTER", "p0": -2.0, "p1": 4.0}
        for values in (np.array([-3, 0, 4], dtype=np.int64), np.array([0, 2, 2**63], dtype=np.uint64),
                       np.array([False, True]), np.array([-0.0, 0.1, 0.3], dtype=np.float32)):
            expected = np.array([candidate.transform_score(float(value), rule) or 0.0 for value in values])
            self.assert_exact(candidate._transform_scores_zero(values, rule), expected)


class TopologyAlgorithmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = candidate.ExactSurfaceIndex.__new__(candidate.ExactSurfaceIndex)
        cls.index.carrier_baronies = np.full((1860, 2200), 7, dtype=np.int32)
        cls.index.explicit_by_carrier = defaultdict(list)
        cls.index.partial_carriers_by_row = defaultdict(list)
        for row in (0, 1, 2, 5, 1859):
            for col in (0, 5, 10, 11, 50, 1000, 2199):
                carrier = row * 2200 + col
                # Boundary-covered, holed, and overlapping fragments retain
                # original last-fragment-wins ordering.
                outer = shapely.box(col, row, col + 0.75, row + 1.0)
                hole = shapely.box(col + 0.2, row + 0.2, col + 0.4, row + 0.4)
                cls.index.explicit_by_carrier[carrier] = [
                    (11, outer.difference(hole)),
                    (13, shapely.box(col + 0.55, row + 0.05, col + 0.95, row + 0.95)),
                ]
                cls.index.partial_carriers_by_row[row].append(carrier)
        cls.index.partial_carriers = set(cls.index.explicit_by_carrier)

    @unittest.skipUnless(ORIGINAL, "preserved original engine not available")
    def test_windows_match_original_exact_geometry_predicates(self):
        windows = [(0, 0, 20, 120), (8, 96, 18, 19), (50, 500, 10, 10),
                   (100, 100, 7, 9), (-3, -4, 14, 18), (18585, 21985, 20, 20)]
        random = np.random.default_rng(171)
        for _ in range(40):
            row = int(random.choice([0, 1, 2, 5])) * 10 + int(random.integers(-4, 4))
            col = int(random.choice([0, 5, 10, 11, 50, 1000])) * 10 + int(random.integers(-4, 4))
            windows.append((row, col, int(random.integers(1, 30)), int(random.integers(1, 30))))
        for window in windows:
            with self.subTest(window=window):
                expected = ORIGINAL.ExactSurfaceIndex.rasterize_window(self.index, *window)
                actual = self.index.rasterize_window(*window)
                self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_result_does_not_alias_source_carrier_array(self):
        before = self.index.carrier_baronies.tobytes()
        result = self.index.rasterize_window(0, 0, 20, 120)
        result[:] = 9999
        self.assertEqual(self.index.carrier_baronies.tobytes(), before)


if __name__ == "__main__":
    unittest.main()
