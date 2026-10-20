"""Focused source-bound masking: preserve original records and all other data."""
import importlib.util
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("mask_selected_comparator", HERE / "compare_arms_r21.py")
C = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = C
spec.loader.exec_module(C)


class Masks(unittest.TestCase):
    def test_nested_mask_preserves_input_and_other_quantities(self):
        original = {"items": [{"x": [1, 3], "y": 7}, {"x": [2, 5], "y": 8}], "other": [4, 9]}
        masked = C.scrub_quantities(original, {("mesh", "items", "0", "x")})
        self.assertEqual(original["items"][0]["x"], [1, 3])
        self.assertEqual(masked["items"][0]["y"], 7)
        self.assertEqual(masked["items"][1], original["items"][1])
        self.assertIs(masked["other"], original["other"])
        self.assertIs(masked["items"][1], original["items"][1])
        self.assertEqual(masked["items"][0]["x"], "<independently-judged-quantity>")

    def test_contained_masks_do_not_reenter_removed_quantity(self):
        original = {"cells": [{"value": [1, 4]}], "untouched": 5}
        masked = C.scrub_quantities(original, {("mesh", "cells"), ("mesh", "cells", "0", "value")})
        self.assertEqual(masked, {"cells": "<independently-judged-quantity>", "untouched": 5})
        self.assertEqual(original["cells"], [{"value": [1, 4]}])
        self.assertIs(C.scrub_quantities(original, set()), original)

    def test_sibling_masks_preserve_alias_safety(self):
        original = {"nested": {"x": 1, "y": 2, "z": 3}}
        masked = C.scrub_quantities(original, {("mesh", "nested", "x"), ("mesh", "nested", "y")})
        self.assertEqual(original, {"nested": {"x": 1, "y": 2, "z": 3}})
        self.assertEqual(masked["nested"]["z"], 3)
        self.assertEqual(masked["nested"]["x"], masked["nested"]["y"])

    def test_production_walker_never_infers_legacy_header_allowance(self):
        before = {C.DEVIATION_FIELD: [hex(1), hex(1)], C.WIDTH_FIELD: [hex(2), hex(1)],
                  "cells": [{C.DEVIATION_FIELD: [hex(1), hex(1)]}]}
        after = dict(before, **{C.DEVIATION_FIELD: [hex(2**65 + 1), hex(2**65)]})
        plain = C.Comparer({}, {}, legacy_headers=False)
        plain.compare(before, after, ("mesh",))
        field = plain.fields["mesh." + C.DEVIATION_FIELD]
        self.assertEqual(field["unbound_changes"], 1)
        self.assertEqual(plain.counts["addendum_e_headers"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
