"""Controls for the design-row encodings (field_contracts.DesignRows, field_provenance family 3).

Small synthetic records built to the producers' own relations. Every FAIL control must FAIL; every REVIEW
case must not FAIL. No runtime import, no interval data. Family 3 needs ATLAS_T (it reuses the r4
provenance fixtures) and skips without it.
usage: python -B test_design_rows_r3.py [-v]
"""
import hashlib
import importlib.util
import json
import math
import tempfile
import unittest
from fractions import Fraction as Q
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


C = load("field_contracts_r3", HERE.parent / "n9-tools-r21/field_contracts.py")
PT = load("test_provenance_r4_fixtures", HERE / "test_provenance_r4.py")
W, E, M = ("atlas_tectonics/" + C.DESIGN_MODULES[k] for k in "WEM")
DG = "atlas_tectonics/" + C.DESIGN_MODULES["DG"]
BASE = {W: C.W_SOURCE, E: C.E_SOURCE, M: C.M_SOURCE, DG: C.DG_SOURCE, "atlas_tectonics/integration_volume.py": "v"*64}
WIDTH = dict(BASE, **{W: C.W_ROUNDED, E: C.E_ROUNDED, M: C.M_ROUNDED})


def enc(value):
    value = Q(value)
    return [hex(value.numerator), hex(value.denominator)]


def rows(after=WIDTH, before=BASE):
    return C.DesignRows({"before": before, "after": after})


def run(kind, old, new, design=None):
    return (design or rows()).evaluate(kind, old, new)


def codes(results, verdict=None):
    return {r["code"] for r in results if verdict in (None, r["verdict"])}


def verdicts(results):
    return {r["verdict"] for r in results}


# -- family 1: the differential interval, posed support, measures, graph and forcing

def interval(eb_plate=Q(1, 2**60), eb_row=Q(1, 2**61), interval_id="i-x", **kw):
    record = dict(schema=C.DG_SCHEMA, method=C.DG_METHOD, interval_id=interval_id, parent_network_id="n0",
                  endpoint_network_id="n1", motion_id="m", motion={"rule": "r"},
                  plate_angular_velocity_rad_s={"p1": [enc(0), enc(0), enc(1)]}, duration_s=enc(10),
                  start_time_s=enc(0), end_time_s=enc(10), endpoint_binding_limit_rad=0.001,
                  plate_endpoint_operator_error_bounds={"p1": enc(eb_plate)},
                  boundary_paths=[dict(boundary_id="b1", kind="ridge", endpoint_operator_error_bound=enc(eb_row))],
                  rays=[], ownership_fans=[], certified_time_partition_s=[[enc(0), enc(10)]],
                  orientation_max_leaves=64, orientation_work_units=12, trajectory={"segments": []},
                  trajectory_id="t", prior_trajectory_id="t0")
    record.update(kw)
    return record


class Interval(unittest.TestCase):
    STEP = Q(1, 2**93)          # 2**-13 * min(eb, 2**-80) for eb = 2**-60

    def test_1a_band_pass_and_fail(self):
        eb = Q(1, 2**60)
        ok, _ = run("differential", interval(eb), interval(eb+3*self.STEP, eb_row=Q(1, 2**61)+self.STEP))
        self.assertEqual(verdicts(ok), {"PASS"}, ok)
        # Both band edges are inside: -m <= (ea-eb)*2**13 <= 7m.
        edges, _ = run("differential", interval(eb), interval(eb+7*self.STEP, eb_row=Q(1, 2**61)-self.STEP))
        self.assertEqual(codes(edges), {"DESIGN_1A_BAND", "DESIGN_1B_EQUAL"}, edges)
        for ea in (eb+8*self.STEP, eb-2*self.STEP):
            bad, _ = run("differential", interval(eb), interval(ea))
            self.assertIn("DESIGN_1A_BAND_VIOLATION", codes(bad, "FAIL"))

    def test_1a_zero_identical_limit_and_precondition(self):
        bad, _ = run("differential", interval(Q(0)), interval(Q(1, 2**100)))
        self.assertIn("DESIGN_1A_EXACT_VIOLATION", codes(bad, "FAIL"))
        same = rows(after=BASE)
        bad, _ = run("differential", interval(), interval(Q(1, 2**60)+self.STEP), same)
        self.assertIn("DESIGN_1A_EXACT_VIOLATION", codes(bad, "FAIL"))
        bad, _ = run("differential", interval(), interval(Q(1, 500)))
        self.assertIn("DESIGN_1A_ABOVE_BINDING_LIMIT", codes(bad, "FAIL"))
        moved = interval(Q(1, 2**59), motion={"rule": "other"})
        review, consumed = run("differential", interval(), moved)
        self.assertNotIn("FAIL", verdicts(review))
        self.assertIn("DESIGN_1A_PRECONDITION_DIFFERS", codes(review, "REVIEW"))
        self.assertFalse(any(path[1] == "plate_endpoint_operator_error_bounds" for path in consumed))
        # A changed DG or an unreviewed module pairing is no reviewed route: REVIEW only.
        review, _ = run("differential", interval(), interval(Q(1, 2**59)), rows(after=dict(WIDTH, **{DG: "e"*64})))
        self.assertNotIn("FAIL", verdicts(review))

    def test_1b_difference_is_review_never_fail(self):
        flipped = interval(certified_time_partition_s=[[enc(0), enc(5)], [enc(5), enc(10)]], orientation_work_units=13)
        review, _ = run("differential", interval(), flipped)
        self.assertEqual(codes(review, "REVIEW") & {"ORIENTATION_DECISION_FLIP"}, {"ORIENTATION_DECISION_FLIP"})
        self.assertNotIn("FAIL", verdicts(review))
        ok, _ = run("differential", interval(), interval())
        self.assertIn("DESIGN_1B_EQUAL", codes(ok, "PASS"))


def posed(normal, error, tree, endpoint="start", offset=Q(3)):
    return dict(schema=C.POSED_SUPPORT_SCHEMA, endpoint=endpoint, time_s=enc(0),
                constraints={"c1": dict(normal=[enc(v) for v in normal], error_euclidean=enc(error),
                                        offset=enc(offset))},
                physical_constraint_record={"c1": tree})


ROTATED = {"kind": "rotated-normal", "normal": [enc(1), enc(Q(1, 3)), enc(0)], "angular_velocity_rad_s": [enc(0)]*3}
SNAP = {"kind": "snapshot-rotated", "constraint": ROTATED, "offset_s": enc(0)}
EDGE = {"kind": "moving-ray-edge", "constraint": None}
FIXED_SNAP = {"kind": "snapshot-rotated", "constraint": {"kind": "fixed-plane", "constraint": None}}


class PosedSupport(unittest.TestCase):
    NB, EB = (Q(5, 7), Q(2, 11), Q(1, 13)), Q(1, 2**70)

    def width(self, tree):
        scale = max(abs(C.source_exact(v)) for v in (tree if tree["kind"] == "rotated-normal" else tree["constraint"])
                    ["normal"])
        q = Q(2)**(C.floor_log2(min(self.EB, scale/2**80))-12)
        return tuple(round(c/q)*q for c in self.NB), -((-(self.EB+q))//q)*q, q

    def test_1c_recomputation_pass_and_fail(self):
        for tree in (SNAP, ROTATED):
            na, ea, q = self.width(tree)
            ok, _ = run("posed", posed(self.NB, self.EB, tree), posed(na, ea, tree))
            self.assertEqual(codes(ok), {"DESIGN_1C_RECOMPUTED"}, ok)
            bad, _ = run("posed", posed(self.NB, self.EB, tree), posed((na[0]+q,)+na[1:], ea, tree))
            self.assertIn("DESIGN_1C_RECOMPUTATION_DIFFERS", codes(bad, "FAIL"))

    def test_1c_zero_error_and_certificates(self):
        bad, _ = run("posed", posed(self.NB, 0, SNAP), posed((Q(5, 7), Q(2, 11), Q(1, 12)), 0, SNAP))
        self.assertIn("DESIGN_1C_ZERO_ERROR_CHANGED", codes(bad, "FAIL"))
        edge = {"kind": "snapshot-rotated", "constraint": EDGE}
        review, _ = run("posed", posed(self.NB, 0, edge), posed((1, 0, 0), 0, edge))
        self.assertEqual(verdicts(review), {"REVIEW"})
        # 1-D narrowing: any moving-ray-edge node keeps a positive-error difference REVIEW.
        for tree in (EDGE, edge):
            review, _ = run("posed", posed(self.NB, self.EB, tree), posed((9, 9, 9), self.EB, tree))
            self.assertEqual(codes(review), {"DESIGN_1D_CERTIFICATE_POSSIBLE"})
        review, _ = run("posed", posed(self.NB, self.EB, SNAP, "end"), posed((9, 9, 9), self.EB, SNAP, "end"))
        self.assertEqual(verdicts(review), {"REVIEW"})

    def test_1d_inconsistent_enclosures_fail(self):
        bad, _ = run("posed", posed(self.NB, self.EB, FIXED_SNAP), posed((9, 9, 9), self.EB, FIXED_SNAP))
        self.assertIn("DESIGN_1D_ENCLOSURES_INCONSISTENT", codes(bad, "FAIL"))
        near = (self.NB[0]+self.EB, self.NB[1], self.NB[2])
        review, _ = run("posed", posed(self.NB, self.EB, FIXED_SNAP), posed(near, self.EB, FIXED_SNAP))
        self.assertEqual(codes(review), {"DESIGN_1D_NO_RULE"})


def measure(inward=(1, 2), met=True, widths=(1, 1)):
    return dict(schema=C.DG_MEASURE_SCHEMA, measure_id="m", query={"q": 1}, max_widths=[enc(w) for w in widths],
                inward_volume_bounds_m3=[enc(inward[0]), enc(inward[1])], outward_volume_bounds_m3=[enc(3), enc(4)],
                moment_bounds=[[enc(0), enc(1)]], leaves=4, met=met, work_units=3, segments=[])


class Measures(unittest.TestCase):
    def test_1e_controls(self):
        bad, consumed = run("graph", measure(), measure(inward=(3, 4)))
        self.assertIn("DESIGN_1E_ENCLOSURES_DISJOINT", codes(bad, "FAIL"))
        self.assertEqual(consumed, set())
        bad, _ = run("graph", measure(inward=(1, Q(6, 5)), widths=(Q(1, 4), 1)),
                     measure(inward=(Q(11, 10), Q(3, 2)), widths=(Q(1, 4), 1)))
        self.assertIn("DESIGN_1E_WIDTH_CONTRADICTION", codes(bad, "FAIL"))
        review, _ = run("graph", measure(), measure(inward=(Q(3, 2), 2), met=False))
        self.assertEqual(codes(review), {"DESIGN_1E_MET_FLIP"})
        other = dict(measure(inward=(3, 4)), query={"q": 2})
        self.assertEqual(verdicts(run("graph", measure(), other)[0]), {"REVIEW"})


DUAL = C.DUAL_CLOSURE_METHOD + " carried signed start error rebased to selected G0"
CARRIED = "true-minus-booked volume; carried signed start error plus original directed stream intervals"


def graph(start=(1, 3), finite=(5, 5), face=(0, 1), interval_id="i-b", method=DUAL):
    return dict(schema=C.GRAPH_SCHEMA, booked="x", interval_id=interval_id, geometry_error_method=method,
                cells=[dict(cell_id="c1", kind="exterior", start_volume_bounds_m3=[enc(start[0]), enc(start[1])],
                            end_volume_bounds_m3=[enc(2), enc(4)], start_volume_m3=enc(start[0]), end_volume_m3=enc(3)),
                       dict(cell_id="finite-stock:s", kind="finite-inventory",
                            start_volume_bounds_m3=[enc(finite[0]), enc(finite[1])],
                            end_volume_bounds_m3=[enc(0), enc(9)], start_volume_m3=enc(finite[0]), end_volume_m3=enc(1))],
                inactive_zero_measure_cells=[],
                selected_face_representatives=[dict(face_id="f1", donor="c1", receiver="c2",
                                                    volume_bounds_m3=[enc(face[0]), enc(face[1])],
                                                    volume_m3=enc(face[0]), max_deviation_m3=enc(0))])


def graph_a(**kw):
    return graph(**dict(dict(interval_id="i-a"), **kw))


def forcing(geometry_id, bounds=((0, 1), (2, 3), (-1, 1)), **kw):
    record = dict(schema=C.FORCING_SCHEMA, geometry_id=geometry_id, time_s=enc(10), plate_ids=["p1"], source={"s": 1},
                  funding_id="f", native_plan_id="np", native_material_source="nm", pressure_reference=None,
                  radial_datum={"r": 1}, reservoir_native_side="out", reservoir_pressure={"p": 1},
                  physical_densities={"d": 1}, request={"w": 1},
                  cut_face_certificates=[dict(cell_id="box1", axis=0, end=1, plate_id="p1",
                                              certificate_id="cert-" + geometry_id,
                                              bounds_n_m=[[enc(lo), enc(hi)] for lo, hi in bounds])],
                  exact_torque_bounds={"reservoir_imposed_cut_torque_n_m": [[[enc(lo), enc(hi)] for lo, hi in bounds]]})
    record.update(kw)
    return record


def observed(old=None, new=None):
    design = rows()
    design.observe("differential", {"interval": old or interval(interval_id="i-b")},
                   {"interval": new or interval(Q(1, 2**60)+Q(1, 2**93), interval_id="i-a")})
    return design


class GraphAndForcing(unittest.TestCase):
    def test_graph_disjoint_fails_only_on_proved_inputs(self):
        self.assertTrue(observed().motion)
        bad, consumed = run("graph", graph(), graph_a(start=(4, 5)), observed())
        self.assertEqual(codes(bad, "FAIL"), {"DESIGN_1E_GRAPH_ENCLOSURES_DISJOINT"})
        self.assertEqual(consumed, set())
        bad, _ = run("graph", graph(), graph_a(face=(2, 3)), observed())
        self.assertEqual(codes(bad, "FAIL"), {"DESIGN_1E_GRAPH_FACE_ENCLOSURES_DISJOINT"})
        review, _ = run("graph", graph(), graph_a(start=(2, 5), finite=(6, 6)), observed())
        self.assertEqual(verdicts(review), {"REVIEW"})       # retained stocks are not enclosures
        moved = observed(new=interval(interval_id="i-a", motion={"rule": "other"}))
        self.assertFalse(moved.motion)
        review, _ = run("graph", graph(), graph_a(start=(4, 5)), moved)
        self.assertEqual(codes(review), {"DESIGN_1E_GRAPH_INPUTS_NOT_PROVED"})

    def test_graph_needs_the_dual_closure_and_its_own_interval(self):
        # Row 1-E, carried start: the carried closure stores each arm's own carried start as [B]*2, so
        # carried starts 3 and 3+2^-40 over one true start [2, 4] are disjoint with both producers correct.
        start_b, start_a = (3, 3), (3+Q(1, 2**40),)*2
        for old in (graph(start=start_b, method=CARRIED), graph(start=start_b)):
            review, _ = run("graph", old, graph_a(start=start_a, method=CARRIED), observed())
            self.assertEqual(codes(review), {"DESIGN_1E_GRAPH_NOT_DUAL_CLOSURE"})
        bad, _ = run("graph", graph(start=start_b), graph_a(start=start_a), observed())
        self.assertEqual(codes(bad, "FAIL"), {"DESIGN_1E_GRAPH_ENCLOSURES_DISJOINT"})   # the dual layout decides
        # A graph without its own arm's differential interval_id proves nothing either.
        for new in (graph(start=(4, 5)), graph_a(start=(4, 5), interval_id=None)):
            review, _ = run("graph", graph(), new, observed())
            self.assertEqual(codes(review), {"DESIGN_1E_GRAPH_INTERVAL_NOT_BOUND"})

    def test_cut_face_disjoint_fails_only_when_bound_to_the_interval(self):
        far = ((5, 6), (2, 3), (-1, 1))
        bad, _ = run("certification", {"force": forcing("i-b")}, {"force": forcing("i-a", far)}, observed())
        self.assertEqual(codes(bad, "FAIL"), {"DESIGN_1E_CUT_TORQUE_DISJOINT"})
        self.assertEqual(sum(r["verdict"] == "FAIL" for r in bad), 2)     # certificate and the per-plate sum
        review, _ = run("certification", {"force": forcing("i-b")}, {"force": forcing("i-a", ((Q(1, 2), 2),)*3)},
                        observed())
        self.assertEqual(verdicts(review), {"REVIEW"})
        for new in (forcing("other", far), forcing("i-a", far, reservoir_pressure={"p": 2})):
            review, _ = run("certification", {"force": forcing("i-b")}, {"force": new}, observed())
            self.assertEqual(codes(review), {"DESIGN_1E_FORCING_INPUTS_NOT_PROVED"})


# -- families 1b and 4: the E thermal mesh

CONE = [["r1"], ["r2"], ["r3"]]
VOXEL = dict(lower_m=[enc(0)]*3, upper_m=[enc(1)]*3, origin_m=[enc(100), enc(0), enc(0)],
             basis=[[1, 0, 0], [0, 1, 0], [0, 0, 1]])
MOVING = [dict(start_time_s=enc(0), end_time_s=enc(10), angular_velocity_rad_s=[enc(0), enc(0), enc(1)])]
STILL = [dict(start_time_s=enc(0), end_time_s=enc(10), angular_velocity_rad_s=[enc(0)]*3)]


def e_mesh(volume=Q(1, 2), bounds=(Q(2, 5), Q(3, 5)), bound=Q(1, 2**20), pin=C.E_SOURCE, segments=MOVING,
           centroid=(Q(1, 2),)*3, swap=False, source_key="k1", header=None, dev=None, quaternion=(1, 0, 0, 0)):
    lo, hi = bounds
    dev = max(abs(volume-lo), abs(volume-hi)) if dev is None else dev
    collar = dict(cell_id="collar-1", kind="collar", volume_m3=enc(2), centroid_m=[enc(0)]*3,
                  physical_volume_bounds_m3=[enc(2), enc(2)], geometry_volume_max_deviation_m3=enc(0),
                  physical_cell_id="box")
    exterior = dict(cell_id="ext-1", kind="exterior", logical_cell_id="L1", source_key=source_key,
                    voxel_index=[0, 0, 0], radial_band=0, chart="c", physical_cell_id="pc",
                    physical_support=dict(cone_id="cone-1", voxel_id="vox-1"), volume_m3=enc(volume),
                    centroid_m=[enc(c) for c in centroid], physical_volume_bounds_m3=[enc(lo), enc(hi)],
                    geometry_volume_max_deviation_m3=enc(dev))
    width = Q(1, 8)
    stored = dev if pin == C.E_SOURCE else C.stored_deviation(dev, width)
    return dict(schema=C.MESH_SCHEMA, trajectory_id="t", trajectory_segments=segments, endpoint="end",
                max_geometry_volume_error_m3=enc(width), funding_id="f", source={"s": 1}, support_id="s",
                time_s=enc(10), grid_id="g", grid_lines=[], support_tables=dict(cones={"cone-1": CONE},
                                                                                voxels={"vox-1": VOXEL}),
                representative_quaternion=[enc(q) for q in quaternion], pose_operator_error_bound=enc(bound),
                geometry_volume_max_deviation_m3=enc(stored if header is None else header),
                cells=[exterior, collar] if swap else [collar, exterior], faces=[])


def widened(**kw):
    kw.setdefault("bound", Q(1, 2**20)+Q(1, 2**32))
    return e_mesh(pin=C.E_ROUNDED, **kw)


class ExteriorMesh(unittest.TestCase):
    def test_small_pose_change_passes_4_3_to_4_7(self):
        ok, consumed = run("mesh", e_mesh(), widened(volume=Q(1, 2)+Q(1, 2**24)))
        self.assertNotIn("FAIL", verdicts(ok), ok)
        self.assertTrue({"DESIGN_4_3_VOLUME", "DESIGN_4_6_DEVIATION", "DESIGN_4_7_HEADER_WITHIN_BOUND"} <=
                        codes(ok, "PASS"), ok)
        self.assertIn(("mesh", "cells", "1", "volume_m3"), consumed)

    def test_4_x_fail_controls(self):
        bad, _ = run("mesh", e_mesh(), widened(volume=Q(1, 2)+Q(1, 2**18)))
        self.assertIn("DESIGN_4_3_VOLUME_VIOLATION", codes(bad, "FAIL"))
        bad, _ = run("mesh", e_mesh(), widened(centroid=(Q(3, 2), Q(1, 2), Q(1, 2))))
        self.assertIn("DESIGN_4_4_CENTROID_VIOLATION", codes(bad, "FAIL"))
        bad, _ = run("mesh", e_mesh(), widened(source_key="k2"))
        self.assertIn("DESIGN_4_2_POSE_INDEPENDENT_CHANGED", codes(bad, "FAIL"))
        bad, _ = run("mesh", e_mesh(), dict(widened(), grid_id="g2"))         # a static header field
        self.assertIn(["mesh", "grid_id"], [r["path"] for r in bad if r["verdict"] == "FAIL" and
                                            r["code"] == "DESIGN_4_2_POSE_INDEPENDENT_CHANGED"])
        bad, _ = run("mesh", e_mesh(), widened(swap=True))
        self.assertIn("DESIGN_4_2_CELL_ORDER_CHANGED", codes(bad, "FAIL"))
        bad, _ = run("mesh", e_mesh(), widened(dev=Q(1, 10)+Q(1, 2**30)))
        self.assertIn("DESIGN_4_6_WITHIN_ARM_IDENTITY", codes(bad, "FAIL"))
        stored = C.stored_deviation(Q(1, 10), Q(1, 8))
        bad, _ = run("mesh", e_mesh(), widened(header=stored+Q(1, 2**70)))
        self.assertIn("DESIGN_4_7_HEADER_IDENTITY", codes(bad, "FAIL"))
        review, _ = run("mesh", e_mesh(), widened(bound=Q(1, 2**20)+Q(1, 2**30)))  # C2 fails: no radius
        self.assertNotIn("FAIL", {r["verdict"] for r in review if (r.get("row") or "").startswith("4.")})

    def test_f4_3_radius_magnitude(self):
        # F4-3 from the design formula, computed here independently: S_c = N_c*r_R*min((8/3)rho^3, 2*rho*D^2)
        # with r_R = (pa-pb)/(1-pb/4), rho^2 = sum_j max over the voxel corners (identity basis, origin
        # (100,0,0)) and D^2 the voxel diagonal squared. A volume change just below S_c PASSes 4.3, 4.6 and
        # 4.7; just above it FAILs all three.
        pb, pa = Q(1, 2**20), Q(1, 2**20)+Q(1, 2**32)
        r, rho2, d2 = (pa-pb)/(1-pb/4), Q(101**2+1+1), Q(3)
        s2 = (len(CONE)*r)**2*min(Q(64, 9)*rho2**3, 4*rho2*d2**2)
        root = Q(math.isqrt(math.floor(s2*4**80)), 2**80)              # root <= S_c < root + 2**-80
        below, above = root*(1-Q(1, 2**10)), (root+Q(1, 2**80))*(1+Q(1, 2**10))
        ok, _ = run("mesh", e_mesh(), widened(volume=Q(1, 2)+below))
        self.assertTrue({"DESIGN_4_3_VOLUME", "DESIGN_4_6_DEVIATION", "DESIGN_4_7_HEADER_WITHIN_BOUND"} <=
                        codes(ok, "PASS") and "FAIL" not in verdicts(ok), ok)
        bad, _ = run("mesh", e_mesh(), widened(volume=Q(1, 2)+above))
        self.assertTrue({"DESIGN_4_3_VOLUME_VIOLATION", "DESIGN_4_6_DEVIATION_VIOLATION",
                         "DESIGN_4_7_HEADER_BOUND_VIOLATION"} <= codes(bad, "FAIL"), bad)

    def test_4_1_norm_band(self):
        # E mesh header norm band: the header stores no rotation, so r_R rests on E's per-arm norm band. A quaternion
        # of norm 1/2 passes C1-C4 against itself but no E arm can store it: FAIL, and no row PASSes on r_R.
        half = (Q(1, 2), 0, 0, 0)
        bad, _ = run("mesh", e_mesh(quaternion=half), widened(quaternion=half, volume=Q(1, 2)+Q(1, 2**24)))
        self.assertIn("DESIGN_4_1_QUATERNION_NORM_OUTSIDE_BAND", codes(bad, "FAIL"))
        self.assertEqual([r["arms"] for r in bad if r["code"] == "DESIGN_4_1_QUATERNION_NORM_OUTSIDE_BAND"],
                         [["before", "after"]])
        self.assertNotIn("DESIGN_4_3_VOLUME", codes(bad, "PASS"))
        self.assertIn("DESIGN_4_POSE_PREREQUISITE_NOT_MET", codes(bad, "REVIEW"))
        self.assertTrue(C.within_norm_band((1, 0, 0, 0), 0) and C.within_norm_band((Q(3, 5), 0, 0, Q(4, 5)), 0))
        self.assertTrue(C.within_norm_band((Q(9, 10), 0, 0, 0), Q(2, 5)))        # | |q| - 1 | = p/4 exactly
        self.assertFalse(C.within_norm_band((Q(9, 10)-Q(1, 2**40), 0, 0, 0), Q(2, 5)))

    def test_vacuous_bound_is_review(self):
        small = dict(volume=Q(1, 10), bounds=(Q(1, 20), Q(3, 20)), bound=Q(1, 2))
        review, _ = run("mesh", e_mesh(**small), e_mesh(pin=C.E_ROUNDED, **dict(small, volume=Q(1, 10)+Q(1, 2**10),
                                                                                bound=Q(1, 2)+Q(1, 2**13))))
        self.assertIn("DESIGN_4_3_VOLUME_VACUOUS", codes(review, "REVIEW"))
        self.assertNotIn("DESIGN_4_3_VOLUME_VIOLATION", codes(review))

    def test_1b_zero_motion_and_header(self):
        ok, _ = run("mesh", e_mesh(segments=STILL), widened(segments=STILL))
        self.assertIn("DESIGN_1B_A_ZERO_MOTION_IDENTITY", codes(ok, "PASS"))
        self.assertIn("DESIGN_1B_D_RULE_CE", codes(ok, "PASS"))
        bad, _ = run("mesh", e_mesh(segments=STILL), widened(segments=STILL, bounds=(Q(2, 5)-Q(1, 2**30), Q(3, 5))))
        self.assertIn("DESIGN_1B_A_ZERO_MOTION_BOUNDS_CHANGED", codes(bad, "FAIL"))
        review, _ = run("mesh", e_mesh(), dict(e_mesh(pin=C.E_ROUNDED), source={"s": 2}))
        self.assertEqual(codes(review), {"DESIGN_4_PRECONDITION_DIFFERS"})


def m_mesh(header, cells=((Q(10), Q(29, 3), Q(51, 5)),)):
    rows = [dict(cell_id="m%d" % i, kind="exterior", logical_cell_id="L%d" % i,
                 physical_support=dict(differential_support_id="D", logical_cell_id="L%d" % i),
                 volume_m3=enc(v), physical_volume_bounds_m3=[enc(lo), enc(hi)],
                 geometry_volume_max_deviation_m3=enc(max(abs(v-lo), abs(v-hi)))) for i, (v, lo, hi) in enumerate(cells)]
    return dict(schema=C.MESH_SCHEMA, physical_geometry_family=C.DIFFERENTIAL_FAMILY, cells=rows,
                geometry_volume_max_deviation_m3=enc(header), max_geometry_volume_error_m3=enc(100))


class DifferentialMeshHeader(unittest.TestCase):
    def test_5_10_exact_formula_by_producer(self):
        total = Q(1, 3)
        ok, _ = run("mesh", m_mesh(total), m_mesh(C.stored_deviation(total, Q(100))))
        self.assertEqual(ok, [])
        inside = total+Q(1, 2**70)          # Addendum E's inequality accepts it; the exact formula does not
        self.assertEqual(C.evaluate_header(enc(inside), enc(total), enc(100))["verdict"], "PASS")
        bad, _ = run("mesh", m_mesh(total), m_mesh(inside))
        self.assertEqual(codes(bad, "FAIL"), {"DESIGN_5_10_EXACT_HEADER_FORMULA"})
        bad, _ = run("mesh", m_mesh(inside), m_mesh(C.stored_deviation(total, Q(100))))
        self.assertEqual([r["arm"] for r in bad], ["before"])
        # Only the logical mesh record itself, never a mesh-schema copy nested in another record.
        self.assertEqual(run("state", {"thermal_mesh": m_mesh(total)}, {"thermal_mesh": m_mesh(inside)})[0], [])


# -- family 2: the E pose consumers outside E

def bpose(q, p, rotation=None):
    return dict(schema=C.BOUNDARY_POSE_SCHEMA, representative_quaternion=[enc(x) for x in q],
                pose_operator_error_bound=enc(p), requested_operator_error=enc(Q(1, 2**10)),
                boundary_rotations=[dict(angular_velocity_rad_s=[enc(0), enc(0), enc(1)], start_time_s=enc(0),
                                         end_time_s=enc(10))],
                rotation_matrix=[[enc(v) for v in row] for row in (rotation or C.rotation_of(tuple(map(Q, q))))])


def background(p, force=None, q=(Q(3, 5), 0, 0, Q(4, 5))):
    residual, matrix_residual, rate = [Q(1, 2**40)], [[Q(1, 2**41)]], Q(1, 2**30)
    fe = p*10+sum(map(abs, residual)) if force is None else force
    me = 2*p*4+sum(abs(v) for row in matrix_residual for v in row)
    pose = dict(trajectory_id="t", requested_operator_error=enc(Q(1, 2**10)), representative_quaternion=[enc(x) for x in q],
                operator_error_bound=enc(p), representative_rotation=[[enc(v) for v in row] for row in
                                                                      C.rotation_of(tuple(map(Q, q)))])
    return dict(schema=C.FORCE_BACKGROUND_SCHEMA, pose=pose, exterior_balance_id="eb", exterior_prepared_id="ep",
                force_error_bound_n_m=enc(fe), resistance_operator_error_bound_j_s=enc(me),
                power_error_bound_w=enc(fe*rate+me*rate**2), angular_rate_l2_bound_s_inv=enc(rate),
                requested_torque_error_n_m=enc(1), requested_power_error_w=enc(1),
                force_projection_residual_n_m=[enc(v) for v in residual],
                resistance_projection_residual_j_s=[[enc(v) for v in row] for row in matrix_residual])


class Poses(unittest.TestCase):
    QB, PB, PA = (Q(3, 5), 0, 0, Q(4, 5)), Q(1, 2**20), Q(1, 2**20)+Q(1, 2**32)

    def test_2_1_to_2_3(self):
        coaxial = (Q(3, 5)+Q(1, 2**36), 0, 0, Q(4, 5))
        ok, _ = run("x", bpose(self.QB, self.PB), bpose(coaxial, self.PA))
        self.assertEqual(verdicts(ok), {"PASS"}, ok)
        self.assertIn("DESIGN_2_3_AXIS_CERTIFICATE_EQUAL", codes(ok))
        # Componentwise rounding control: an off-axis component loses the common-axis certificate.
        bad, _ = run("x", bpose(self.QB, self.PB), bpose((Q(3, 5), Q(1, 2**36), 0, Q(4, 5)), self.PA))
        self.assertIn("DESIGN_2_3_AXIS_CERTIFICATE_CHANGED", codes(bad, "FAIL"))
        bad, _ = run("x", bpose(self.QB, self.PB), bpose(coaxial, self.PB+Q(1, 2**30)))
        self.assertIn("DESIGN_QUATERNION_RULE_VIOLATION", codes(bad, "FAIL"))
        identity = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
        bad, _ = run("x", bpose(self.QB, self.PB), bpose(coaxial, self.PA, rotation=identity))
        self.assertIn("DESIGN_ROTATION_NOT_FROM_QUATERNION", codes(bad, "FAIL"))

    def test_2_2_half_turn_within_c1_c2_c4_fails(self):
        # Norm band, far quaternions: C1, C2 and C4 hold and each R = M(q)/|q|^2, but the quaternions are far
        # from unit and the rotations are I and a half turn about the common axis. Only the 2.2 radius catches it.
        qb, qa = (Q(1, 2**16), 0, 0, 0), (0, 0, 0, Q(1, 2**16))
        bad, _ = run("x", bpose(qb, Q(1, 2)), bpose(qa, Q(1, 2)+Q(1, 2**13)))
        self.assertIn("DESIGN_QUATERNION_C1_C2_C4", codes(bad, "PASS"))
        self.assertEqual(codes(bad, "FAIL"), {"DESIGN_ROTATION_RADIUS_VIOLATION"})

    def test_2_8_identities_and_reachability(self):
        ok, _ = run("x", background(self.PB), background(self.PA))
        self.assertIn("DESIGN_2_8_CURRENT_FORCE_BACKGROUND_REACHED", codes(ok, "REVIEW"))
        self.assertIn("DESIGN_2_8_ERROR_IDENTITIES", codes(ok, "PASS"))
        bad, _ = run("x", background(self.PB), background(self.PA, force=self.PA*10+Q(1, 2**40)+Q(1, 2**50)))
        self.assertIn("DESIGN_2_8_ERROR_IDENTITY_VIOLATION", codes(bad, "FAIL"))


# -- family 5: the joined heat plan, references, audit array and ledger

def plan(target=Q(1, 1024), text="0.0009765625", original=None, boundary=None):
    return dict(schema=C.HEAT_PLAN_SCHEMA, method_id="m", geometry_id="g", conductivity_w_m_k=[1.0],
                absolute_residual_target=enc(target), absolute_residual_target_decimal=text,
                original_target=original or {"kind": "decimal-string", "value": "0.0009765625"},
                boundary=boundary or {"f1": ["power", 0.0]}, endpoint_face_trace_status="s")


def reference(original=None, **kw):
    return dict(dict(schema=C.HEAT_REF_SCHEMA, result_id="r", geometry_id="g", plan_id="p", duration_s=enc(10),
                     method_id=C.HEAT_METHOD, consumer_sources={"a.py": "1"*64},
                     original_target=original or {"kind": "decimal-string", "value": "0.0009765625"}), **kw)


def exchange(heat_plan=None, ref=None):
    return dict(schema="exchange", joined_heat=ref or reference(), joined_heat_plan=heat_plan or plan())


def run_exchange(old, new):
    design = rows()
    design.observe("exchange", old, new)        # compare_arms observes the exchange before its record walk
    return run("exchange", old, new, design)


class Heat(unittest.TestCase):
    def test_5_8_plan_targets(self):
        ok, consumed = run_exchange(exchange(), exchange())
        self.assertEqual(codes(ok), {"DESIGN_5_8_TARGET_EQUAL", "DESIGN_5_8_REFERENCE_TARGET_EQUAL"})
        self.assertIn(("exchange", "joined_heat_plan", "absolute_residual_target"), consumed)
        changed = plan(Q(1, 512), "0.001953125")
        bad, _ = run_exchange(exchange(), exchange(changed))
        self.assertIn("DESIGN_5_8_TARGET_CHANGED", codes(bad, "FAIL"))
        caller = plan(Q(1, 512), "0.001953125", {"kind": "decimal-string", "value": "0.001953125"})
        review, _ = run_exchange(exchange(), exchange(caller, reference(caller["original_target"])))
        self.assertEqual(verdicts(review), {"REVIEW"})
        for broken in (plan(text="0.001"), plan(Q(0), "0")):
            bad, _ = run_exchange(exchange(), exchange(broken))
            self.assertIn("DESIGN_5_8_PLAN_TARGET_INCONSISTENT", codes(bad, "FAIL"))
        # The reference inside the exchange repeats its own arm's plan.
        bad, _ = run_exchange(exchange(), exchange(ref=reference({"kind": "decimal-string", "value": "0.5"})))
        self.assertIn("DESIGN_5_8_REFERENCE_TARGET_NOT_PLAN", codes(bad, "FAIL"))

    def test_5_8_reference_repeats_its_plan(self):
        design = rows()
        design.observe("exchange", exchange(), exchange())
        self.assertIn("DESIGN_5_8_REFERENCE_TARGET_EQUAL", codes(run("heat", reference(), reference(), design)[0]))
        other = reference({"kind": "decimal-string", "value": "0.5"})
        bad, _ = run("heat", reference(), other, design)
        self.assertIn("DESIGN_5_8_REFERENCE_TARGET_NOT_PLAN", codes(bad, "FAIL"))

    def audit(self, words, *, ref=None, n=3, dtype="<f8"):
        design = rows()
        design.observe("exchange", exchange(), exchange(ref=ref))
        design.observe("mesh", {"schema": C.MESH_SCHEMA, "cells": [{}]*n, "faces": []},
                       {"schema": C.MESH_SCHEMA, "cells": [{}]*n, "faces": []})
        with tempfile.TemporaryDirectory() as folder:
            arrays, entries = Path(folder)/"arrays", []
            arrays.mkdir()
            for index, values in enumerate(words):
                raw = b"".join(v.to_bytes(8, "little") for v in values)
                (arrays/("%04d.bin" % index)).write_bytes(raw)
                entries.append([{"name": C.AUDIT_SOURCE, "file": "%04d.bin" % index, "dtype": dtype, "shape": [n],
                                 "sha256": hashlib.sha256(raw).hexdigest()}])
            return design.audit_source("arrays", {"before": entries[0], "after": entries[1]},
                                       {"before": Path(folder), "after": Path(folder)})

    def test_5_6_audit_array(self):
        zero, one, negative = [0, 0, 0], [0, 0x3FF0000000000000, 0], [0, 1 << 63, 0]
        self.assertEqual(codes(self.audit([zero, zero])), {"DESIGN_5_6_ZERO_SOURCE_AUDIT"})
        self.assertEqual(codes(self.audit([zero, one]), "FAIL"), {"DESIGN_5_6_NONZERO_SOURCE"})
        self.assertEqual(codes(self.audit([zero, negative])), {"DESIGN_5_6_NEGATIVE_ZERO"})
        self.assertEqual(codes(self.audit([zero, one], dtype="<f4")), {"DESIGN_5_6_AUDIT_ARRAY_UNBOUND"})
        self.assertEqual(codes(self.audit([zero, one], ref=reference(method_id="other"))),
                         {"DESIGN_5_6_ROUTE_NOT_ESTABLISHED"})

    def ledger(self, **kw):
        record = dict(schema=C.HEAT_SCHEMA, source_policy=C.ZERO_SOURCE_POLICY,
                      caller_snapshot={"source_policy": C.ZERO_SOURCE_POLICY}, exact_source_energy_j=["0x0", "0x1"],
                      independently_supplied_absolute_residual_target=enc(Q(1, 1024)),
                      private_correction_method_id=C.FINISHER, geometry_id="g", plan_id="p", duration_s=enc(10),
                      exact_outward_boundary_energy_j=enc(20), **{k: enc(1) for k in C.HEAT_NUMERICAL[1:6]})
        record.update(kw)
        return record

    def heat_rows(self, old, new, boundary=None, ref=None):
        design = rows()
        heat_plan = plan(boundary=boundary or {"f1": ["power", 2.0], "f2": ["power", 5.0]})
        design.observe("exchange", exchange(heat_plan), exchange(heat_plan, ref))
        mesh = {"schema": C.MESH_SCHEMA, "cells": [], "faces": [{"face_id": "f1", "owners": ["c"]},
                                                                  {"face_id": "f2", "owners": ["c", "d"]}]}
        design.observe("mesh", mesh, mesh)
        design.observe("state", {"schema": C.STATE_SCHEMA, "thermal_mesh_id": "g"},
                       {"schema": C.STATE_SCHEMA, "thermal_mesh_id": "g"})
        return run("heat", old, new, design)[0]

    def test_ledger_rows(self):
        ok = self.heat_rows(self.ledger(), self.ledger())
        self.assertTrue({"DESIGN_5_6_ZERO_SOURCE", "DESIGN_5_8_TARGET_EQUAL", "DESIGN_5_7A_DECLARED_OUTWARD",
                         "DESIGN_5_9_BITWISE_EQUAL"} <= codes(ok, "PASS"), ok)
        bad = self.heat_rows(self.ledger(), self.ledger(exact_source_energy_j=enc(1)))
        self.assertIn("DESIGN_5_6_SOURCE_ENERGY_NOT_ZERO", codes(bad, "FAIL"))
        bad = self.heat_rows(self.ledger(), self.ledger(exact_outward_boundary_energy_j=enc(21)))
        self.assertIn("DESIGN_5_7A_OUTWARD_NOT_DECLARED", codes(bad, "FAIL"))
        review = self.heat_rows(self.ledger(), self.ledger(), boundary={"f1": ["temperature", 300.0]})
        self.assertNotIn("FAIL", verdicts(review))
        # 5.9 BINDING CORRECTION: a difference under identical inputs is REVIEW, never FAIL.
        review = self.heat_rows(self.ledger(), self.ledger(exact_corrected_enthalpy_j=enc(2)))
        self.assertIn("DESIGN_5_9_DIFFERENCE_UNDER_IDENTICAL_INPUTS", codes(review, "REVIEW"))
        self.assertNotIn("FAIL", verdicts(review))

    def test_5_8_needs_the_heat_route(self):
        # Row 5.8 heat route: equal original targets give equal targets only under identical r13 helpers,
        # which the references' consumer_sources pin. Another method or other consumer sources leave a target
        # change REVIEW, in the plan and in the heat record alike.
        moved = plan(Q(1, 512), "0.001953125")
        target = dict(independently_supplied_absolute_residual_target=enc(Q(1, 512)))
        bad = self.heat_rows(self.ledger(), self.ledger(**target))
        self.assertIn("DESIGN_5_8_TARGET_CHANGED", codes(bad, "FAIL"))
        for ref in (reference(consumer_sources={"a.py": "2"*64}), reference(method_id="other")):
            with self.subTest(ref=ref["method_id"]):
                review, _ = run_exchange(exchange(), exchange(moved, ref))
                self.assertIn("DESIGN_5_8_ROUTE_NOT_ESTABLISHED", codes(review, "REVIEW"))
                self.assertNotIn("DESIGN_5_8_TARGET_CHANGED", codes(review))
                review = self.heat_rows(self.ledger(), self.ledger(**target), ref=ref)
                self.assertIn("DESIGN_5_8_ROUTE_NOT_ESTABLISHED", codes(review, "REVIEW"))
                self.assertNotIn("DESIGN_5_8_TARGET_CHANGED", codes(review))


class Refusals(unittest.TestCase):
    def test_flip_is_review_and_zero_flips_grant_nothing(self):
        for row in ("1-G", "1b-G", "2.7", "5.11", None):
            self.assertEqual(C.refusal_result(True, False, row)["verdict"], "REVIEW")
            self.assertEqual(C.refusal_result(None, False, row)["verdict"], "REVIEW")
        self.assertEqual(C.refusal_result(False, False)["code"], "NO_REFUSAL_FLIP")
        self.assertEqual(set(C.REFUSAL_SITES), {k for k, v in C.DESIGN_ROWS.items() if v[1] == C.REFUSAL_ONLY})

    def test_catalogue(self):
        counts = {v: sum(1 for row in C.DESIGN_ROWS.values() if row[1] == v) for v in (C.RULE, C.REFUSAL_ONLY, C.NO_RULE)}
        self.assertEqual(counts, {C.RULE: 25, C.REFUSAL_ONLY: 4, C.NO_RULE: 27})
        groups = [g for g, _, _ in C.MISSED_CONSUMERS]
        self.assertEqual([groups.count(g) for g in ("W-pose", "E-pose", "W-enclosure", "Heat")], [7, 7, 6, 9])
        self.assertTrue(all(row[1] != C.RULE or row[2] for row in C.DESIGN_ROWS.values()))


# -- family 3: W records (field_provenance), on the r4 provenance fixtures

def owned_by(wall, key, other):
    record = json.loads(json.dumps(wall))
    start, end = PT.support_ids(PT.SEGMENTS)
    for row in record["rows"]:
        row["exterior_cell_key"] = key
    record["exterior_cells"][0].update(exterior_cell_key=key, start_support_id=PT.digest({"key": key, "support_id": start}),
                                       end_support_id=PT.digest({"key": key, "support_id": end}))
    record["exterior_cells"][1:] = [PT.zero_cell(other)]
    return PT.reseal(record)


class FamilyThree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        PT.require_sources()
        cls.src = PT.we_tree((PT.R4/"integration_wall_measures.py").read_bytes(),
                             (PT.R4/"integration_exterior_mesh.py").read_bytes())
        cls.rnd = PT.we_tree((PT.WR2/"integration_wall_measures.py").read_bytes(),
                             (PT.WR2/"integration_exterior_mesh.py").read_bytes())
        # An E pin outside the reviewed transforms: closure parity fails.
        cls.other = PT.we_tree((PT.WR2/"integration_wall_measures.py").read_bytes(),
                               (PT.WR2/"integration_exterior_mesh.py").read_bytes()+b"\n# parity control\n")

    def pair(self, old, new, after=None):
        records = {"before": PT.record_set(old), "after": PT.record_set(new)}
        pairs = [(records["before"]["exchange"]["identity"], records["after"]["exchange"]["identity"])]
        return PT.codes(PT.assess(self.src, after or self.rnd, records, pairs))

    def test_equal_and_settled_records_add_nothing(self):
        found = self.pair(PT.make_wall(PT.BASE_BOUNDS, PT.BASE_EXACT), PT.make_wall(PT.BASE_BOUNDS, PT.BASE_EXACT))
        self.assertFalse(found & set(PT.P.FAIL_CODES), found)

    def test_3_2_moved_owner_fails(self):
        wall = PT.make_wall([((0, 0), (2, 5))], [(0, 4)], extra_cells=(["layer", 1],))
        found = self.pair(wall, owned_by(wall, ["layer", 1], ["layer", 0]))
        self.assertIn("W_FACE_PARTITION_CONTRADICTION", found)
        # Both keys are unsettled over the union, so their changed chosen values are row 3.7, not 3.6.
        self.assertNotIn("W_SETTLED_CELL_CHOSEN_CHANGED", found)

    def test_3_6_settled_chosen_change_fails(self):
        wall = PT.make_wall(PT.BASE_BOUNDS, PT.BASE_EXACT)
        new = json.loads(json.dumps(wall))
        new["exterior_cells"][0]["chosen_volume_change_m3"] = enc(3)
        found = self.pair(wall, PT.reseal(new))
        self.assertIn("W_SETTLED_CELL_CHOSEN_CHANGED", found)
        self.assertIn("W_AGGREGATE_CHOSEN_CONTRADICTION", found)

    def test_3_8_first_interval_start_bounds(self):
        first = PT.SEGMENTS[:1]
        wall = PT.make_wall(PT.BASE_BOUNDS, PT.BASE_EXACT, segments=first)
        new = json.loads(json.dumps(wall))
        new["exterior_cells"][0]["start_volume_bounds_m3"] = [enc(5), enc(Q(15, 2))]
        self.assertIn("W_EXACT_START_BOUNDS_CHANGED", self.pair(wall, PT.reseal(new)))
        # Without closure parity the same difference stays REVIEW.
        self.assertNotIn("W_EXACT_START_BOUNDS_CHANGED", self.pair(wall, PT.reseal(new), after=self.other))
        later = PT.make_wall(PT.BASE_BOUNDS, PT.BASE_EXACT)
        new = json.loads(json.dumps(later))
        new["exterior_cells"][0]["start_volume_bounds_m3"] = [enc(5), enc(Q(15, 2))]
        self.assertNotIn("W_EXACT_START_BOUNDS_CHANGED", self.pair(later, PT.reseal(new)))


if __name__ == "__main__":
    import sys
    result = unittest.main(argv=[sys.argv[0]] + sys.argv[1:], exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
