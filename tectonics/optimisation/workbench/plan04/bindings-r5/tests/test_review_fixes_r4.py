"""Controls for the route gates, type-strict premises and failure handling of the comparator tools.

Each control fails if its source rule is reverted:
- DesignRows.route: DG counts as identical only at DG_SOURCE in both arms; package parity, a missing or
  ambiguous module pin and the reviewed transform pair each withhold every PASS and FAIL of the rows that
  read them, and leave the other rows unchanged; an identical E route judges a cell change at radius 0.
- Type-strict premises: identical() is canonical-digest equality, and evaluate() turns a value-equality PASS
  whose leaves are not encoded alike (5 and 5.0, 0.0 and -0.0) into REVIEW DESIGN_ENCODING_DIFFERS, left to
  the type-strict walk.
- Layout errors: a row method that raises keeps its FAIL and REVIEW items, but no PASS and no consumed path.
- Family 3 (field_provenance): rows 3.2 and 3.6 compare the arms only on family3_route; off it they are
  <code>_ROUTE_NOT_PROVED notes, while the per-arm writer contradictions still FAIL.
- dump_arm_r5.close_scope: a close failure of any Exception type is noted on the original refusal.
- array_bindings_r5.decoder_summary names the differing helpers/*.py decoders apart from the others.
- check_equat_bound refuses a pin mismatch under python -O.
Small synthetic records built with the fixture helpers of test_design_rows_r3.py. No runtime import, no
interval data. Family 3 and the E-bound check need ATLAS_T (the r4 and wr2 producer sources) and skip
without it.
usage: python -B test_review_fixes_r4.py [-v]
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction as Q
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEV = HERE.parent / "n9-tools-r21"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


D = load("test_design_rows_r3_fixtures", HERE / "test_design_rows_r3.py")
C, PT = D.C, D.PT
AB = load("array_bindings_r5_controls", DEV / "array_bindings_r5.py")
DA = load("dump_arm_r5_controls", DEV / "dump_arm_r5.py")
W, E, M, DG = D.W, D.E, D.M, D.DG
V = "atlas_tectonics/integration_volume.py"
MODULES = {"W": W, "E": E, "M": M, "DG": DG}

EB, STEP = Q(1, 2**60), D.Interval.STEP
NB, PEB = D.PosedSupport.NB, D.PosedSupport.EB
NA, EA, QUANTUM = D.PosedSupport("test_1c_recomputation_pass_and_fail").width(D.SNAP)
QB, PB, PA = D.Poses.QB, D.Poses.PB, D.Poses.PA
COAXIAL = (Q(3, 5)+Q(1, 2**36), 0, 0, Q(4, 5))
FAR = ((5, 6), (2, 3), (-1, 1))
HEAT = D.Heat("test_ledger_rows")          # for its ledger record builder


def design(before=D.BASE, after=D.WIDTH, parity=None):
    """A DesignRows factory on the two arms' pins; a given parity replaces the package parity gate."""
    def make():
        rows = D.rows(after=after, before=before)
        if parity is not None:
            rows.parity = parity
        return rows
    return make


def decisions(results, gated=None):
    """The PASS and FAIL items (only the gated codes when given), comparable across pin pairings."""
    return sorted((r["verdict"], r["code"], tuple(r["path"])) for r in results
                  if r["verdict"] in ("PASS", "FAIL") and (gated is None or r["code"] in gated))


def observed(make):
    """compare_arms observes the differential interval before its record walk (graph and forcing rows)."""
    rows = make()
    rows.observe("differential", {"interval": D.interval(interval_id="i-b")},
                 {"interval": D.interval(EB+STEP, interval_id="i-a")})
    return rows


def heat_pair(make, old, new):
    """Heat.heat_rows on a given pin pairing: exchange, mesh and state context, then the composed heat record."""
    rows = make()
    heat_plan = D.plan(boundary={"f1": ["power", 2.0], "f2": ["power", 5.0]})
    rows.observe("exchange", D.exchange(heat_plan), D.exchange(heat_plan))
    mesh = {"schema": C.MESH_SCHEMA, "cells": [], "faces": [{"face_id": "f1", "owners": ["c"]},
                                                              {"face_id": "f2", "owners": ["c", "d"]}]}
    rows.observe("mesh", mesh, mesh)
    rows.observe("state", {"schema": C.STATE_SCHEMA, "thermal_mesh_id": "g"},
                 {"schema": C.STATE_SCHEMA, "thermal_mesh_id": "g"})
    return D.run("heat", old, new, rows)


def heat_rows(make, old, new):
    return heat_pair(make, old, new)[0]


def plan_target(make):
    rows = make()
    old, new = D.exchange(), D.exchange(D.plan(Q(1, 512), "0.001953125"))
    rows.observe("exchange", old, new)
    return D.run("exchange", old, new, rows)[0]


def force_pose(p):
    return dict(D.background(p)["pose"], schema=C.FORCE_POSE_SCHEMA)


# Heat rows gated by parity; the 5.7a and value-equal 5.8 rows are per-arm or route-free.
HEAT_GATED = frozenset({"DESIGN_5_6_ZERO_SOURCE", "DESIGN_5_6_SOURCE_ENERGY_NOT_ZERO", "DESIGN_5_8_TARGET_CHANGED",
                        "DESIGN_5_9_BITWISE_EQUAL"})
DIFFERENTIAL, BOUNDARY_POSE, E_POSE, E_MESH = ({"parity", "DG", "W"}, {"parity", "DG", "E"}, {"parity", "E"},
                                               {"parity", "E", "W"})
# name: (gates the rows read, gated codes or None for every PASS/FAIL, probe returning the results)
PROBES = {
    "1-A band": (DIFFERENTIAL, None, lambda make: D.run(
        "differential", D.interval(EB), D.interval(EB+3*STEP, eb_row=Q(1, 2**61)+STEP), make())[0]),
    "1-A band violation": (DIFFERENTIAL, None, lambda make: D.run(
        "differential", D.interval(EB), D.interval(EB+8*STEP), make())[0]),
    "1-C recomputed": (DIFFERENTIAL, None, lambda make: D.run(
        "posed", D.posed(NB, PEB, D.SNAP), D.posed(NA, EA, D.SNAP), make())[0]),
    "1-C recomputation differs": (DIFFERENTIAL, None, lambda make: D.run(
        "posed", D.posed(NB, PEB, D.SNAP), D.posed((NA[0]+QUANTUM,)+NA[1:], EA, D.SNAP), make())[0]),
    "1-E measure disjoint": (DIFFERENTIAL, None, lambda make: D.run(
        "graph", D.measure(), D.measure(inward=(3, 4)), make())[0]),
    "1-E graph disjoint": (DIFFERENTIAL, None, lambda make: D.run(
        "graph", D.graph(), D.graph_a(start=(4, 5)), observed(make))[0]),
    "1-E cut torque disjoint": (DIFFERENTIAL, None, lambda make: D.run(
        "certification", {"force": D.forcing("i-b")}, {"force": D.forcing("i-a", FAR)}, observed(make))[0]),
    "2.1-2.3": (BOUNDARY_POSE, None, lambda make: D.run(
        "x", D.bpose(QB, PB), D.bpose(COAXIAL, PA), make())[0]),
    "2.1 violation": (BOUNDARY_POSE, None, lambda make: D.run(
        "x", D.bpose(QB, PB), D.bpose(COAXIAL, PB+Q(1, 2**30)), make())[0]),
    "2.6": (E_POSE, None, lambda make: D.run("x", force_pose(PB), force_pose(PA), make())[0]),
    "2.8": (E_POSE, None, lambda make: D.run("x", D.background(PB), D.background(PA), make())[0]),
    "4.3-4.7": (E_MESH, None, lambda make: D.run(
        "mesh", D.e_mesh(), D.widened(volume=Q(1, 2)+Q(1, 2**24)), make())[0]),
    "4.3 violation": (E_MESH, None, lambda make: D.run(
        "mesh", D.e_mesh(), D.widened(volume=Q(1, 2)+Q(1, 2**18)), make())[0]),
    "5.6 and 5.9": ({"parity"}, HEAT_GATED, lambda make: heat_rows(make, HEAT.ledger(), HEAT.ledger())),
    "5.8 heat target changed": ({"parity"}, HEAT_GATED, lambda make: heat_rows(
        make, HEAT.ledger(), HEAT.ledger(independently_supplied_absolute_residual_target=D.enc(Q(1, 512))))),
    "5.8 plan target changed": ({"parity"}, HEAT_GATED, plan_target),
}


def without(pins, path):
    return {key: pin for key, pin in pins.items() if key != path}


SHADOW_W = "atlas_tectonics/legacy/integration_wall_measures.py"
# label, before pins, after pins, forced parity (None: computed), gates the pairing breaks
FIXTURES = (
    ("integration_volume.py differs", D.BASE, dict(D.WIDTH, **{V: "w"*64}), None, {"parity"}),
    ("W pair reversed", dict(D.BASE, **{W: C.W_ROUNDED}), dict(D.WIDTH, **{W: C.W_SOURCE}), None, {"parity", "W"}),
    ("every pair reversed", D.WIDTH, D.BASE, None, {"parity", "W", "E"}),
    ("W after-pin unreviewed", D.BASE, dict(D.WIDTH, **{W: "f"*64}), None, {"parity", "W"}),
    ("E pair unreviewed", D.BASE, dict(D.WIDTH, **{E: "e"*64}), None, {"parity", "E"}),
    ("DG unreviewed in both arms", dict(D.BASE, **{DG: "d"*64}), dict(D.WIDTH, **{DG: "d"*64}), None, {"DG"}),
    ("DG pin missing in both arms", without(D.BASE, DG), without(D.WIDTH, DG), None, {"DG"}),
    ("W pin missing in both arms", without(D.BASE, W), without(D.WIDTH, W), None, {"W"}),
    ("E pin missing in both arms", without(D.BASE, E), without(D.WIDTH, E), None, {"E"}),
    ("W pin ambiguous in both arms", dict(D.BASE, **{SHADOW_W: "x"*64}), dict(D.WIDTH, **{SHADOW_W: "x"*64}), None,
     {"W"}),
    # Parity forced True: the reviewed-pair gate on its own, which a broken parity otherwise hides.
    ("W pair reversed, parity forced", dict(D.BASE, **{W: C.W_ROUNDED}), dict(D.WIDTH, **{W: C.W_SOURCE}), True,
     {"W"}),
    ("W after-pin unreviewed, parity forced", D.BASE, dict(D.WIDTH, **{W: "f"*64}), True, {"W"}),
    ("E pair unreviewed, parity forced", D.BASE, dict(D.WIDTH, **{E: "e"*64}), True, {"E"}),
    ("E pins on the W transform, parity forced", dict(D.BASE, **{E: C.W_SOURCE}), dict(D.WIDTH, **{E: C.W_ROUNDED}),
     True, {"E"}),
    ("DG differs, parity forced", D.BASE, dict(D.WIDTH, **{DG: "d"*64}), True, {"DG"}),
)


class DifferentialGeometryPin(unittest.TestCase):
    def test_unreviewed_dg_in_both_arms_decides_no_row(self):
        unreviewed = design(dict(D.BASE, **{DG: "d"*64}), dict(D.WIDTH, **{DG: "d"*64}))
        rows = unreviewed()
        self.assertTrue(rows.parity)
        self.assertEqual((rows.route("DG"), rows.differential_route()), (None, None))
        self.assertEqual((D.rows().route("DG"), D.rows().differential_route()), ("identical", "transform"))
        for name in ("1-A band", "1-A band violation", "1-C recomputed", "2.1-2.3"):
            with self.subTest(name):
                _, gated, probe = PROBES[name]
                self.assertTrue(decisions(probe(design()), gated))         # it decides at DG_SOURCE
                results = probe(unreviewed)
                self.assertEqual(decisions(results, gated), [], results)
                self.assertEqual(D.verdicts(results), {"REVIEW"}, results)


class RouteGates(unittest.TestCase):
    def test_each_gate_withholds_exactly_the_rows_that_read_it(self):
        reviewed = {name: decisions(probe(design()), gated) for name, (_, gated, probe) in PROBES.items()}
        for name, found in reviewed.items():
            self.assertTrue(found, "%s decides nothing on the reviewed route" % name)
        for label, before, after, parity, broken in FIXTURES:
            make = design(before, after, parity)
            if parity is None:
                self.assertEqual(make().parity, "parity" not in broken, label)
            for name, (reads, gated, probe) in PROBES.items():
                with self.subTest(label, row=name):
                    self.assertEqual(decisions(probe(make), gated), [] if reads & broken else reviewed[name])

    def test_reviewed_pair_gate_alone(self):
        # Every unreviewed pairing here also breaks parity; forcing parity exposes the reviewed-pair check.
        rows = design(D.BASE, dict(D.WIDTH, **{E: "e"*64}))()
        self.assertFalse(rows.parity)
        rows.parity = True
        self.assertEqual((rows.route("W"), rows.route("DG"), rows.route("E"), rows.route("M")),
                         ("transform", "identical", None, "transform"))
        for family, (before, after) in (("W", (C.W_ROUNDED, C.W_SOURCE)), ("W", (C.W_SOURCE, "f"*64)),
                                        ("E", (C.E_ROUNDED, C.E_SOURCE)), ("E", (C.W_SOURCE, C.W_ROUNDED)),
                                        ("M", (C.E_SOURCE, C.E_ROUNDED)), ("DG", (C.DG_SOURCE, "d"*64)),
                                        ("DG", ("d"*64, "d"*64))):
            with self.subTest(family=family, pair=(before[:8], after[:8])):
                path = MODULES[family]
                rows = design(dict(D.BASE, **{path: before}), dict(D.WIDTH, **{path: after}), parity=True)()
                self.assertIsNone(rows.route(family))
        same = design(D.BASE, D.BASE, parity=True)()
        self.assertEqual({family: same.route(family) for family in MODULES}, dict.fromkeys(MODULES, "identical"))

    def test_identical_e_route_has_radius_zero(self):
        same = D.rows(after=D.BASE)
        self.assertEqual((same.route("E"), same.route("W")), ("identical", "identical"))
        changed = dict(volume=Q(1, 2)+Q(1, 2**24))
        bad, _ = D.run("mesh", D.e_mesh(), D.e_mesh(**changed), same)
        self.assertIn("DESIGN_4_3_VOLUME_VIOLATION", D.codes(bad, "FAIL"))
        ok, _ = D.run("mesh", D.e_mesh(), D.widened(**changed))      # the same change on the reviewed transform
        self.assertIn("DESIGN_4_3_VOLUME", D.codes(ok, "PASS"))
        # A pose change that C1-C4 allow on the transform is no identical-route premise: REVIEW, never PASS.
        review, _ = D.run("mesh", D.e_mesh(), D.e_mesh(bound=Q(1, 2**20)+Q(1, 2**32), **changed), same)
        self.assertNotIn("PASS", D.verdicts(review))
        self.assertIn("DESIGN_4_POSE_PREREQUISITE_NOT_MET", D.codes(review, "REVIEW"))


class TypeStrictPremises(unittest.TestCase):
    def test_motion_boundary_paths_are_part_of_the_premise(self):
        def record():
            rows = D.interval(EB)["boundary_paths"]
            rows.append(dict(rows[0], boundary_id="b2"))
            return D.interval(EB, boundary_paths=rows)
        old, valid = record(), record()
        valid["boundary_paths"][0]["endpoint_operator_error_bound"] = D.enc(Q(1, 2**61)+STEP)
        self.assertTrue(C.DesignRows.motion_same(old, valid))
        for case in ("identity", "kind", "new-input", "order"):
            new = record()
            new["plate_endpoint_operator_error_bounds"]["p1"] = D.enc(EB+3*STEP)
            if case == "identity":
                new["boundary_paths"][0]["boundary_id"] = "different-boundary"
            elif case == "kind":
                new["boundary_paths"][0]["kind"] = "different-kind"
            elif case == "new-input":
                new["boundary_paths"][0]["other_input"] = D.enc(1)
            else:
                new["boundary_paths"].reverse()
            with self.subTest(case=case):
                self.assertFalse(C.DesignRows.motion_same(old, new))
                items, consumed = D.run("differential", old, new)
                self.assertIn("DESIGN_1A_PRECONDITION_DIFFERS", D.codes(items, "REVIEW"))
                self.assertNotIn("DESIGN_1A_BAND", D.codes(items, "PASS"))
                self.assertFalse(any(path[1] == "plate_endpoint_operator_error_bounds" for path in consumed))

    def test_float_motion_input_breaks_the_premise(self):
        old, new = D.interval(EB), dict(eb_row=Q(1, 2**61)+STEP)
        ok, _ = D.run("differential", old, D.interval(EB+3*STEP, orientation_max_leaves=64, **new))
        self.assertTrue({"DESIGN_1A_BAND", "DESIGN_1B_EQUAL"} <= D.codes(ok, "PASS"), ok)
        review, consumed = D.run("differential", old, D.interval(EB+3*STEP, orientation_max_leaves=64.0, **new))
        self.assertFalse(D.codes(review, "PASS"), review)
        self.assertIn("DESIGN_1A_PRECONDITION_DIFFERS", D.codes(review, "REVIEW"))
        self.assertEqual(consumed, set())
        self.assertFalse(C.identical(64, 64.0) or C.identical(0.0, -0.0) or C.identical(1, True))

    def test_value_equal_pass_with_another_encoding_stays_walked(self):
        name = "independently_supplied_absolute_residual_target"
        # Two rules that PASS on Python equality: 1-B on an orientation decision and 5.8 on the heat target.
        cases = (("1-B", lambda x, y: D.run("differential", D.interval(orientation_work_units=x),
                                            D.interval(orientation_work_units=y)),
                  ("differential", "orientation_work_units"), "DESIGN_1B_EQUAL"),
                 ("5.8", lambda x, y: heat_pair(design(), HEAT.ledger(**{name: x}), HEAT.ledger(**{name: y})),
                  ("heat", name), "DESIGN_5_8_TARGET_EQUAL"))
        for row, run, path, code in cases:
            ok, consumed = run(5, 5)
            self.assertIn((list(path), "PASS", code), [(r["path"], r["verdict"], r["code"]) for r in ok], row)
            self.assertIn(path, consumed, row)
            for x, y in ((5, 5.0), (0.0, -0.0)):
                with self.subTest(row, before=x, after=y):
                    results, consumed = run(x, y)
                    at = [r for r in results if r["path"] == list(path)]
                    self.assertNotIn("PASS", {r["verdict"] for r in at}, results)
                    vetoed = [(r["verdict"], r.get("passed")) for r in at if r["code"] == "DESIGN_ENCODING_DIFFERS"]
                    self.assertEqual(vetoed, [("REVIEW", code)], results)
                    self.assertNotIn(path, consumed)


class LayoutErrors(unittest.TestCase):
    def test_pass_before_a_layout_error_is_dropped(self):
        rows, emitted = D.rows(), []

        def recording(results, consumed, verdict, code, path, row, consume=True, **details):
            emitted.append((verdict, row))
            C.DesignRows._add(results, consumed, verdict, code, path, row, consume, **details)
        rows._add = recording
        malformed = D.bpose(COAXIAL, PA, rotation=((1, 0, 0), (0, 1, 0)))        # two rows: _matrix refuses
        results, consumed = rows.evaluate("x", D.bpose(QB, PB), malformed)
        self.assertEqual(emitted, [("PASS", "2.1"), ("PASS", "2.1")])          # 2.1 PASSed before the error
        self.assertNotIn("PASS", D.verdicts(results))
        self.assertEqual(D.codes(results), {"DESIGN_ROW_LAYOUT_UNRECOGNISED"})
        self.assertEqual(consumed, set())

    def test_fail_before_a_layout_error_is_kept(self):
        def short_cone(mesh):
            mesh["support_tables"]["cones"]["cone-1"] = [["r1"], ["r2"]]           # E cone layout needs >= 3
            return mesh
        results, consumed = D.run("mesh", short_cone(D.e_mesh()), short_cone(D.widened(source_key="k2")))
        self.assertEqual(D.codes(results, "FAIL"), {"DESIGN_4_2_POSE_INDEPENDENT_CHANGED"})
        self.assertIn("DESIGN_ROW_LAYOUT_UNRECOGNISED", D.codes(results, "REVIEW"))
        self.assertNotIn("PASS", D.verdicts(results))
        self.assertEqual(consumed, set())


def overlapping(wall):
    """The extra (zero) cells take the owner's start and end bounds, so moving the owner leaves every per-key
    enclosure intersecting: row 3.2 alone separates the arms."""
    wall = json.loads(json.dumps(wall))
    for cell in wall["exterior_cells"][1:]:
        cell.update(start_volume_bounds_m3=[D.enc(5), D.enc(7)], end_volume_bounds_m3=[D.enc(5), D.enc(8)])
    return PT.reseal(wall)


class FamilyThreeRoute(unittest.TestCase):
    ROWS = {"W_SETTLED_KEY_DIFFERS", "W_FACE_PARTITION_CONTRADICTION", "W_SETTLED_CELL_CHOSEN_CHANGED"}

    @classmethod
    def setUpClass(cls):
        D.FamilyThree.setUpClass()
        cls.src, cls.rnd, cls.other = D.FamilyThree.src, D.FamilyThree.rnd, D.FamilyThree.other
        cls.fails = set(PT.P.FAIL_CODES)

    pair = D.FamilyThree.pair

    def test_3_2_moved_owner_without_route_is_review(self):
        wall = PT.make_wall([((0, 0), (2, 5))], [(0, 4)], extra_cells=(["layer", 1],))
        moved = D.owned_by(wall, ["layer", 1], ["layer", 0])
        proved, unproved = self.pair(wall, moved), self.pair(wall, moved, after=self.other)
        self.assertIn("W_FACE_PARTITION_CONTRADICTION", proved)
        self.assertIn("W_FACE_PARTITION_CONTRADICTION_ROUTE_NOT_PROVED", unproved)
        self.assertEqual(unproved & self.fails, (proved & self.fails) - self.ROWS)     # disjoint enclosures remain
        # Moved without disjoint enclosures: the row decides the verdict, FAIL on the route and none off it.
        wall = PT.make_wall([((0, 0), (0, 5))], [(0, 4)], extra_cells=(["layer", 1],))
        moved = D.owned_by(wall, ["layer", 1], ["layer", 0])
        proved = self.pair(overlapping(wall), overlapping(moved))
        unproved = self.pair(overlapping(wall), overlapping(moved), after=self.other)
        self.assertEqual(proved & self.fails, {"W_FACE_PARTITION_CONTRADICTION"})
        self.assertEqual(unproved & self.fails, set())
        self.assertIn("W_FACE_PARTITION_CONTRADICTION_ROUTE_NOT_PROVED", unproved)

    def test_3_6_settled_chosen_change_without_route_is_review(self):
        # A settled chosen change also contradicts the arm's own writer relations, which FAIL on any route.
        wall = PT.make_wall(PT.BASE_BOUNDS, PT.BASE_EXACT)
        new = json.loads(json.dumps(wall))
        new["exterior_cells"][0]["chosen_volume_change_m3"] = D.enc(3)
        proved, unproved = self.pair(wall, PT.reseal(new)), self.pair(wall, PT.reseal(new), after=self.other)
        self.assertIn("W_SETTLED_CELL_CHOSEN_CHANGED", proved)
        self.assertIn("W_SETTLED_CELL_CHOSEN_CHANGED_ROUTE_NOT_PROVED", unproved)
        self.assertEqual(unproved & self.fails, {"W_AGGREGATE_CHOSEN_CONTRADICTION", "W_CELL_CONTRACT_CONTRADICTION"})
        self.assertEqual(unproved & self.fails, (proved & self.fails) - self.ROWS)


class ScopeClose(unittest.TestCase):
    class Scope:
        def __init__(self, error=None):
            self.error, self.closed = error, 0

        def close(self):
            self.closed += 1
            if self.error is not None:
                raise self.error

    @staticmethod
    def refuse(scope):
        """The dump's own handling: close the scope while the refusal is handled, then re-raise it."""
        try:
            raise DA.DumpRefused("the dump changed the store")
        except BaseException as error:
            DA.close_scope(scope, error)
            raise

    def test_close_failure_keeps_the_refusal(self):
        for closing in (ValueError("blocks still owned"), RuntimeError("blocks still owned"), OSError(5, "busy")):
            with self.subTest(type(closing).__name__):
                scope = self.Scope(closing)
                with self.assertRaises(DA.DumpRefused) as caught:
                    self.refuse(scope)
                self.assertEqual(str(caught.exception), "the dump changed the store")
                self.assertEqual(caught.exception.__notes__, ["retained scope left open after the refusal: %s: %s" % (
                    type(closing).__name__, closing)])
                self.assertEqual(scope.closed, 1)

    def test_clean_close_and_unhandled_cases(self):
        with self.assertRaises(DA.DumpRefused) as caught:
            self.refuse(self.Scope())
        self.assertFalse(getattr(caught.exception, "__notes__", None))
        with self.assertRaises(ValueError):                  # no refusal in flight: a close failure surfaces
            DA.close_scope(self.Scope(ValueError("blocks still owned")))
        with self.assertRaises(KeyboardInterrupt):           # only Exception types are noted
            self.refuse(self.Scope(KeyboardInterrupt()))


class DecoderSummary(unittest.TestCase):
    HELPER, PACKAGE = "partition_v2", "atlas_tectonics.storage"

    @staticmethod
    def dumps(changed=()):
        def decoders(arm):
            return {name: {"path": path, "sha256": ("b" if arm == "after" and name in changed else "a")*64}
                    for name, path in sorted(AB.DECODER_PATHS.items())}
        return {arm: {interval: {"decoders": decoders(arm)} for interval in (0, 1)} for arm in ("before", "after")}

    def test_helpers_decoders_named_apart(self):
        self.assertTrue(AB.DECODER_PATHS[self.HELPER].startswith("helpers/"))
        self.assertTrue(AB.DECODER_PATHS[self.PACKAGE].startswith("src/atlas_tectonics/"))
        summary = AB.decoder_summary(self.dumps((self.HELPER, self.PACKAGE)))
        self.assertEqual(summary["differ_across_arms"], sorted([self.HELPER, self.PACKAGE]))
        self.assertEqual(summary["helpers_differ_across_arms"], [self.HELPER])
        self.assertEqual(set(summary["arms"]["after"]), {"i0", "i1"})
        summary = AB.decoder_summary(self.dumps((self.PACKAGE,)))
        self.assertEqual((summary["differ_across_arms"], summary["helpers_differ_across_arms"]), ([self.PACKAGE], []))
        summary = AB.decoder_summary(self.dumps())
        self.assertEqual((summary["differ_across_arms"], summary["helpers_differ_across_arms"]), ([], []))


class EquatBoundOptimised(unittest.TestCase):
    def test_pin_mismatch_refuses_under_python_o(self):
        root = Path(os.environ.get("ATLAS_T", "."))
        inputs = [root / "ac/p1820c-r4/src/atlas_tectonics/integration_exterior_mesh.py",
                  root / "ps/c/wr2/src/atlas_tectonics/integration_exterior_mesh.py",
                  root / "ps/c/wr2/src/atlas_tectonics/integration_wall_measures.py"]
        if not all(path.is_file() for path in inputs):
            self.skipTest("ATLAS_T with the full6 E, wr2 E and wr2 W producer sources is required")
        source = (HERE.parent / "check_equat_bound.py").read_text(encoding="utf-8")
        pin = "'full6_e': '%s'" % C.E_SOURCE
        self.assertEqual(source.count(pin), 1)
        with tempfile.TemporaryDirectory(prefix="equat") as folder:
            script = Path(folder) / "check_equat_bound_planted.py"
            script.write_text(source.replace(pin, "'full6_e': '%s'" % C.E_ROUNDED), encoding="utf-8", newline="\n")
            done = subprocess.run([sys.executable, "-O", "-B", str(script)] + [str(path) for path in inputs],
                                  cwd=folder, capture_output=True, text=True, timeout=600)
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("full6_e source differs from its pin", done.stderr)
        self.assertNotIn("RESULT", done.stdout)


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0]] + sys.argv[1:], exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
