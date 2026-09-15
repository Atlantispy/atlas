"""Small analytical, failure, continuation and exact-source tests; no world run.

Run: python -B -m work.generator_upgrade_r1.test_landscape --receipt PATH
Repeat with -OO. The tested landscape module is compiled from captured raw bytes,
not accepted from a pre-existing Python module alias or bytecode cache.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from fractions import Fraction as F
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import py_compile
import sys
import tempfile
import time
import types
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
LANDSCAPE_RAW = (HERE / "landscape.py").read_bytes()
ls = types.ModuleType("_tested_generator_upgrade_landscape")
ls.__file__ = str(HERE / "landscape.py")
sys.modules[ls.__name__] = ls
exec(compile(LANDSCAPE_RAW, ls.__file__, "exec", dont_inherit=True,
             optimize=sys.flags.optimize), ls.__dict__)
EXECUTED_LANDSCAPE_SHA256 = hashlib.sha256(LANDSCAPE_RAW).hexdigest()


def prop(name, value, unit, status="SYNTHETIC TEST"):
    return ls.PhysicalProperty(name, value, unit, "explicit analytical fixture", status)


def forcing(q=4, slope=.5, status="SYNTHETIC TEST"):
    return ls.Forcing(prop("discharge", q, "m3/year", status), prop("hydraulic_slope", slope, "1", status))


def law(identity="rock", phase="bedrock", k=1, reference=1, status="SYNTHETIC TEST"):
    return ls.ErosionLaw(identity, phase, prop("erosion_coefficient_at_reference_runoff", k, "1/year", status),
                         prop("reference_runoff", reference, "m/year", status))


def layer(identity="rock", mass=100, density=10, porosity=0, phase="bedrock"):
    return ls.Layer(identity, F(mass), F(density), F(porosity), phase, "analytical finite stock")


def state(layers=None, area=1, base=0, status="SYNTHETIC TEST"):
    if layers is None:
        layers = (layer(),)
    return ls.LandscapeState((("a", ls.Column(F(area), F(base), tuple(layers), status)),))


def deposit(identity="sand", mass=10, time=0, sequence=0, event="deposit-1", column="a", porosity=F(1, 2), density=10):
    return ls.Deposition(event, column, F(time), sequence,
                         layer(identity, mass, density, porosity, "mobile_sediment"), "SYNTHETIC TEST")


def run(source=None, years=1, laws=None, events=(), force=None):
    source = state() if source is None else source
    return ls.advance(source, {key: forcing() if force is None else force for key, _ in source.columns},
                      (law(),) if laws is None else laws, years, events)


class AnalyticalEvolution(unittest.TestCase):
    def test_homogeneous_mass_depth_and_time_oracle(self):
        # I=sqrt(4/1)*.5=1m; E=.5m/y. A=2, rho=10,p=.5:
        # removal over3y=.5*3*2*10*.5=15kg, lowering1.5m.
        initial = state((layer(porosity=F(1, 2)),), area=2)
        result = run(initial, 3, (law(k=F(1, 2)),))
        self.assertEqual(result.state.column_map["a"].mass_kg, 85)
        self.assertEqual(initial.column_map["a"].surface_m-result.state.column_map["a"].surface_m, F(3, 2))
        self.assertEqual(result.eroded_parcels[0].source_layer.mass_kg, 15)
        self.assertEqual(result.receipt["columns"][0]["erosion_active_years"], [3, 1])

    def test_contact_changes_coefficient_during_same_step(self):
        # Top2m erodes at2m/y for1y, then bottom3m at.5m/y for2y.
        initial = state((layer("rock", 60), layer("sand", 8, 4, F(1, 2), "mobile_sediment")), area=2)
        result = run(initial, 3, (law(k=F(1, 2)), law("sand", "mobile_sediment", 2)))
        self.assertEqual(result.state.column_map["a"].mass_kg, 40)
        self.assertEqual(result.state.column_map["a"].surface_m, 2)
        self.assertEqual([p.source_layer.material_id for p in result.eroded_parcels], ["sand", "rock"])
        self.assertEqual([p.source_layer.mass_kg for p in result.eroded_parcels], [8, 20])
        self.assertEqual([(p.start_year, p.end_year) for p in result.eroded_parcels], [(0, 1), (1, 3)])

    def test_contact_exactly_at_step_end_exposes_without_extra_erosion(self):
        initial = state((layer(), layer("sand", 10, 10, 0, "mobile_sediment")))
        result = run(initial, 1, (law(k=7), law("sand", "mobile_sediment", 1)))
        self.assertEqual(result.state.column_map["a"].layers, (layer(),))
        self.assertEqual(len(result.eroded_parcels), 1)

    def test_resistant_layer_blocks_remaining_interval(self):
        initial = state((layer(), layer("sand", 10, 10, 0, "mobile_sediment")))
        result = run(initial, 3, (law(k=0), law("sand", "mobile_sediment", 1)))
        self.assertEqual(result.state.column_map["a"].mass_kg, 100)
        self.assertEqual(result.receipt["columns"][0]["zero_rate_years"], [2, 1])

    def test_finite_stock_never_erodes_basal_floor(self):
        result = run(state(base=-100), 30)
        self.assertEqual(result.state.column_map["a"].surface_m, -100)
        self.assertEqual(result.state.column_map["a"].layers, ())
        self.assertEqual(sum(p.source_layer.mass_kg for p in result.eroded_parcels), 100)
        self.assertEqual(result.receipt["columns"][0]["stock_exhausted_years"], [20, 1])

    def test_all_zero_drivers_preserve_stock(self):
        for water, slope, coefficient in ((0, .5, 1), (4, 0, 1), (4, .5, 0)):
            with self.subTest(water=water, slope=slope, coefficient=coefficient):
                result = run(years=10, laws=(law(k=coefficient),), force=forcing(water, slope))
                self.assertEqual(result.state.column_map["a"].mass_kg, 100)
                self.assertEqual(result.eroded_parcels, ())
                self.assertEqual(result.receipt["columns"][0]["zero_rate_years"], [10, 1])

    def test_zero_duration_without_pulses_is_identity(self):
        initial = state()
        self.assertEqual(run(initial, 0).state, initial)

    def test_runoff_response_and_explicit_calibration_reference(self):
        low = run(years=F(1, 10000), force=forcing(4))
        high = run(years=F(1, 10000), force=forcing(4_000_000))
        # Scaled binary64 square root may differ by one ulp even for this square;
        # exact bookkeeping must not be misrepresented as exact physical sqrt.
        ratio = float(high.eroded_parcels[0].source_layer.mass_kg / low.eroded_parcels[0].source_layer.mass_kg)
        self.assertLessEqual(abs(ratio-1000), 2*math.ulp(1000.0))
        reference = run(years=F(1, 10000), laws=(law(reference=4),))
        self.assertEqual(low.eroded_parcels[0].source_layer.mass_kg / reference.eroded_parcels[0].source_layer.mass_kg, 2)

    def test_irrational_intensity_honestly_uses_represented_value(self):
        result = run(years=F(1, 10), force=forcing(2, 1))
        self.assertAlmostEqual(float(result.eroded_parcels[0].source_layer.mass_kg), math.sqrt(2), places=14)
        self.assertIn("represented binary64", result.receipt["contact_solver"])
        self.assertNotIn("CERTIFIED", result.receipt["status"])

    def test_many_layer_analytical_contact_sum(self):
        # Every layer1m. Rates bottom-to-top1..20m/y. Exact exhaustion time
        # equals the independent sum1/k, with exactly200kg exported.
        layers = tuple(layer("r"+str(i), 10) for i in range(1, 21))
        laws = tuple(law("r"+str(i), k=i) for i in range(1, 21))
        duration = sum((F(1, i) for i in range(1, 21)), F())
        result = run(state(layers), duration, laws)
        self.assertEqual(result.state.column_map["a"].layers, ())
        self.assertEqual(len(result.eroded_parcels), 20)
        self.assertEqual(result.eroded_parcels[-1].end_year, duration)
        self.assertEqual(sum(p.source_layer.mass_kg for p in result.eroded_parcels), 200)

    def test_deposition_buries_then_reexposes_with_correct_time(self):
        result = run(years=2, laws=(law(), law("sand", "mobile_sediment", 2)), events=(deposit(time=F(1, 2)),))
        self.assertEqual(result.state.column_map["a"].mass_kg, 90)
        self.assertEqual([p.source_layer.material_id for p in result.eroded_parcels], ["rock", "sand", "rock"])
        self.assertEqual([(p.start_year, p.end_year) for p in result.eroded_parcels],
                         [(0, F(1, 2)), (F(1, 2), F(3, 2)), (F(3, 2), 2)])
        self.assertEqual(result.state.applied_deposition_ids, ("deposit-1",))

    def test_deposition_can_armour_surface(self):
        result = run(years=20, laws=(law(), law("sand", "mobile_sediment", 0)), events=(deposit(time=F(1, 2)),))
        self.assertEqual(result.state.column_map["a"].mass_kg, 105)
        self.assertEqual(result.state.column_map["a"].surface_m, F(23, 2))
        self.assertEqual(result.state.column_map["a"].exposed.material_id, "sand")

    def test_end_time_deposit_has_no_earlier_erosion(self):
        result = run(years=1, laws=(law(), law("sand", "mobile_sediment", 100)), events=(deposit(time=1),))
        self.assertEqual(result.state.column_map["a"].mass_kg, 100)
        self.assertEqual(result.state.column_map["a"].exposed.mass_kg, 10)
        self.assertEqual(len(result.eroded_parcels), 1)

    def test_empty_column_can_receive_and_lose_finite_new_stock(self):
        result = run(state(()), 3, (law("sand", "mobile_sediment", 2),), (deposit(time=1),))
        self.assertEqual(result.state.column_map["a"].layers, ())
        self.assertEqual(result.eroded_parcels[0].source_layer.mass_kg, 10)
        self.assertEqual(result.receipt["columns"][0]["stock_exhausted_years"], [2, 1])

    def test_equal_time_explicit_sequence_sets_physical_layer_order(self):
        events = (deposit("sand", sequence=2, event="late"), deposit("silt", sequence=1, event="early"))
        laws = (law(), law("sand", "mobile_sediment"), law("silt", "mobile_sediment"))
        a = run(years=0, laws=laws, events=events)
        b = run(years=0, laws=laws, events=tuple(reversed(events)))
        self.assertEqual(a.state, b.state)
        self.assertEqual([x.material_id for x in a.state.column_map["a"].layers], ["rock", "silt", "sand"])

    def test_piecewise_semigroup_and_checkpoint_restart(self):
        initial = state((layer(), layer("sand", 10, 10, F(1, 2), "mobile_sediment")))
        laws = (law(k=F(1, 3)), law("sand", "mobile_sediment", 2))
        pulse = deposit(time=F(7, 4))
        whole = run(initial, 4, laws, (pulse,))
        a = run(initial, F(7, 4), laws, (pulse,))
        recovered = ls.LandscapeState.from_json(json.dumps(a.state.as_dict()))
        b = run(recovered, F(9, 4), laws)
        self.assertEqual(whole.state, b.state)
        self.assertEqual(sum(p.source_layer.mass_kg for p in whole.eroded_parcels),
                         sum(p.source_layer.mass_kg for p in a.eroded_parcels + b.eroded_parcels))

    def test_four_substeps_equal_one_for_fixed_forcing(self):
        initial = state((layer(), layer("sand", 15, 3, F(1, 3), "mobile_sediment")))
        laws = (law(), law("sand", "mobile_sediment", 5))
        whole = run(initial, 2, laws)
        current = initial
        for _ in range(4):
            current = run(current, F(1, 2), laws).state
        self.assertEqual(current, whole.state)

    def test_two_columns_conserve_each_material_exactly(self):
        source = ls.LandscapeState((('a', state().column_map['a']),
                                    ('b', ls.Column(F(2), F(-3), (layer("sand", 21, 3, F(1, 3), "mobile_sediment"),), "SYNTHETIC TEST"))))
        result = ls.advance(source, {"a": forcing(4), "b": forcing(9)},
                            (law(), law("sand", "mobile_sediment", F(2, 3))), F(1, 2))
        for row in result.receipt["global_material_balance"]:
            self.assertEqual(row["residual_mass_kg"], [0, 1])
            self.assertEqual(row["residual_solid_volume_m3"], [0, 1])
        self.assertEqual(sum(c.mass_kg for _, c in source.columns),
                         sum(c.mass_kg for _, c in result.state.columns) + sum(p.source_layer.mass_kg for p in result.eroded_parcels))

    def test_redeposition_retains_mass_identity_density_changes_only_explicit_packing(self):
        eroded = run(years=1).eroded_parcels[0]
        event = ls.redeposit(eroded, event_id="return", column_id="a", at_year=1, sequence=0,
                             sediment_porosity=prop("deposited_sediment_porosity", F(1, 2), "1"), source_status="SYNTHETIC TEST")
        self.assertEqual(event.layer.mass_kg, eroded.source_layer.mass_kg)
        self.assertEqual(event.layer.grain_density_kg_m3, eroded.source_layer.grain_density_kg_m3)
        self.assertEqual(event.layer.material_id, "rock")
        self.assertEqual(event.layer.phase, "mobile_sediment")
        self.assertEqual(event.layer.bulk_volume_m3, 2 * eroded.source_layer.bulk_volume_m3)
        first = run(years=1)
        result = run(first.state, 0, (law(), law("rock", "mobile_sediment", 2)), (event,))
        self.assertEqual(result.state.column_map["a"].mass_kg, 100)
        # Solid volume is conserved; changing porosity increases bulk height.
        self.assertEqual(result.state.column_map["a"].surface_m, 11)
        reexposed = run(result.state, 1, (law(), law("rock", "mobile_sediment", 2)))
        self.assertEqual(reexposed.state.column_map["a"].exposed.phase, "bedrock")

    def test_outputs_never_promote_canon(self):
        result = run(state(status="CANON"), laws=(law(status="CANON"),), force=forcing(status="CANON"))
        self.assertEqual(result.state.column_map["a"].source_status, "WORKING NON-CANON")

    def test_parent_reference_is_deterministic_json_safe_and_actually_checked(self):
        first = ls.verification_reference()
        second = ls.verification_reference()
        self.assertEqual(first, second)
        self.assertEqual(first["independent_oracle"]["final_mass_kg"], [90, 1])
        self.assertTrue(first["restart_identical"])
        self.assertTrue(first["replay_rejected"])
        json.dumps(first, allow_nan=False)


class FailureAndBinding(unittest.TestCase):
    def test_wrong_units_unresolved_nonfinite_and_scores_rejected(self):
        for bad in (prop("discharge", 3, "ordinal"), prop("discharge", None, "m3/year", "UNKNOWN"),
                    prop("discharge", math.nan, "m3/year"), prop("discharge", True, "m3/year"),
                    prop("discharge", F(1, 3), "m3/year"), prop("discharge", -1, "m3/year")):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    ls.Forcing(bad, prop("hydraulic_slope", 1, "1"))

    def test_nonpositive_reference_and_unknown_erodibility_rejected(self):
        for ref in (0, -1, math.inf, True):
            with self.subTest(reference=ref), self.assertRaises(ValueError):
                law(reference=ref)
        with self.assertRaises(ValueError):
            ls.ErosionLaw("rock", "bedrock", prop("erosion_coefficient_at_reference_runoff", None, "1/year", "INCOMPLETE"),
                          prop("reference_runoff", 1, "m/year"))

    def test_missing_buried_deposited_duplicate_and_phase_laws_rejected(self):
        initial = state((layer(), layer("sand", 10, phase="mobile_sediment")))
        for laws, events in (((law("sand", "mobile_sediment"),), ()),
                            ((law(), law()), ()), ((law(),), (deposit(),)),
                            ((law(), law("sand", "bedrock")), ())):
            with self.subTest(laws=laws), self.assertRaises(ValueError):
                run(initial, laws=laws, events=events)

    def test_conflicting_density_identity_rejected(self):
        initial = state((layer(), layer("rock", density=20)))
        with self.assertRaisesRegex(ValueError, "conflicting grain densities"):
            run(initial)

    def test_each_column_requires_exact_forcing_inventory(self):
        for forces in ({}, {"a": forcing(), "b": forcing()}, {"a": {"Q": 1}}):
            with self.subTest(forces=forces), self.assertRaises(ValueError):
                ls.advance(state(), forces, (law(),), 1)

    def test_event_replay_rejected_after_restart(self):
        laws = (law(), law("sand", "mobile_sediment"))
        pulse = deposit(time=1)
        result = run(years=1, laws=laws, events=(pulse,))
        loaded = ls.LandscapeState.from_json(json.dumps(result.state.as_dict()))
        with self.assertRaisesRegex(ValueError, "replay"):
            run(loaded, 1, laws, (pulse,))

    def test_duplicate_or_ambiguous_deposition_rejected(self):
        pulse = deposit()
        for events in ((pulse, pulse), (pulse, replace(pulse, event_id="different"))):
            with self.subTest(events=events), self.assertRaises(ValueError):
                run(laws=(law(), law("sand", "mobile_sediment")), events=events)

    def test_outside_interval_and_unknown_destination_rejected_atomically(self):
        initial = state()
        before = initial.as_dict()
        for event in (deposit(time=2), deposit(column="missing")):
            with self.subTest(event=event), self.assertRaises(ValueError):
                run(initial, events=(event,), laws=(law(), law("sand", "mobile_sediment")))
            self.assertEqual(initial.as_dict(), before)
        advanced = run(initial).state
        with self.assertRaises(ValueError):
            run(advanced, events=(deposit(time=0),), laws=(law(), law("sand", "mobile_sediment")))

    def test_negative_boolean_nonfinite_durations_and_sequences_rejected(self):
        for duration in (-1, True, math.nan, math.inf):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                run(years=duration)
        for sequence in (-1, True, .5):
            with self.subTest(sequence=sequence), self.assertRaises(ValueError):
                deposit(sequence=sequence)

    def test_deposition_has_no_implicit_bedrock_or_unknown_source(self):
        with self.assertRaises(ValueError):
            ls.Deposition("x", "a", 0, 0, layer(), "SYNTHETIC TEST")
        with self.assertRaises(ValueError):
            replace(deposit(), source_status="UNKNOWN")

    def test_redeposition_rejects_arrival_before_whole_parcel_exists(self):
        parcel = run(years=1).eroded_parcels[0]
        with self.assertRaises(ValueError):
            ls.redeposit(parcel, event_id="x", column_id="a", at_year=F(1, 2), sequence=0,
                         sediment_porosity=prop("deposited_sediment_porosity", .5, "1"), source_status="SYNTHETIC TEST")

    def test_direct_eroded_parcel_requires_real_positive_time_interval(self):
        for start, end in ((10, 1), (1, 1), (-1, 1), (0, math.nan), (0, math.inf),
                           (True, 2), (0, 1 << (ls.MAX_EXACT_BITS+1))):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                ls.ErodedParcel("a", start, end, layer())

    def test_direct_eroded_parcel_requires_identity_and_actual_material(self):
        with self.assertRaises(ValueError):
            ls.ErodedParcel("  ", 0, 1, layer())
        with self.assertRaises(ValueError):
            ls.ErodedParcel("a", 0, 1, {"mass_kg": 10})

    def test_redeposition_requires_physical_porosity_below_one(self):
        for porosity in (1, -1, math.nan):
            with self.subTest(porosity=porosity), self.assertRaises(ValueError):
                ls.redeposit(run().eroded_parcels[0], event_id="x", column_id="a", at_year=1, sequence=0,
                             sediment_porosity=prop("deposited_sediment_porosity", porosity, "1"), source_status="SYNTHETIC TEST")

    def test_duplicate_columns_and_invalid_history_rejected(self):
        with self.assertRaises(ValueError):
            ls.LandscapeState((state().columns[0], state().columns[0]))
        with self.assertRaises(ValueError):
            ls.LandscapeState(state().columns, applied_deposition_ids=("x", "x"))

    def test_state_roundtrip_preserves_negative_base_fractions_and_layer_evidence(self):
        initial = state((layer("rock", F(2, 3), F(7, 3), F(2, 5)),), F(7, 9), F(-11, 17))
        self.assertEqual(ls.LandscapeState.from_json(json.dumps(initial.as_dict())), initial)

    def test_strict_checkpoint_json_and_source_pins(self):
        text = json.dumps(state().as_dict())
        with self.assertRaises(ValueError):
            ls.LandscapeState.from_json(text.replace('"schema":', '"schema": "duplicate", "schema":', 1))
        with self.assertRaises(ValueError):
            ls.LandscapeState.from_json(text.replace('"elapsed_years": [0, 1]', '"elapsed_years": NaN'))
        changed = state().as_dict()
        changed["foundation_sources"]["materials.py"] = "0" * 64
        with self.assertRaises(ValueError):
            ls.LandscapeState.from_dict(changed)
        changed = state().as_dict()
        changed["extra"] = 1
        with self.assertRaises(ValueError):
            ls.LandscapeState.from_dict(changed)

    def test_resource_refusal_returns_no_mutation(self):
        initial = state()
        before = initial.as_dict()
        with mock.patch.object(ls, "MAX_EVENT_HISTORY", 0), self.assertRaises(ValueError):
            run(initial, events=(deposit(),), laws=(law(), law("sand", "mobile_sediment")))
        with mock.patch.object(ls, "MAX_EXACT_BITS", 2), self.assertRaises(ValueError):
            run(initial, years=100)
        with mock.patch.object(ls, "MAX_TOTAL_LAYERS", 1), self.assertRaises(ValueError):
            run(initial, events=(deposit(),), laws=(law(), law("sand", "mobile_sediment")))
        self.assertEqual(initial.as_dict(), before)

    def test_foundation_runtime_is_the_actual_bound_source_and_stays_unchanged(self):
        before = {name: hashlib.sha256((ls.FOUNDATION / name).read_bytes()).hexdigest() for name in ls.FOUNDATION_PINS}
        self.assertEqual(before, ls.FOUNDATION_PINS)
        self.assertEqual(Path(ls.Column.strip_mass.__code__.co_filename).resolve(), (ls.FOUNDATION / "materials.py").resolve())
        self.assertEqual(Path(ls._erosion.runoff_normalised_intensity.__code__.co_filename).resolve(), (ls.FOUNDATION / "erosion.py").resolve())
        result = run()
        self.assertEqual(result.receipt["foundation_executed_sources"], before)
        self.assertEqual(before, {name: hashlib.sha256((ls.FOUNDATION / name).read_bytes()).hexdigest() for name in before})
        json.dumps(result.receipt, allow_nan=False)

    def test_fresh_compilation_ignores_real_timestamp_valid_stale_bytecode(self):
        with tempfile.TemporaryDirectory(prefix="landscape-source-binding-") as folder:
            path = Path(folder) / "fixture.py"
            path.write_text("VALUE = 'old'\n", encoding="utf-8")
            py_compile.compile(str(path), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
            timestamp = path.stat().st_mtime_ns
            path.write_text("VALUE = 'new'\n", encoding="utf-8")
            os.utime(path, ns=(timestamp, timestamp))
            spec = importlib.util.spec_from_file_location("stale_landscape_fixture", path)
            ordinary = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ordinary)
            self.assertEqual(ordinary.VALUE, "old")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(ls._load_pinned(path, digest).VALUE, "new")
            with self.assertRaises(ValueError):
                ls._load_pinned(path, "0" * 64)

    def test_drift_refusal_without_touching_predecessors(self):
        with mock.patch.object(ls, "FOUNDATION_PINS", {**ls.FOUNDATION_PINS, "erosion.py": "0"*64}):
            with self.assertRaisesRegex(ValueError, "source drift"):
                run()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    paths = [HERE / "landscape.py", HERE / "test_landscape.py", HERE / "LANDSCAPE_DESIGN.md"]
    paths.extend(ls.FOUNDATION / name for name in ls.FOUNDATION_PINS)
    paths.append(HERE.parent / "terrain_model_r7" / "hillslope_kernel.py")
    before = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    ids = []
    def collect(node):
        if isinstance(node, unittest.TestSuite):
            for child in node:
                collect(child)
        else:
            ids.append(node.id())
    collect(suite)
    start = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    elapsed = time.perf_counter()-start
    after = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in before}
    receipt = {"schema": "generator-upgrade-landscape-verification.r1", "tests_run": result.testsRun,
               "failures": [(test.id(), message) for test, message in result.failures],
               "errors": [(test.id(), message) for test, message in result.errors],
               "skipped": [(test.id(), message) for test, message in result.skipped],
               "elapsed_seconds": elapsed, "python_optimize": sys.flags.optimize, "test_ids": ids,
               "executed_landscape_sha256": EXECUTED_LANDSCAPE_SHA256,
               "sources_before": before, "sources_after": after, "source_preservation_pass": before == after,
               "status": "PASS" if result.wasSuccessful() and before == after else "FAIL"}
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
