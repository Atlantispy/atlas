"""Focused controls for the Plan 04 E pose rows in field_contracts.

Before/after values come from executing the pinned E/W producer bodies (check_equat_bound.py)
on synthetic histories; records are small mesh headers. No runtime import, no interval data.
usage: python -B test_contracts_r4.py [-v]
"""
import hashlib
import importlib.util
import json
import os
import unittest
from fractions import Fraction as Q
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CE = load("check_equat_bound", HERE.parent / "check_equat_bound.py")
T = Path(os.environ.get("ATLAS_T", "."))       # private source root; the controls skip without it
SRC = T / "ps/c/full6/src/atlas_tectonics"
WR2 = T / "ps/c/wr2/src/atlas_tectonics"
C = load("field_contracts_r2", HERE.parent / "n9-tools-r21/field_contracts.py")
EPATH = "atlas_tectonics/integration_exterior_mesh.py"
FIELDS = [("mesh", "representative_quaternion"), ("mesh", "pose_operator_error_bound")]
ARENA = SimpleNamespace(work=lambda _n: None, resource=None)
YEAR = Q(31_557_600)


def enc(value):
    value = Q(value)
    return [hex(value.numerator), hex(value.denominator)]


def poses(case, goal):
    before = CE.build(CE.pinned(str(SRC / "integration_exterior_mesh.py"), "full6_e"), None)
    after = CE.build(CE.pinned(str(WR2 / "integration_exterior_mesh.py"), "wr2_e"),
                     CE.pinned(str(WR2 / "integration_wall_measures.py"), "wr2_w"))
    return before(case, goal, ARENA), after(case, goal, ARENA)


SLOW = (Q(1, 10**14), Q(-3, 10**15), Q(2, 10**14))
NONCOAXIAL = CE.segments([SLOW, (Q(2, 10**14), Q(1, 10**14), Q(0)), (Q(-1, 10**15), Q(4, 10**14), Q(1, 10**14))],
                         [Q(10**5)*YEAR]*3)


def mesh(q, pe, segments=NONCOAXIAL, **kw):
    record = {"schema": C.MESH_SCHEMA, "representative_quaternion": [enc(x) for x in q],
              "pose_operator_error_bound": enc(pe), "trajectory_id": C.digest(segments),
              "trajectory_segments": segments, "endpoint": "end", C.WIDTH: enc(Q(1, 8)),
              "funding_id": "fund", "source": {"sphere_state_id": "sphere"}, "time_s": enc(20)}
    record.update(kw)
    return record


def judge(rb, ra, sources=(C.E_SOURCE, C.E_ROUNDED), extra=({}, {})):
    manifests = {"before": hashlib.sha256(b"mb").hexdigest(), "after": hashlib.sha256(b"ma").hexdigest()}
    pins = {"before": {EPATH: sources[0], **extra[0]}, "after": {EPATH: sources[1], **extra[1]}}
    pairs = {"mesh": {arm: {"record": record, "identity": hashlib.sha256(json.dumps(record).encode()).hexdigest(),
                            "producer": {"path": EPATH, "sha256": pins[arm][EPATH]}}
                      for arm, record in (("before", rb), ("after", ra))}}
    compiled = C.compile_source_evidence(manifests, pins, pairs, FIELDS)
    contracts = C.FieldContracts(compiled["document"], manifests, pins, compiled["verified_evidence"])
    results, _ = contracts.compare_record("mesh", rb, ra, compiled["correspondence"])
    rows = {tuple(row["path"])[1]: (row["verdict"], row["code"]) for row in results}
    rows.update({row["path"][1]: ("REVIEW", row["code"]) for row in compiled["unresolved"]})
    return rows


class PoseRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (SRC / "integration_exterior_mesh.py").is_file() or not (WR2 / "integration_exterior_mesh.py").is_file():
            raise unittest.SkipTest("ATLAS_T source root with the full6 and wr2 trees is required")
        (cls.qb, cls.pb), (cls.qa, cls.pa) = poses(NONCOAXIAL, Q(1, 10**6))

    def test_dependency_change_is_unresolved(self):
        # The proof assumes every other selected module unchanged, except reviewed width transforms.
        volume = "atlas_tectonics/integration_volume.py"
        changed = ({volume: hashlib.sha256(b"v-before").hexdigest()}, {volume: hashlib.sha256(b"v-after").hexdigest()})
        rows = judge(mesh(self.qb, self.pb), mesh(self.qa, self.pa), extra=changed)
        for field in ("representative_quaternion", "pose_operator_error_bound"):
            self.assertEqual(rows[field], ("REVIEW", "E_POSE_DEPENDENCY_SOURCES_DIFFER"))
        wall = "atlas_tectonics/integration_wall_measures.py"
        rounded = ({wall: C.W_SOURCE}, {wall: C.W_ROUNDED})
        rows = judge(mesh(self.qb, self.pb), mesh(self.qa, self.pa), extra=rounded)
        self.assertEqual(rows["representative_quaternion"], ("PASS", "COVERED_QUANTITY_CHANGE"))
        # Tolerance is by canonical key and exact pins, never by basename.
        for key in ("atlas_tectonics/sub/integration_wall_measures.py", "atlas_tectonics\\integration_wall_measures.py"):
            rows = judge(mesh(self.qb, self.pb), mesh(self.qa, self.pa), extra=({key: C.W_SOURCE}, {key: C.W_ROUNDED}))
            self.assertEqual(rows["representative_quaternion"], ("REVIEW", "E_POSE_DEPENDENCY_SOURCES_DIFFER"))
        dm = "atlas_tectonics/integration_differential_mesh.py"
        rows = judge(mesh(self.qb, self.pb), mesh(self.qa, self.pa), extra=({dm: C.M_SOURCE}, {dm: C.M_ROUNDED}))
        self.assertEqual(rows["representative_quaternion"], ("PASS", "COVERED_QUANTITY_CHANGE"))
        # A supplied row carrying the proof bound outside its preconditions is a contradicted contract.
        manifests = {"before": hashlib.sha256(b"mb").hexdigest(), "after": hashlib.sha256(b"ma").hexdigest()}
        pins = {"before": {EPATH: C.E_SOURCE}, "after": {EPATH: C.E_ROUNDED}}
        pairs = {"mesh": {arm: {"record": record, "identity": hashlib.sha256(json.dumps(record).encode()).hexdigest(),
                                "producer": {"path": EPATH, "sha256": pins[arm][EPATH]}}
                          for arm, record in (("before", mesh(self.qb, self.pb)), ("after", mesh(self.qa, self.pa)))}}
        compiled = C.compile_source_evidence(manifests, pins, pairs, FIELDS)
        pins = {arm: dict(pins[arm], **changed[index]) for index, arm in enumerate(("before", "after"))}
        with self.assertRaises(C.ContractError):
            C.FieldContracts(compiled["document"], manifests, pins, compiled["verified_evidence"])

    def test_genuine_rounding_passes(self):
        self.assertNotEqual(self.qb, self.qa)
        rows = judge(mesh(self.qb, self.pb), mesh(self.qa, self.pa))
        self.assertEqual(rows["representative_quaternion"], ("PASS", "COVERED_QUANTITY_CHANGE"))
        self.assertEqual(rows["pose_operator_error_bound"], ("PASS", "COVERED_RADIUS_GROWTH"))

    def test_quaternion_strict_edge(self):
        limit = min(self.pb, self.pa)/4/2048                 # 2**-11 * min(e_before, e_after)
        at_edge = (self.qb[0]+limit,) + tuple(self.qb[1:])
        below = (self.qb[0]+limit*Q(4095, 4096),) + tuple(self.qb[1:])
        self.assertEqual(judge(mesh(self.qb, self.pb), mesh(at_edge, self.pa))["representative_quaternion"],
                         ("FAIL", "STRICT_QUANTITY_BOUND_VIOLATION"))
        self.assertEqual(judge(mesh(self.qb, self.pb), mesh(below, self.pa))["representative_quaternion"],
                         ("PASS", "COVERED_QUANTITY_CHANGE"))

    def test_radius_rules(self):
        rows = judge(mesh(self.qb, self.pb), mesh(self.qb, self.pb - Q(1, 10**40)))
        self.assertEqual(rows["pose_operator_error_bound"], ("FAIL", "RADIUS_NOT_OUTWARD"))
        rows = judge(mesh(self.qb, self.pb), mesh(self.qb, self.pb*(1+Q(1, 2048))))
        self.assertEqual(rows["pose_operator_error_bound"], ("FAIL", "STRICT_RADIUS_GROWTH_VIOLATION"))
        rows = judge(mesh(self.qb, self.pb), mesh(self.qb, self.pb*(1+Q(2047, 2048**2))))
        self.assertEqual(rows["pose_operator_error_bound"], ("PASS", "COVERED_RADIUS_GROWTH"))

    def test_identical_sources_are_exact(self):
        same = (C.E_SOURCE, C.E_SOURCE)
        self.assertEqual(judge(mesh(self.qb, self.pb), mesh(self.qb, self.pb), same)["representative_quaternion"],
                         ("PASS", "EXACT_EQUAL"))
        self.assertEqual(judge(mesh(self.qb, self.pb), mesh(self.qa, self.pa), same)["representative_quaternion"],
                         ("FAIL", "EXACT_UNAFFECTED_CHANGED"))

    def test_unproved_pairs_and_inputs_review(self):
        rows = judge(mesh(self.qa, self.pa), mesh(self.qb, self.pb), (C.E_ROUNDED, C.E_SOURCE))
        self.assertEqual(rows["representative_quaternion"], ("REVIEW", "E_POSE_SOURCE_PAIR_NOT_PROVED"))
        rows = judge(mesh(self.qb, self.pb), mesh(self.qa, self.pa), (C.E_SOURCE, "0"*64))
        self.assertEqual(rows["representative_quaternion"], ("REVIEW", "UNKNOWN_SOURCE_OR_MISSING_RECORD_CONTEXT"))
        rows = judge(mesh(self.qb, self.pb), mesh(self.qa, self.pa, endpoint="start"))
        self.assertEqual(rows["representative_quaternion"], ("REVIEW", "E_POSE_INVOCATION_INPUTS_DIFFER"))
        rows = judge(mesh(self.qb, self.pb), mesh(self.qa, self.pa, trajectory_segments={"compact": "ref"}))
        self.assertEqual(rows["representative_quaternion"], ("REVIEW", "UNKNOWN_SOURCE_OR_MISSING_RECORD_CONTEXT"))

    def test_forged_history_raises(self):
        forged = mesh(self.qa, self.pa, trajectory_id=C.digest(NONCOAXIAL[:1]))
        with self.assertRaises(C.ContractError):
            judge(mesh(self.qb, self.pb), forged)

    def test_zero_rate_exact(self):
        zero = CE.segments([(Q(0), Q(0), Q(0))]*2, [YEAR]*2)
        (qb, pb), (qa, pa) = poses(zero, Q(1, 2))
        rows = judge(mesh(qb, pb, zero), mesh(qa, pa, zero))
        self.assertEqual(rows["representative_quaternion"][0], "PASS")
        self.assertEqual(rows["pose_operator_error_bound"], ("PASS", "EXACT_EQUAL"))


if __name__ == "__main__":
    unittest.main()
