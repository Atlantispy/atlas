"""Exact settled-energy controls on native heat metadata and sibling captured arrays.

Synthetic records only. Mesh identities and signed cell/face incidence are supplied independently.
Run with the science interpreter and -B; no Atlas producer, store, worker or interval is started.
"""
import copy
import importlib.util
import sys
import unittest
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEV = HERE.parent / "n9-tools-r21"
if not sys.dont_write_bytecode:
    raise SystemExit("run with -B: no bytecode may be written beside the tool sources")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


Q = load("settled_field_contracts", DEV / "field_contracts.py")
C = load("settled_compare_arms", DEV / "compare_arms_r21.py")
IDENTITY = "ADDENDUM_5_4_SETTLED_ENERGY_IDENTITY"
RESIDUALS = tuple(Q.RESIDUALS_54[1:])


def pair(value):
    value = Fraction(value)
    return [hex(value.numerator), hex(value.denominator)]


def fixture(geometry="geometry-a", correction=Fraction(0)):
    # Deliberately distinct table orders; signs and stored IDs determine the outward energy.
    mesh = dict(schema=Q.MESH_SCHEMA, geometry_id=geometry,
                physical_geometry_family=Q.DIFFERENTIAL_FAMILY,
                cells=[dict(cell_id="b", faces=[["shared", -1], ["edge-b", 1]]),
                       dict(cell_id="a", faces=[["shared", 1], ["edge-a", -1]])],
                faces=[dict(face_id="edge-a"), dict(face_id="shared"), dict(face_id="edge-b")])
    outward = [Fraction(3, 16), Fraction(-1, 8)]
    old = [1.0, 2.0]
    retained = [Fraction(1, 3 * 2**20) + correction, -Fraction(1, 5 * 2**21)]
    corrected = [Fraction(v) - out + r for v, out, r in zip(old, outward, retained, strict=True)]
    stored = [float(v) for v in corrected]
    projection = [Fraction(v) - n for v, n in zip(stored, corrected, strict=True)]
    metadata = dict(schema=Q.HEAT_SCHEMA, geometry_id=geometry, cell_ids=["a", "b"],
                    face_ids=["shared", "edge-b", "edge-a"],
                    exact_paired_face_energy_j=[pair(Fraction(1, 4)), pair(Fraction(1, 8)), pair(Fraction(1, 16))],
                    exact_source_energy_j=pair(0), independently_supplied_absolute_residual_target=pair(Fraction(1, 1024)),
                    exact_corrected_enthalpy_j=list(map(pair, corrected)),
                    exact_retained_solver_residual_j=list(map(pair, retained)),
                    exact_stock_projection_residual_j=list(map(pair, projection)),
                    exact_cell_storage_residual_j=[pair(r + p) for r, p in zip(retained, projection, strict=True)])
    native = dict(metadata=metadata, arrays=dict(input_enthalpy_j=old, enthalpy_j=stored, input_source_w=[0.0, 0.0]))
    return mesh, native


def violate(native, index=0):
    """Break only R=new-old+out, while retaining the target, storage and rounding identities."""
    metadata = native["metadata"]
    retained = Q.source_exact(metadata["exact_retained_solver_residual_j"][index]) + Fraction(1, 2**25)
    projection = Q.source_exact(metadata["exact_stock_projection_residual_j"][index])
    metadata["exact_retained_solver_residual_j"][index] = pair(retained)
    metadata["exact_cell_storage_residual_j"][index] = pair(retained + projection)


def evaluate(before, after, meshes=None, rows=None):
    rows = rows or Q.AddendumRows(1)
    if meshes is not None:
        rows.evaluate("mesh", *meshes)
    items, consumed = rows.evaluate("heat", before, after)
    return items, consumed, rows


def energy_items(items, verdict=None):
    return [item for item in items if item.get("row") == "5.4" and
            (verdict is None or item["verdict"] == verdict)]


class SettledEnergy(unittest.TestCase):
    def assert_valid(self, items, consumed):
        self.assertEqual([item for item in items if item["verdict"] != "EXCLUDED"], [])
        self.assertEqual(consumed, {("heat", "metadata", name) for name in RESIDUALS})

    def assert_review(self, items, consumed, code):
        self.assertEqual(energy_items(items, "FAIL"), [])
        self.assertIn(code, [item["code"] for item in energy_items(items, "REVIEW")])
        self.assertEqual(consumed, set())

    def test_complete_valid_native_arms(self):
        mesh, before = fixture()
        _, after = fixture(correction=Fraction(1, 2**26))
        self.assert_valid(*evaluate(before, after, (mesh, copy.deepcopy(mesh)))[:2])

    def test_identical_both_arm_violation_drives_comparator_fail(self):
        mesh, before = fixture()
        violate(before)
        after = copy.deepcopy(before)
        walk = C.Comparer({}, {}, legacy_headers=False)
        walk.compare(before, after, ("heat",))
        self.assertTrue(walk.fields)
        self.assertEqual(walk.counts["structure"], 0)
        self.assertEqual(walk.counts["labels"], 0)
        self.assertFalse(any(field["changed"] for field in walk.fields.values()))
        items, consumed, _ = evaluate(before, after, (mesh, copy.deepcopy(mesh)))
        failures = energy_items(items, "FAIL")
        self.assertEqual([(item["code"], item["arm"], item["cell_index"]) for item in failures],
                         [(IDENTITY, "before", 0), (IDENTITY, "after", 0)])
        review, fail = [], []
        C.judge_items(items, review, fail, "i1")
        self.assertEqual(review, [])
        self.assertEqual(len(fail), 2)
        self.assertTrue(all(IDENTITY in detail for detail in fail))
        self.assertEqual(C.exit_code("FAIL"), 1)
        self.assertEqual(consumed, set())

    def test_one_arm_identity_violation(self):
        mesh, before = fixture()
        after = copy.deepcopy(before)
        violate(after, 1)
        items, consumed, _ = evaluate(before, after, (mesh, copy.deepcopy(mesh)))
        self.assertEqual([(item["code"], item["arm"], item["cell_index"]) for item in energy_items(items, "FAIL")],
                         [(IDENTITY, "after", 1)])
        self.assertEqual(consumed, set())

    def test_missing_or_mismatched_independent_geometry_is_review(self):
        mesh, native = fixture()
        for meshes in (None, (dict(mesh, geometry_id="geometry-other"), copy.deepcopy(mesh))):
            with self.subTest(meshes_present=meshes is not None):
                items, consumed, _ = evaluate(native, copy.deepcopy(native), meshes)
                self.assert_review(items, consumed, "ADDENDUM_5_4_GEOMETRY_UNBOUND")

    def test_missing_sibling_capture_or_source_evidence_is_review(self):
        mesh, native = fixture()
        for name in ("input_enthalpy_j", "enthalpy_j", "input_source_w", "exact_source_energy_j"):
            broken = copy.deepcopy(native)
            del broken["metadata" if name == "exact_source_energy_j" else "arrays"][name]
            items, consumed, _ = evaluate(broken, copy.deepcopy(native), (mesh, copy.deepcopy(mesh)))
            code = "ADDENDUM_5_4_ZERO_SOURCE_UNPROVED" if name == "exact_source_energy_j" else \
                "ADDENDUM_5_4_CAPTURED_ARRAYS_UNBOUND"
            with self.subTest(missing=name):
                self.assert_review(items, consumed, code)

    def test_zero_total_with_cancelling_nonzero_source_vector_is_review(self):
        mesh, native = fixture()
        native["arrays"]["input_source_w"] = [1.0, -1.0]
        self.assertEqual(Q.source_exact(native["metadata"]["exact_source_energy_j"]), 0)
        items, consumed, _ = evaluate(native, copy.deepcopy(native), (mesh, copy.deepcopy(mesh)))
        self.assert_review(items, consumed, "ADDENDUM_5_4_ZERO_SOURCE_UNPROVED")

    def test_permuted_cell_and_face_axes_pair_by_stored_ids(self):
        mesh, native = fixture()
        after_mesh, after = copy.deepcopy(mesh), copy.deepcopy(native)
        after_mesh["cells"].reverse()
        after_mesh["faces"].reverse()
        for name in ("cell_ids", *Q.RESIDUALS_54):
            after["metadata"][name].reverse()
        for name in ("face_ids", "exact_paired_face_energy_j"):
            after["metadata"][name].reverse()
        for values in after["arrays"].values():
            values.reverse()
        self.assert_valid(*evaluate(native, after, (mesh, after_mesh))[:2])

    def test_duplicate_incidence_is_review(self):
        mesh, native = fixture()
        mesh["cells"][0]["faces"].append(copy.deepcopy(mesh["cells"][0]["faces"][0]))
        items, consumed, _ = evaluate(native, copy.deepcopy(native), (mesh, copy.deepcopy(mesh)))
        self.assert_review(items, consumed, "ADDENDUM_5_4_SIGNED_INCIDENCE_UNBOUND")

    def test_missing_incidence_is_review(self):
        mesh, native = fixture()
        mesh["cells"][0]["faces"] = []
        items, consumed, _ = evaluate(native, copy.deepcopy(native), (mesh, copy.deepcopy(mesh)))
        self.assert_review(items, consumed, "ADDENDUM_5_4_SIGNED_INCIDENCE_UNBOUND")

    def test_unbound_face_axis_or_sign_is_review(self):
        for variant in ("face", "sign"):
            mesh, native = fixture()
            if variant == "face":
                mesh["faces"].pop()
                code = "ADDENDUM_5_4_AXES_UNBOUND"
            else:
                mesh["cells"][0]["faces"][0][1] = 0
                code = "ADDENDUM_5_4_SIGNED_INCIDENCE_UNBOUND"
            with self.subTest(variant=variant):
                items, consumed, _ = evaluate(native, copy.deepcopy(native), (mesh, copy.deepcopy(mesh)))
                self.assert_review(items, consumed, code)

    def test_each_arm_uses_its_own_mesh_geometry(self):
        before_mesh, before = fixture("geometry-before")
        after_mesh, after = fixture("geometry-after")
        self.assert_valid(*evaluate(before, after, (before_mesh, after_mesh))[:2])

    def test_shared_object_still_checks_before_and_after_independently(self):
        class Observed(Q.AddendumRows):
            def __init__(self):
                super().__init__(1)
                self.checked = []

            def settled_heat(self, where, arm, record, *args):
                self.checked.append(arm)
                return super().settled_heat(where, arm, record, *args)

        mesh, native = fixture()
        observed = Observed()
        items, consumed, _ = evaluate(native, native, (mesh, mesh), observed)
        self.assert_valid(items, consumed)
        self.assertEqual(observed.checked, ["before", "after"])
        violate(native)
        observed = Observed()
        items, consumed, _ = evaluate(native, native, (mesh, mesh), observed)
        self.assertEqual(observed.checked, ["before", "after"])
        self.assertEqual([item["arm"] for item in energy_items(items, "FAIL")], ["before", "after"])
        self.assertEqual(consumed, set())

    def test_only_three_residual_fields_are_excluded(self):
        mesh, native = fixture()
        items, consumed, _ = evaluate(native, copy.deepcopy(native), (mesh, copy.deepcopy(mesh)))
        self.assert_valid(items, consumed)
        self.assertEqual([item["code"] for item in energy_items(items)], ["ADDENDUM_5_4_PER_ARM_EXACT"] * 3)
        self.assertNotIn(("heat", "metadata", "exact_corrected_enthalpy_j"), consumed)
        self.assertNotIn(("heat", "metadata", "exact_paired_face_energy_j"), consumed)

    def test_changed_corrected_and_face_energies_stay_in_field_walk(self):
        mesh, before = fixture()
        after = copy.deepcopy(before)
        delta = Fraction(1, 2**24)
        metadata = after["metadata"]
        metadata["exact_paired_face_energy_j"][0] = pair(Fraction(1, 4) + delta)
        for index, sign in enumerate((1, -1)):
            corrected = Q.source_exact(metadata["exact_corrected_enthalpy_j"][index]) - sign * delta
            stored = float(corrected)
            projection = Fraction(stored) - corrected
            retained = Q.source_exact(metadata["exact_retained_solver_residual_j"][index])
            metadata["exact_corrected_enthalpy_j"][index] = pair(corrected)
            metadata["exact_stock_projection_residual_j"][index] = pair(projection)
            metadata["exact_cell_storage_residual_j"][index] = pair(retained + projection)
            after["arrays"]["enthalpy_j"][index] = stored
        items, consumed, _ = evaluate(before, after, (mesh, copy.deepcopy(mesh)))
        self.assert_valid(items, consumed)
        for name in ("exact_corrected_enthalpy_j", "exact_paired_face_energy_j"):
            self.assertNotEqual(before["metadata"][name], after["metadata"][name])
            self.assertNotIn(("heat", "metadata", name), consumed)


if __name__ == "__main__":
    unittest.main()
