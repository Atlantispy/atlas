"""Contract addendum rows (field_contracts.AddendumRows): focused controls. Synthetic records only; no
Atlas package, store or run.

usage (science interpreter, from this folder):  PYTHONHASHSEED=0 python -B test_contract_rows_r1.py -v
The dev tool set beside this folder is the candidate. The settled rows (rows.json and ADDENDUM-r1.md) are read
from PLAN04_ADDENDUM (a private record; unset, it is the current folder); the disposition checks skip without them.
"""
import copy
import importlib.util
import json
import math
import os
import sys
import unittest
from collections import Counter
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEV = HERE.parent / "n9-tools-r21"
ADDENDUM = Path(os.environ.get("PLAN04_ADDENDUM", "."))

if not sys.dont_write_bytecode:
    raise SystemExit("run with -B: no bytecode may be written beside the tool sources")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


Q = load("field_contracts", DEV / "field_contracts.py")
GEOMETRY = "geometry-" + "a" * 64


def q(value):
    """The producer's exact pair (private_heat_native_projection_r5:36)."""
    value = Fraction(value)
    return [hex(value.numerator), hex(value.denominator)]


def codes(items, verdict=None):
    return sorted(item["code"] for item in items if verdict is None or item["verdict"] == verdict)


def forcing(**changes):
    record = dict(schema=Q.FORCING_SCHEMA, geometry_id=GEOMETRY, native_state_id="native-1", funding_id="fund-1",
                  reservoir_closure_id="closure-1", radial_datum=q(6371000), physical_densities=[q(3300), q(1000)],
                  request={"duration_s": q(10)}, spatial_state_id="spatial-1",
                  boundary_pose_ids=[GEOMETRY, GEOMETRY], cut_torques=[1.0, 2.0])
    record.update(changes)
    return record


def heat(cells=3, target=Fraction(1, 10**6), retained=None, **changes):
    """A composed heat record whose per-cell lists meet the producer identities."""
    retained = retained or [Fraction((-1)**i, 10**9 * (i + 1)) for i in range(cells)]
    new = [Fraction(1, 3) + i for i in range(cells)]
    projection = [Fraction(n.numerator / n.denominator) - n for n in new]
    record = dict(schema=Q.HEAT_SCHEMA, independently_supplied_absolute_residual_target=q(target),
                  exact_corrected_enthalpy_j=[q(n) for n in new],
                  exact_retained_solver_residual_j=[q(r) for r in retained],
                  exact_stock_projection_residual_j=[q(p) for p in projection],
                  exact_cell_storage_residual_j=[q(r + p) for r, p in zip(retained, projection, strict=True)],
                  projection_resource_policy={"workers": 2, "peak_bytes": 1024})
    record.update(changes)
    return record


def evaluate(kind, before, after, interval=1, ids=None, parity=False):
    rows = Q.AddendumRows(interval, ids, parity=parity)
    items, consumed = rows.evaluate(kind, before, after)
    return items, consumed, rows


class Dispositions(unittest.TestCase):
    def settled(self, name):
        path = ADDENDUM / name
        if not path.is_file():
            self.skipTest("settled %s not present at %s" % (name, ADDENDUM))
        data = path.read_bytes()
        self.assertEqual(sha256(data).hexdigest(), Q.CONTRACT_ADDENDUM[name])
        return data

    def test_dispositions_equal_the_settled_rows(self):
        rows = json.loads(self.settled("rows.json"))
        self.assertEqual({row["id"]: row["disposition"] for row in rows},
                         {row: entry[0] for row, entry in Q.ADDENDUM_ROWS.items()})
        self.assertEqual(Q.AddendumRows(1).summary()["rows"], dict(Counter(r["disposition"] for r in rows)))

    def test_addendum_text_digest(self):
        self.settled("ADDENDUM-r1.md")

    def test_catalogued_rows_stay_review_or_derived(self):
        self.assertEqual(len(Q.ADDENDUM_ROWS), 46)
        for row, (disposition, where) in Q.ADDENDUM_ROWS.items():
            self.assertIn(disposition, {Q.REVIEW_ROW, Q.DROPPED, Q.DERIVED, Q.RULE, Q.NOT_REACHED, Q.EXCLUDED_K,
                                        Q.EXCLUDED_L, Q.REFUSAL_ONLY}, row)
            if where is None:
                self.assertIn(disposition, (Q.REVIEW_ROW, Q.DERIVED), row)
        for row in ("1-F", "G-ID"):
            self.assertIn(Q.ADDENDUM_ROWS[row][0], (Q.REVIEW_ROW, Q.DERIVED))


class Guards(unittest.TestCase):
    def fired(self, record, kind="state"):
        return codes(evaluate(kind, record, record)[0], "REVIEW")

    def test_clean_differential_records_raise_nothing(self):
        clean = [("forcing", forcing()), ("heat", dict(heat(), projection_resource_policy=None)),
                 ("mesh", dict(schema=Q.MESH_SCHEMA, physical_geometry_family=Q.DIFFERENTIAL_FAMILY,
                               geometry_id=GEOMETRY, cells=[{"volume_m3": 1.0}])),
                 ("graph", dict(schema=Q.GRAPH_SCHEMA, physical_geometry_family=Q.DIFFERENTIAL_FAMILY,
                                inner=dict(schema=Q.GRAPH_SCHEMA))),
                 ("bounds", dict(schema=Q.ALE_BOUNDS_SCHEMA, physical_geometry_family=Q.DIFFERENTIAL_FAMILY,
                                 rows=[{"face_index": [0, 0], "volume_m3": q(1)}])),
                 ("state", dict(rays={"vertex:a": {"prior_rotations": []}}, rigid_motion=None,
                                constraint=dict(kind="snapshot-rotated", snapshot_offset_s=q(0)),
                                joined_heat_plan=dict(schema=Q.HEAT_PLAN_SCHEMA, boundary={"7": ["power", q(1)]})))]
        for kind, record in clean:
            items = evaluate(kind, record, record)[0]
            # This isolated heat fixture omits its independent mesh and captured input arrays.
            expected = ["ADDENDUM_5_4_GEOMETRY_UNBOUND"] * 2 if kind == "heat" else []
            self.assertEqual([i["code"] for i in items if i["verdict"] != "EXCLUDED"], expected, kind)

    def test_each_route_guard_fires(self):
        cases = [
            ({"inner": {"schema": Q.POSED_SUPPORT_SCHEMA}}, "ADDENDUM_1D_POSED_SUPPORT_RECORD"),
            ({"inner": [{"schema": Q.BOUNDARY_POSE_SCHEMA}]}, "ADDENDUM_G_EPOSE_BOUNDARY_POSE_RECORD"),
            ({"inner": {"schema": Q.FORCE_POSE_SCHEMA}}, "ADDENDUM_2_9_CURRENT_FORCE_RECORD"),
            ({"inner": {"schema": Q.FORCE_BACKGROUND_SCHEMA}}, "ADDENDUM_2_9_CURRENT_FORCE_RECORD"),
            ({"inner": {"schema": Q.SPATIAL_CORRECTION_SCHEMA}}, "ADDENDUM_2_9_CURRENT_FORCE_RECORD"),
            ({"inner": {"schema": Q.WALL_SCHEMA}}, "ADDENDUM_1B_3X_W_RECORD"),
            ({"wall_measure_id": None}, "ADDENDUM_1B_4_WALL_FIELD"),
            ({"inner": {"rigid_motion": {"angular_velocity_rad_s": [0, 0, 1]}}}, "ADDENDUM_1B_4_WALL_FIELD"),
            ({"driving": {"current_background": {}}}, "ADDENDUM_2_9_CURRENT_BACKGROUND"),
            ({"inner": {"exterior_cells": []}}, "ADDENDUM_3X_EXTERIOR_CELLS"),
            ({"offer": {"rows": [{"face_index": [0, 0], "inward_volume_m3": q(1)}]}}, "ADDENDUM_3X_EXTERIOR_ROWS"),
            ({"rows": {"f0": {"outward_volume_m3": q(1)}}}, "ADDENDUM_3X_EXTERIOR_ROWS"),
            ({"schema": Q.ALE_BOUNDS_SCHEMA}, "ADDENDUM_1B_4_BOUNDS_NOT_DIFFERENTIAL"),
            ({"inner": {"schema": Q.ALE_BOUNDS_SCHEMA, "physical_geometry_family": "complete-grid-v1"}},
             "ADDENDUM_1B_4_BOUNDS_NOT_DIFFERENTIAL"),
            ({"inner": {"schema": Q.MESH_SCHEMA, "representative_quaternion": [1, 0, 0, 0]}},
             "ADDENDUM_4_E_POSE_FIELD"),
            ({"schema": Q.GRAPH_SCHEMA}, "ADDENDUM_1B_GRAPH_NOT_DIFFERENTIAL"),
            ({"inner": {"schema": Q.GRAPH_SCHEMA, "physical_geometry_family": "w-family"}},
             "ADDENDUM_1B_GRAPH_NOT_DIFFERENTIAL"),
            ({"inner": {"schema": Q.DG_SCHEMA, "rays": {"vertex:a": {"prior_rotations": [[1, 0]]}}}},
             "ADDENDUM_1D_PRIOR_RAY_HISTORY"),
            ({"inner": {"schema": Q.DG_SCHEMA, "rays": [{"prior_rotations": [[1, 0]]}]}},
             "ADDENDUM_1D_PRIOR_RAY_HISTORY"),
            ({"c": {"kind": "snapshot-rotated", "snapshot_offset_s": q(Fraction(1, 2**40))}},
             "ADDENDUM_1D_SNAPSHOT_OFFSET_NOT_ZERO"),
            ({"c": {"kind": "snapshot-rotated", "snapshot_offset_s": "late"}}, "ADDENDUM_1D_SNAPSHOT_OFFSET_NOT_ZERO"),
            ({"joined_heat_plan": {"schema": Q.HEAT_PLAN_SCHEMA, "boundary": {"3": ["temperature", q(300)]}}},
             "ADDENDUM_5_7B_DIRICHLET_FACE"),
        ]
        for record, code in cases:
            self.assertIn(code, self.fired(record), record)
        self.assertIn("ADDENDUM_4_E_MESH_RECORD", self.fired({"schema": Q.MESH_SCHEMA}, "mesh"))
        # Nested compact copies without a family field, and E headers on another record kind, are not guards.
        self.assertEqual(self.fired({"inner": {"schema": Q.MESH_SCHEMA}}), [])
        self.assertEqual(self.fired({"inner": {"schema": Q.GRAPH_SCHEMA}}), [])
        self.assertEqual(self.fired({"inner": {"schema": Q.ALE_BOUNDS_SCHEMA}}), [])

    def test_one_item_per_guard_and_arm_with_its_count(self):
        dirty = {"a": {"schema": Q.WALL_SCHEMA}, "b": [{"schema": Q.WALL_SCHEMA}]}
        items = evaluate("state", dirty, {"clean": True})[0]
        walls = [item for item in items if item["code"] == "ADDENDUM_1B_3X_W_RECORD"]
        self.assertEqual([(w["arm"], w["found"], w["verdict"]) for w in walls], [("before", 2, "REVIEW")])
        shared = evaluate("state", dirty, dirty)[0]
        self.assertEqual([i["arm"] for i in shared if i["code"] == "ADDENDUM_1B_3X_W_RECORD"], ["both"])


class Forcing(unittest.TestCase):
    def test_2_4_positive_equal_records(self):
        self.assertEqual(evaluate("forcing", forcing(), forcing())[0], [])

    def test_2_4_entry_not_geometry_is_review_and_blocks_2_5(self):
        items = evaluate("forcing", forcing(), forcing(boundary_pose_ids=[GEOMETRY, "pose-2"]))[0]
        self.assertEqual(codes(items), ["ADDENDUM_2_4_POSE_ID_NOT_GEOMETRY", "ADDENDUM_2_5_PRECONDITION_2_4"])
        self.assertEqual(items[0]["arms"], ["after"])
        self.assertEqual(codes(evaluate("forcing", forcing(boundary_pose_ids=None), forcing())[0], "REVIEW")[0],
                         "ADDENDUM_2_4_POSE_ID_NOT_GEOMETRY")

    def test_2_4_geometry_differs_across_arms(self):
        other = "geometry-" + "b" * 64
        items = evaluate("forcing", forcing(), forcing(geometry_id=other, boundary_pose_ids=[other]))[0]
        self.assertEqual(codes(items), ["ADDENDUM_2_4_GEOMETRY_DIFFERS", "ADDENDUM_2_5_INPUTS_DIFFER"])

    def test_2_5_one_ulp_with_identical_inputs(self):
        after = forcing(cut_torques=[math.nextafter(1.0, 2.0), 2.0])
        self.assertEqual(codes(evaluate("forcing", forcing(), after)[0]), ["ADDENDUM_2_5_FORCING_DIFFERS"])

    def test_2_5_spatial_state_without_a_reader_proved_pair(self):
        after = forcing(spatial_state_id="spatial-2")
        self.assertEqual(codes(evaluate("forcing", forcing(), after)[0]), ["ADDENDUM_2_5_NO_SPATIAL_STATE_PAIR"])
        proved = evaluate("forcing", forcing(), after, ids={"spatial-1": "spatial-2"})[0]
        self.assertEqual(proved, [])
        moved = forcing(spatial_state_id="spatial-2", cut_torques=[1.0, 3.0])
        self.assertEqual(codes(evaluate("forcing", forcing(), moved, ids={"spatial-1": "spatial-2"})[0]),
                         ["ADDENDUM_2_5_FORCING_DIFFERS"])

    def test_2_5_inputs_are_type_strict(self):
        for changes in ({"radial_datum": 6371000}, {"physical_densities": [q(3300), q(1001)]},
                        {"request": {"duration_s": q(11)}}):
            self.assertEqual(codes(evaluate("forcing", forcing(), forcing(**changes))[0]),
                             ["ADDENDUM_2_5_INPUTS_DIFFER"], changes)
        self.assertEqual(codes(evaluate("forcing", forcing(radial_datum=5), forcing(radial_datum=5.0))[0]),
                         ["ADDENDUM_2_5_INPUTS_DIFFER"])
        self.assertEqual(codes(evaluate("forcing", forcing(cut_torques=[1, 2.0]), forcing())[0]),
                         ["ADDENDUM_2_5_FORCING_DIFFERS"])

    def test_forcing_rows_grant_no_pass_and_consume_nothing(self):
        for after in (forcing(), forcing(spatial_state_id="spatial-2"), forcing(cut_torques=[0.0, 0.0])):
            items, consumed, _ = evaluate("forcing", forcing(), after, ids={"spatial-1": "spatial-2"})
            self.assertEqual(consumed, set())
            self.assertTrue(all(item["verdict"] == "REVIEW" for item in items))


class Heat(unittest.TestCase):
    def test_partial_heat_records_cannot_exclude_differing_storage(self):
        after = heat(retained=[Fraction(1, 10**7), Fraction(-1, 10**7), Fraction(0)])
        items = evaluate("heat", heat(), after)[0]
        self.assertEqual([(i["verdict"], i["code"], i["arm"]) for i in items if i["row"] == "5.4"],
                         [("REVIEW", "ADDENDUM_5_4_GEOMETRY_UNBOUND", arm) for arm in ("before", "after")])
        self.assertNotEqual(heat()["exact_cell_storage_residual_j"], after["exact_cell_storage_residual_j"])

    def test_retained_above_target_by_2_pow_minus_200(self):
        target = Fraction(1, 10**6)
        record = heat(target=target, retained=[Fraction(0), -(target + Fraction(1, 2**200)), Fraction(0)])
        items = evaluate("heat", heat(), record)[0]
        self.assertEqual([(i["code"], i["arm"], i["cell_index"]) for i in items if i["verdict"] == "FAIL"],
                         [("ADDENDUM_5_4_RETAINED_ABOVE_TARGET", "after", 1)])
        edge = heat(target=target, retained=[Fraction(0), -target, target])
        self.assertEqual(codes(evaluate("heat", edge, edge)[0], "FAIL"), [])

    def test_storage_not_retained_plus_projection(self):
        record = heat()
        record["exact_cell_storage_residual_j"][2] = q(Fraction(1, 2**80))
        items = evaluate("heat", record, heat())[0]
        self.assertEqual([(i["code"], i["arm"], i["cell_index"]) for i in items if i["verdict"] == "FAIL"],
                         [("ADDENDUM_5_4_STORAGE_NOT_RETAINED_PLUS_PROJECTION", "before", 2)])

    def test_projection_is_the_producer_rounding_exactly(self):
        record, new = heat(), Fraction(1, 3)
        stored = math.nextafter(new.numerator / new.denominator, 1.0)       # a binary64 neighbour, not the rounding
        projection = Fraction(stored) - new
        record["exact_stock_projection_residual_j"][0] = q(projection)
        record["exact_cell_storage_residual_j"][0] = q(Fraction(1, 10**9) + projection)     # cell 0 retains 1e-9
        self.assertEqual(codes(evaluate("heat", record, record)[0], "FAIL"),
                         ["ADDENDUM_5_4_PROJECTION_NOT_ROUNDING"] * 2)
        tiny = heat(cells=1)
        tiny["exact_corrected_enthalpy_j"] = [q(Fraction(3, 2**1076))]                 # rounds into the subnormals
        p = Fraction((3 / 2**1076)) - Fraction(3, 2**1076)
        tiny["exact_stock_projection_residual_j"] = [q(p)]
        tiny["exact_cell_storage_residual_j"] = [q(Fraction(1, 10**9) + p)]
        self.assertEqual(codes(evaluate("heat", tiny, tiny)[0], "FAIL"), [])
        self.assertNotEqual(p, 0)

    def test_other_layouts_are_review(self):
        for changes in ({"exact_corrected_enthalpy_j": ["0x1", "0x3"]},
                        {"exact_retained_solver_residual_j": {"ledger": "rows-1", "count": 3}},
                        {"exact_stock_projection_residual_j": [q(0), q(0)]},
                        {"exact_corrected_enthalpy_j": [[1, 3]] * 3},
                        dict.fromkeys(Q.RESIDUALS_54, ["0x1", "0x3"]),        # scalar pairs are not two cells
                        {"independently_supplied_absolute_residual_target": "0x1"}):
            items = evaluate("heat", heat(**changes), heat())[0]
            self.assertEqual([(i["verdict"], i["code"], i.get("arm")) for i in items if i.get("row") != "5.12"],
                             [("REVIEW", "ADDENDUM_5_4_LAYOUT_NOT_DECODED", "before"),
                              ("REVIEW", "ADDENDUM_5_4_GEOMETRY_UNBOUND", "after")], changes)

    def test_an_undecodable_pair_is_a_layout_review(self):
        items, consumed, _ = evaluate("heat", heat(independently_supplied_absolute_residual_target=["0x1", "0x0"]),
                                      heat())
        self.assertEqual(codes(items), ["ADDENDUM_ROW_LAYOUT_UNRECOGNISED"])
        self.assertEqual(consumed, set())

    def test_5_12_resource_policy_is_excluded_only_when_encoded_alike(self):
        after = heat(projection_resource_policy={"workers": 4, "peak_bytes": 4096})
        items, consumed, _ = evaluate("heat", heat(), after)
        self.assertEqual([i["verdict"] for i in items if i["row"] == "5.12"], ["EXCLUDED"])
        self.assertEqual(consumed, {("heat", "projection_resource_policy")})
        retyped = heat(projection_resource_policy={"workers": 2.0, "peak_bytes": 1024})
        items, consumed, _ = evaluate("heat", heat(), retyped)
        self.assertEqual([(i["verdict"], i["code"], i["excluded"]) for i in items if i["row"] == "5.12"],
                         [("REVIEW", "ADDENDUM_EXCLUSION_NOT_APPLIED", "ADDENDUM_5_12_EXCLUDED")])
        self.assertEqual(consumed, set())


class WorkUnits(unittest.TestCase):
    def support(self, work_units):
        return dict(schema=Q.SUPPORT_SCHEMA, support_id="support-1", work_units=work_units)

    def test_excluded_while_refusal_parity_holds(self):
        items, consumed, rows = evaluate("support", self.support(5), self.support(7), parity=True)
        self.assertEqual([(i["verdict"], i["code"]) for i in items], [("EXCLUDED", "ADDENDUM_G_WU_EXCLUDED")])
        self.assertEqual(consumed, {("support", "work_units")})
        summary = rows.summary()
        self.assertEqual(summary["support_work_units_record_only"], {"before": 5, "after": 7})
        self.assertTrue(summary["refusal_parity"])

    def test_no_exclusion_without_refusal_parity(self):
        items, consumed, rows = evaluate("support", self.support(5), self.support(7), parity=False)
        self.assertEqual((items, consumed), ([], set()))
        self.assertEqual(rows.summary()["support_work_units_record_only"], {"before": 5, "after": 7})

    def test_nested_supports_and_type_changes(self):
        before = {"supports": [self.support(5), self.support(1)]}
        after = {"supports": [self.support(9), self.support(1.0)]}
        items, consumed, rows = evaluate("mesh", before, after, parity=True)
        self.assertEqual(consumed, {("mesh", "supports", "0", "work_units")})
        self.assertEqual([i["path"] for i in items if i["verdict"] == "EXCLUDED"],
                         [["mesh", "supports", "0", "work_units"]])
        self.assertEqual(rows.summary()["support_work_units_record_only"], {"before": 6, "after": 9})


class Identities(unittest.TestCase):
    def dg(self, interval_id):
        return dict(schema=Q.DG_SCHEMA, interval_id=interval_id, rays={})

    def test_unchanged_interval_id_on_the_width_arm(self):
        self.assertEqual(codes(evaluate("differential", self.dg("i-1"), self.dg("i-1"))[0]),
                         ["ADDENDUM_G_ID_INTERVAL_UNCHANGED"])
        self.assertEqual(evaluate("differential", self.dg("i-1"), self.dg("i-1"), interval=0)[0], [])
        self.assertEqual(evaluate("differential", self.dg("i-1"), self.dg("i-2"))[0], [])

    def test_undumped_source_identities_are_review(self):
        before = {"partition_id": "p-1", "rows": [{"partition_id": "p-1"}, {"heat_id": "h-1"}]}
        after = {"partition_id": "p-2", "rows": [{"partition_id": "p-3"}, {"heat_id": "h-1"}]}
        items = evaluate("support", before, after)[0]
        self.assertEqual([(i["code"], i["key"], i["found"]) for i in items],
                         [("ADDENDUM_G_ID_SOURCE_NOT_DUMPED", "partition_id", 2)])
        self.assertEqual(evaluate("support", before, after, ids={"p-1": "p-2"})[0][0]["found"], 1)
        self.assertEqual(evaluate("support", before, before)[0], [])

    def test_4_9_mesh_geometry_id_is_review_by_derivation(self):
        mesh = dict(schema=Q.MESH_SCHEMA, physical_geometry_family=Q.DIFFERENTIAL_FAMILY, geometry_id="g-1")
        moved = dict(mesh, geometry_id="g-2")
        items = evaluate("mesh", mesh, moved, ids={"g-1": "g-2"})[0]
        self.assertEqual([(i["verdict"], i["code"], i["row"]) for i in items],
                         [("REVIEW", "ADDENDUM_4_9_DERIVED_FROM_REVIEW_CONTENT", "4.9,G-ID")])
        self.assertEqual(evaluate("state", {"m": mesh}, {"m": moved})[0], [])
        self.assertEqual(evaluate("mesh", mesh, copy.deepcopy(mesh))[0], [])


class InitialCascade(unittest.TestCase):
    def test_header_and_record_level_ids_are_inside(self):
        names = ["mesh." + Q.DEVIATION, "mesh.geometry_id", "state.thermal_mesh_id", "state.owner.state_id",
                 "workflow.root_key", "mesh.initial_mesh_id", "state.workflow_id"]
        self.assertEqual(Q.i0_outside("mesh", [n for n in names if n.startswith("mesh")]), [])
        self.assertEqual(Q.i0_outside("state", [n for n in names if n.startswith("state")]), [])

    def test_elements_other_fields_and_other_headers_are_outside(self):
        names = ["mesh.cells.[].geometry_id", "mesh.cells.[].volume_m3", "mesh.time_s", "state." + Q.DEVIATION]
        self.assertEqual(Q.i0_outside("mesh", names[:3]), sorted(names[:3]))
        self.assertEqual(Q.i0_outside("state", names[3:]), names[3:])


class Summary(unittest.TestCase):
    def test_counts_by_row_and_verdict(self):
        rows = Q.AddendumRows(1, parity=True)
        rows.evaluate("forcing", forcing(), forcing(spatial_state_id="spatial-2"))
        rows.evaluate("heat", heat(), heat(projection_resource_policy={"workers": 3, "peak_bytes": 1}))
        self.assertEqual(rows.summary()["results"], {"2.5:REVIEW": 1, "5.12:EXCLUDED": 1, "5.4:REVIEW": 2})
        self.assertEqual(rows.summary()["addendum"], Q.CONTRACT_ADDENDUM)


if __name__ == "__main__":
    unittest.main()
