"""Bounded fresh-process verification and exclusive local evidence recording."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXPECTED = {
 "ColumnTests": "bad_layers_reject burial_and_reexposure_keep_identity erosion_through_contact_is_persistent finite_stock_no_invented_underlying_rock independent_bulk_height_oracle json_recovery_preserves_exact_column ordinal_affinity_cannot_be_permeability sequential_removal_matches_one_total unknown_property_not_zero",
 "ConnectivityTests": "actual_hs17_component_uses_path_connectivity actual_hs17_opens_only_at_usable_pass anisotropic_cell_support barrier_blocks_nearby_endpoints barrier_unreachable_result_matches_independent_flood_fill diagonal_cannot_cut_blocked_corner gap_limit_is_enforced_along_path inherited_gap_is_explicitly_radius_not_segment_length missing_subpredictor_cannot_turn_into_positive_support missing_threshold_is_not_empty_habitat no_endpoint_is_infinite_not_fabricated_nearby non_boolean_masks_and_misaligned_arrays_reject pass_allows_real_detour predecessor_drift_rejects",
 "DischargeTests": "confluence_and_conservative_deposition erosion_rotation_consistency intensity_avoids_intermediate_ratio_overflow intensity_extreme_range_matches_decimal_oracle million_fold_runoff_reduces_incision_thousand_fold no_arbitrary_or_bad_reference predecessor_bytes_unchanged reference_runoff_controls_coefficient_meaning spatial_runoff_is_not_replaced_by_global_mean temporal_refinement_against_independent_exponential uniform_reference_reproduces_area_reference untrusted_core_alias_is_not_executed zero_runoff_zero_erosion",
 "FoodTests": "energy_equivalent_overflow_cannot_escape_as_infinity exact_independent_mass_and_energy_example land_changes_independent_supply land_overallocation_and_duplicates_reject population_cannot_create_supply unknown_yield_remains_unknown water_deficit_does_not_invent_drought_yield",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    return {p.name: {"bytes": p.stat().st_size, "sha256": sha(p)} for p in sorted(HERE.iterdir()) if p.suffix in {".py", ".md", ".json"}}


def predecessors():
    from . import erosion, connectivity
    rows = {}
    for path, expected in ((erosion.CORE_PATH, erosion.CORE_SHA256),
                           (connectivity.HS17_PATH, connectivity.HS17_SHA256),
                           (connectivity.FRAMEWORK_PATH, connectivity.FRAMEWORK_SHA256)):
        actual = sha(path)
        if actual != expected:
            raise ValueError("predecessor mismatch: " + str(path))
        rows[str(path)] = actual
    return rows


def ids(suite):
    for case in suite:
        if isinstance(case, unittest.TestSuite):
            yield from ids(case)
        else:
            yield case.id()


def diagnostics():
    from .test_foundation import DischargeTests, ConnectivityTests, FoodTests
    first = DischargeTests(); first.setUp()
    _, wet = first.step((1.,)*4); _, dry = first.step((1e-6,)*4)
    from . import connectivity
    second = ConnectivityTests()
    inputs = second.predictors()
    free = connectivity.corrected_hs17_movement(inputs, dx_m=1000, dy_m=1000)
    inputs["land"][:,2] = False
    blocked = connectivity.corrected_hs17_movement(inputs, dx_m=1000, dy_m=1000)
    third = FoodTests(); third.setUp()
    food_one = third.budget(population=1); food_many = third.budget(population=10000)
    return {"synthetic_only": True, "runoff_reduction_factor": 1_000_000,
            "wet_rock_debit_solid_m3": wet["rate_rock_loss_solid_m3"],
            "dry_rock_debit_solid_m3": dry["rate_rock_loss_solid_m3"],
            "incision_reduction_factor": wet["rate_rock_loss_solid_m3"]/dry["rate_rock_loss_solid_m3"],
            "unobstructed_supported_cells": int((free["movement_support"] > 0).sum()),
            "barrier_supported_cells": int((blocked["movement_support"] > 0).sum()),
            "food_energy_at_population_1": food_one["total_available_energy_kcal_year"],
            "food_energy_at_population_10000": food_many["total_available_energy_kcal_year"]}


def worker():
    before, pins = sources(), predecessors()
    suite = unittest.defaultTestLoader.loadTestsFromName("work.scientific_foundation_r1.test_foundation")
    inventory = sorted(ids(suite))
    expected = sorted("work.scientific_foundation_r1.test_foundation." + cls + ".test_" + name
                      for cls, names in EXPECTED.items() for name in names.split())
    if inventory != expected or len(set(inventory)) != 43:
        raise ValueError("exact scientific foundation test inventory mismatch")
    stream = io.StringIO(); start = time.perf_counter()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    elapsed = time.perf_counter()-start
    if not result.wasSuccessful() or result.skipped or result.expectedFailures or result.unexpectedSuccesses or result.testsRun != len(expected):
        raise ValueError(stream.getvalue())
    scientific = diagnostics()
    if sources() != before or predecessors() != pins:
        raise ValueError("source/predecessor changed during execution")
    print(json.dumps({"status": "PASS", "tests": result.testsRun, "test_inventory": inventory,
                      "verification_seconds": elapsed, "optimise": sys.flags.optimize,
                      "python": sys.version, "sources": before, "predecessors": pins,
                      "diagnostics": scientific, "log": stream.getvalue()}, allow_nan=False))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--worker", action="store_true"); parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.worker:
        worker(); return
    if not args.run_id or not all(x.isalnum() or x in "-_" for x in args.run_id) or len(args.run_id)>80:
        raise ValueError("bounded simple run id required")
    destination = ROOT/"outputs/scientific-corrections-2026-09-09"/args.run_id
    destination.mkdir(parents=True, exist_ok=False)
    before = sources(); environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    workers=[]
    for flags in ([], ["-OO"]):
        result = subprocess.run([sys.executable,"-B",*flags,"-m","work.scientific_foundation_r1.verify","--worker"],
                                cwd=ROOT,env=environment,capture_output=True,text=True,timeout=120)
        if result.returncode:
            with (destination/"FAILED_WORKER.txt").open("x",encoding="utf-8") as out:
                out.write(result.stdout+result.stderr)
            raise ValueError("scientific foundation worker failed: "+result.stderr)
        worker_result = json.loads(result.stdout)
        workers.append(worker_result)
    if workers[0]["diagnostics"] != workers[1]["diagnostics"] or any(w["sources"] != before for w in workers) or sources() != before:
        raise ValueError("independent worker output/source mismatch")
    receipt={"schema":"diadem.scientific-foundation-verification.r1","status":"PASS",
             "workers":workers,"distinct_tests":43,"production_generated":False,
             "installed":False,"physical_acceptance":False,"speedup_measured":False}
    with (destination/"RECEIPT.json").open("x",encoding="utf-8") as out:
        json.dump(receipt,out,indent=2,allow_nan=False); out.write("\n")
    print(json.dumps({"status":"PASS","receipt":str(destination/"RECEIPT.json"),"sha256":sha(destination/"RECEIPT.json"),
                      "distinct_tests":43,"fresh_workers":2,"diagnostics":workers[0]["diagnostics"]}))


if __name__ == "__main__":
    main()
