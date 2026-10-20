"""Focused disposable controls; these fixtures are not scientific evidence."""
import copy
from fractions import Fraction as F
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("field_contracts", Path(__file__).with_name("field_contracts.py"))
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)


def q(n, d=1):
    return fc.encoded(F(n, d))


def fixture(norm="l2", representation="exact", bound=None):
    manifests = {"before": "1"*64, "after": "2"*64}
    producer = {"before": {"path": "source.py", "sha256": "3"*64},
                "after": {"path": "source.py", "sha256": "4"*64}}
    row = dict(id="fixture-pose", path=["fixture", "vector"], quantity="fixture direction",
               units="1", norm=norm, components=3 if norm != "scalar" else 1,
               representation=representation, producer=producer,
               context=dict(level=4, history={"before": "5"*64, "after": "6"*64},
                            projection="identity exact", layout="fixture-source-order"),
               bound=bound or dict(kind="design-5", certifies="same-quantity",
                                   radius=dict(before_path=["certificate", "r"], after_path=["certificate", "r"],
                                               scale=q(1))),
               coverage_evidence="7"*64, correspondence_evidence="8"*64)
    coverage = {k: row[k] for k in ("path", "quantity", "units", "norm", "components",
                                     "representation", "producer", "context", "bound")}
    coverage.update(kind="field-semantics", composition=manifests)
    mapping = dict(kind="quantity-correspondence", composition=manifests, path=row["path"],
                   layout=row["context"]["layout"], before_identity="reader-before:quantity0",
                   after_identity="reader-after:quantity0")
    document = dict(schema=fc.SCHEMA, composition=manifests, quantities=[row])
    pins = {arm: {"source.py": producer[arm]["sha256"]} for arm in manifests}
    engine = fc.FieldContracts(document, manifests, pins, {"7"*64: coverage, "8"*64: mapping})
    return engine, document, pins


def compare(engine, a, b, **overrides):
    kw = dict(before_record={"certificate": {"r": q(1)}},
              after_record={"certificate": {"r": q(1)}},
              correspondence=dict(before_identity="reader-before:quantity0", after_identity="reader-after:quantity0"))
    kw.update(overrides)
    return engine.compare(("fixture", "vector"), a, b, **kw)


def cell(identity, volume, lo, hi, error, kind="exterior", logical="logical", support="support"):
    return dict(cell_id=identity, kind=kind, volume_m3=q(volume),
                physical_volume_bounds_m3=[q(lo), q(hi)], geometry_volume_max_deviation_m3=q(error),
                logical_cell_id=logical, physical_support=dict(differential_support_id=support, logical_cell_id=logical))


def mesh(cells, total, width, differential=False):
    record = dict(schema=fc.MESH_SCHEMA, cells=cells, geometry_volume_max_deviation_m3=q(total),
                  max_geometry_volume_error_m3=q(width))
    if differential:
        record["physical_geometry_family"] = "differential-plate-component-partition-v1"
    return record


class QuantityControls(unittest.TestCase):
    def test_vector_norm_rejects_each_component_individually_below_bound(self):
        engine, _, _ = fixture()
        outcome = compare(engine, [q(0)]*3, [q(3, 8192)]*3)
        self.assertEqual(("FAIL", "STRICT_QUANTITY_BOUND_VIOLATION"), (outcome["verdict"], outcome["code"]))

    def test_vector_true_sub_bound_pass(self):
        engine, _, _ = fixture()
        self.assertEqual("PASS", compare(engine, [q(0)]*3, [q(1, 8192)]*3)["verdict"])

    def test_strict_scalar_equal_boundary_and_below(self):
        engine, _, _ = fixture(norm="scalar")
        self.assertEqual("FAIL", compare(engine, q(0), q(1, 2048))["verdict"])
        self.assertEqual("PASS", compare(engine, q(0), q(1, 4096))["verdict"])

    def test_l1_and_linf_are_distinct(self):
        a, _, _ = fixture(norm="l1")
        b, _, _ = fixture(norm="linf")
        old, new = [q(0)]*3, [q(1, 4096)]*3
        self.assertEqual("FAIL", compare(a, old, new)["verdict"])
        self.assertEqual("PASS", compare(b, old, new)["verdict"])

    def test_missing_evidence_cannot_accept_even_exact_values(self):
        engine, _, _ = fixture()
        engine.evidence = {}
        self.assertEqual("REVIEW", compare(engine, [q(0)]*3, [q(0)]*3)["verdict"])

    def test_reader_receipt_is_not_semantics_proof(self):
        engine, _, _ = fixture()
        engine.evidence["7"*64] = {"kind": "reader-receipt"}
        self.assertEqual("REVIEW", compare(engine, [q(0)]*3, [q(0)]*3)["verdict"])

    def test_changed_units_or_norm_in_proof_fails(self):
        for field, value in (("units", "J"), ("norm", "linf")):
            engine, _, _ = fixture()
            engine.evidence["7"*64] = dict(engine.evidence["7"*64], **{field: value})
            self.assertEqual("FAIL", compare(engine, [q(0)]*3, [q(0)]*3)["verdict"])

    def test_wrong_correspondence_fails_and_missing_reviews(self):
        engine, _, _ = fixture()
        self.assertEqual("FAIL", compare(engine, [q(0)]*3, [q(0)]*3,
                                        correspondence=dict(before_identity="other", after_identity="reader-after:quantity0"))["verdict"])
        self.assertEqual("REVIEW", compare(engine, [q(0)]*3, [q(0)]*3, correspondence=None)["verdict"])

    def test_source_and_manifest_mismatch_refuse(self):
        engine, document, pins = fixture()
        pins["after"]["source.py"] = "0"*64
        with self.assertRaises(fc.ContractError):
            fc.FieldContracts(document, engine.manifests, pins)
        document["composition"] = {"before": "9"*64, "after": "2"*64}
        with self.assertRaises(fc.ContractError):
            fc.FieldContracts(document, engine.manifests, {})

    def test_wildcard_and_overlapping_selectors_refuse(self):
        engine, document, pins = fixture()
        document["quantities"][0]["path"] = ["fixture", "[]", "vector"]
        with self.assertRaises(fc.ContractError):
            fc.FieldContracts(document, engine.manifests, pins)
        engine, document, pins = fixture()
        document["quantities"].append(dict(document["quantities"][0], path=["fixture", "vector", "0"]))
        with self.assertRaises(fc.ContractError):
            fc.FieldContracts(document, engine.manifests, pins)

    def test_exact_unaffected_change_fails(self):
        engine, _, _ = fixture(norm="scalar", bound={"kind": "exact"})
        self.assertEqual("FAIL", compare(engine, q(1), q(2))["verdict"])
        self.assertEqual("PASS", compare(engine, q(1), q(1))["verdict"])

    def test_heat_unresolved_never_inherits_pose_factor(self):
        engine, _, _ = fixture(norm="scalar", bound={"kind": "unresolved"})
        self.assertEqual("REVIEW", compare(engine, q(1), q(1))["verdict"])
        self.assertEqual("REVIEW", compare(engine, q(1), q(1_000_001, 1_000_000))["verdict"])

    def test_independent_bound_requires_same_source_proof(self):
        engine, _, _ = fixture(norm="scalar", bound=dict(kind="independent-absolute", strict=True,
                                                        limit=q(1, 100), method="fixture independently derived energy bound"))
        self.assertEqual("PASS", compare(engine, q(1), q(1001, 1000))["verdict"])
        self.assertEqual("FAIL", compare(engine, q(1), q(101, 100))["verdict"])
        engine.evidence.clear()
        self.assertEqual("REVIEW", compare(engine, q(1), q(1001, 1000))["verdict"])

    def test_zero_radius_only_allows_exact_equality(self):
        engine, _, _ = fixture(norm="scalar")
        zero = dict(before_record={"certificate": {"r": q(0)}}, after_record={"certificate": {"r": q(0)}})
        self.assertEqual("PASS", compare(engine, q(1), q(1), **zero)["verdict"])
        self.assertEqual("FAIL", compare(engine, q(1), q(4097, 4096), **zero)["verdict"])

    def test_radius_scale_preserves_e_vs_four_e(self):
        engine, document, pins = fixture(norm="scalar")
        # Source-backed semantics explicitly says operator radius /4, not a sibling guess.
        document["quantities"][0]["bound"]["radius"]["scale"] = q(1, 4)
        engine.evidence["7"*64]["bound"]["radius"]["scale"] = q(1, 4)
        engine = fc.FieldContracts(document, engine.manifests, pins, engine.evidence)
        self.assertEqual("FAIL", compare(engine, q(0), q(1, 8192))["verdict"])

    def test_binary64_nonfinite_and_signed_zero(self):
        engine, _, _ = fixture(norm="scalar", representation="binary64")
        for value in (float("nan"), float("inf"), -float("inf")):
            self.assertEqual("FAIL", compare(engine, value, value)["verdict"])
        self.assertEqual("REVIEW", compare(engine, 0.0, -0.0)["verdict"])
        outcome = compare(engine, 1.0, math_next())
        self.assertEqual("PASS", outcome["verdict"])
        self.assertEqual(1, outcome["diagnostics"]["max_ulps"])
        json.dumps(outcome, allow_nan=False)

    def test_record_walk_consumes_whole_vector_only(self):
        engine, _, _ = fixture()
        before = {"vector": [q(0)]*3, "certificate": {"r": q(1)}, "other": 123}
        after = copy.deepcopy(before)
        after["vector"] = [q(1, 8192)]*3
        evidence = {("fixture", "vector"): dict(before_identity="reader-before:quantity0", after_identity="reader-after:quantity0")}
        results, consumed = engine.compare_record("fixture", before, after, evidence)
        self.assertEqual("PASS", results[0]["verdict"])
        self.assertEqual({("fixture", "vector")}, consumed)
        self.assertIsNone(engine.compare(("fixture", "other"), 123, 124))

    def test_missing_selected_candidate_is_dependency_open(self):
        engine = fc.FieldContracts(None, {}, {})
        self.assertEqual("DEPENDENCY-OPEN", engine.summary()["status"])
        self.assertIsNone(engine.compare(("fixture", "vector"), 1, 2))


def math_next():
    import math
    return math.nextafter(1.0, 2.0)


class HeaderControls(unittest.TestCase):
    def test_e_rederives_each_cell_exact_error(self):
        record = mesh([cell("a", 8, 7, 9, 1), cell("b", 4, 3, 5, 1)], 2, 3)
        outcome = fc.derive_header_total(record, "integration_exterior_mesh.py", fc.E_SOURCE)
        self.assertEqual("PASS", outcome["verdict"])
        self.assertEqual(q(2), outcome["exact_total"])

    def test_m_counts_repeated_piece_error_once(self):
        record = mesh([cell("a", 3, F(15, 2), F(17, 2), F(1, 2)),
                       cell("b", 5, F(15, 2), F(17, 2), F(1, 2))], F(1, 2), 1, True)
        outcome = fc.derive_header_total(record, "integration_differential_mesh.py", fc.M_SOURCE)
        self.assertEqual(("PASS", 1, q(1, 2)), (outcome["verdict"], outcome["groups"], outcome["exact_total"]))
        record["cells"] = [cell("merged", 8, F(15, 2), F(17, 2), F(1, 2))]
        self.assertEqual("PASS", fc.derive_header_total(record, "integration_differential_mesh.py", fc.M_SOURCE)["verdict"])

    def test_m_distinct_supports_are_not_merged(self):
        record = mesh([cell("a", 8, 7, 9, 1, support="support1"),
                       cell("b", 8, 7, 9, 1, support="support2")], 2, 3, True)
        self.assertEqual(2, fc.derive_header_total(record, "integration_differential_mesh.py", fc.M_SOURCE)["groups"])

    def test_m_inconsistent_metadata_fails(self):
        record = mesh([cell("a", 3, 7, 9, 1), cell("b", 5, 7, 9, 2)], 1, 2, True)
        self.assertEqual("FAIL", fc.derive_header_total(record, "integration_differential_mesh.py", fc.M_SOURCE)["verdict"])

    def test_false_per_cell_deviation_and_duplicate_ids_fail(self):
        record = mesh([cell("a", 8, 7, 9, 2)], 2, 3)
        self.assertEqual("FAIL", fc.derive_header_total(record, "integration_exterior_mesh.py", fc.E_SOURCE)["verdict"])
        record = mesh([cell("a", 8, 7, 9, 1)]*2, 2, 3)
        self.assertEqual("FAIL", fc.derive_header_total(record, "integration_exterior_mesh.py", fc.E_SOURCE)["verdict"])

    def test_unknown_producer_and_shared_schema_never_select_layout(self):
        record = mesh([cell("a", 8, 7, 9, 1)], 1, 2, True)
        self.assertEqual("REVIEW", fc.derive_header_total(record, "integration_exterior_mesh.py", "0"*64)["verdict"])
        self.assertEqual("FAIL", fc.derive_header_total(record, "integration_exterior_mesh.py", fc.E_SOURCE)["verdict"])

    def test_addendum_strict_boundary_and_tiny_outward_value(self):
        self.assertEqual("FAIL", fc.evaluate_header(q(2**64+1, 2**64), q(1), q(2))["verdict"])
        self.assertEqual("PASS", fc.evaluate_header(q(2**65+1, 2**65), q(1), q(2))["verdict"])
        self.assertEqual("PASS", fc.evaluate_header(q(2**65+1, 2**1065), q(1, 2**1000), q(1))["verdict"])

    def test_exact_zero_width_before_rounding_and_stored_width(self):
        self.assertEqual("PASS", fc.evaluate_header(q(0), q(0), q(0))["verdict"])
        self.assertEqual("FAIL", fc.evaluate_header(q(1), q(0), q(2))["verdict"])
        self.assertEqual("FAIL", fc.evaluate_header(q(1), q(2), q(1))["verdict"])
        self.assertEqual("FAIL", fc.evaluate_header(q(2**65+1, 2**65), q(1), q(1))["verdict"])
        self.assertEqual("PASS", fc.evaluate_header(q(1), q(1), q(1))["verdict"])

    def test_collar_is_exact_and_zero_deviation(self):
        record = mesh([cell("collar", 8, 8, 8, 0, kind="collar")], 0, 1)
        self.assertEqual("PASS", fc.derive_header_total(record, "integration_exterior_mesh.py", fc.E_SOURCE)["verdict"])
        record["cells"][0][fc.DEVIATION] = q(1)
        self.assertEqual("FAIL", fc.derive_header_total(record, "integration_exterior_mesh.py", fc.E_SOURCE)["verdict"])

    def test_every_refusal_flip_fails(self):
        for a, b in ((True, False), (False, True)):
            self.assertEqual("FAIL", fc.refusal_result(a, b)["verdict"])
        self.assertEqual("REVIEW", fc.refusal_result(None, False)["verdict"])
        self.assertEqual("PASS", fc.refusal_result(True, True)["verdict"])

    def test_rounded_historical_sources_dispatch_identically(self):
        record = mesh([cell("a", 8, 7, 9, 1)], 1, 2)
        self.assertEqual("PASS", fc.derive_header_total(record, "integration_exterior_mesh.py", fc.E_ROUNDED)["verdict"])
        record["physical_geometry_family"] = "differential-plate-component-partition-v1"
        self.assertEqual("PASS", fc.derive_header_total(record, "integration_differential_mesh.py", fc.M_ROUNDED)["verdict"])

    def test_exact_header_rejects_binary64(self):
        self.assertEqual("FAIL", fc.evaluate_header(1.0, q(1), q(2))["verdict"])


class SourceCompilerControls(unittest.TestCase):
    def source_fixture(self):
        before = mesh([cell("a", 8, 7, 9, 1)], 1, 2)
        before.update(time_s=q(12), trajectory_id="a"*64)
        after = copy.deepcopy(before)
        manifests = dict(before="1"*64, after="2"*64)
        sources = dict(before={"src/integration_exterior_mesh.py": fc.E_SOURCE},
                       after={"src/integration_exterior_mesh.py": fc.E_ROUNDED})
        records = {"mesh": {
            "before": dict(record=before, identity="proved-before-target",
                           producer=dict(path="src/integration_exterior_mesh.py", sha256=fc.E_SOURCE)),
            "after": dict(record=after, identity="proved-after-target",
                          producer=dict(path="src/integration_exterior_mesh.py", sha256=fc.E_ROUNDED)),
        }}
        return manifests, sources, records

    def test_source_derivation_produces_consumable_exact_contract(self):
        manifests, sources, records = self.source_fixture()
        compiled = fc.compile_source_evidence(manifests, sources, records,
                                              [("mesh", "time_s"), ("mesh", fc.WIDTH)])
        self.assertEqual([], compiled["unresolved"])
        engine = fc.FieldContracts(compiled["document"], manifests, sources, compiled["verified_evidence"])
        rows, _ = engine.compare_record("mesh", records["mesh"]["before"]["record"],
                                         records["mesh"]["after"]["record"], compiled["correspondence"])
        self.assertEqual(["PASS", "PASS"], [row["verdict"] for row in rows])
        records["mesh"]["after"]["record"]["time_s"] = q(13)
        rows, _ = engine.compare_record("mesh", records["mesh"]["before"]["record"],
                                         records["mesh"]["after"]["record"], compiled["correspondence"])
        self.assertEqual("FAIL", rows[0]["verdict"])

    def test_modified_contract_assertion_cannot_override_derived_semantics(self):
        manifests, sources, records = self.source_fixture()
        compiled = fc.compile_source_evidence(manifests, sources, records, [("mesh", "time_s")])
        compiled["document"]["quantities"][0]["units"] = "J"
        engine = fc.FieldContracts(compiled["document"], manifests, sources, compiled["verified_evidence"])
        rows, _ = engine.compare_record("mesh", records["mesh"]["before"]["record"],
                                         records["mesh"]["after"]["record"], compiled["correspondence"])
        self.assertEqual("FAIL", rows[0]["verdict"])
        self.assertEqual("CONTRADICTED_FIELD_SEMANTICS", rows[0]["code"])

    def test_pose_heat_and_unknown_sources_cannot_compile(self):
        manifests, sources, records = self.source_fixture()
        compiled = fc.compile_source_evidence(manifests, sources, records,
                                              [("mesh", "representative_quaternion"), ("heat", "energy_j")])
        self.assertEqual(2, len(compiled["unresolved"]))
        self.assertEqual([], compiled["document"]["quantities"])
        sources["after"]["src/integration_exterior_mesh.py"] = "9"*64
        records["mesh"]["after"]["producer"]["sha256"] = "9"*64
        compiled = fc.compile_source_evidence(manifests, sources, records, [("mesh", "time_s")])
        self.assertEqual(1, len(compiled["unresolved"]))
        self.assertEqual({}, compiled["verified_evidence"])

    def test_producer_source_mismatch_fails_before_deriving(self):
        manifests, sources, records = self.source_fixture()
        sources["after"]["src/integration_exterior_mesh.py"] = "9"*64
        with self.assertRaises(fc.ContractError):
            fc.compile_source_evidence(manifests, sources, records, [("mesh", "time_s")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
