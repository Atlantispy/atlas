"""Matched, bounded transport-lifetime comparison; no fine coupled campaign.

Each timed trial includes a fresh execution context, plan, case2a solve, numeric
output materialisation, and plan/context close. Byte comparisons and report I/O
are outside the timer. Temporary reference bytes keep earlier result objects and
their budget leases out of subsequent trials. No public report contains paths.
"""
from __future__ import annotations

import argparse
from dataclasses import fields
import gc
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import traceback
from time import perf_counter


CAP_BYTES = 128 * 1024**2
MODES = ("retained", "phase-local")
REPEATS = 3
OPERATIONAL_SUBTREES = frozenset({"phase_local_stats", "phase-local_stats"})


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def materialise(result, np):
    payloads, inventory = {}, {}
    for field in fields(result):
        value = getattr(result, field.name)
        if isinstance(value, np.ndarray):
            array = value
        elif isinstance(value, (int, float, bool, tuple)):
            array = np.asarray(value)
        else:
            continue
        if array.dtype.kind not in "biufc":
            raise TypeError(f"Unsupported numeric field: {field.name}")
        payload = array.tobytes(order="C")
        payloads[field.name] = payload
        inventory[field.name] = dict(dtype=array.dtype.str, shape=list(array.shape),
                                    bytes=len(payload), sha256=sha256(payload))
    return payloads, inventory, result.statistics


def compare_bytes(payloads, inventory, reference_dir, reference_inventory):
    """Direct byte equality, including array dtype/shape; hashes are evidence only."""
    if reference_inventory is None:
        for name, payload in payloads.items():
            (reference_dir / f"{name}.bin").write_bytes(payload)
        return inventory
    if inventory.keys() != reference_inventory.keys():
        raise ValueError("Numeric result field membership differs")
    for name, payload in payloads.items():
        metadata = {k: v for k, v in inventory[name].items() if k != "sha256"}
        expected = {k: v for k, v in reference_inventory[name].items() if k != "sha256"}
        if metadata != expected:
            raise ValueError(f"Numeric field layout differs: {name}")
        with (reference_dir / f"{name}.bin").open("rb") as stream:
            view = memoryview(payload)
            for offset in range(0, len(payload), 1024**2):
                expected_bytes = min(1024**2, len(payload) - offset)
                chunk = stream.read(expected_bytes)
                if len(chunk) != expected_bytes or chunk != view[offset:offset + expected_bytes]:
                    raise ValueError(f"Numeric field bytes differ: {name}")
            if stream.read(1):
                raise ValueError(f"Numeric field length differs: {name}")
    return reference_inventory


def run_trial(mode, spacing, solve, api, reference_dir, reference_inventory):
    np, PreparedSubduction, ExecutionContext, WorkBudget, kwargs = api
    owner = WorkBudget(CAP_BYTES)
    row = dict(transport_lifetime=mode, spacing_km=spacing,
               kind="coupled" if solve else "construction-only", status="RUNNING")
    context = plan = result = snapshot_lease = None
    payloads = None
    try:
        gc.collect()  # Outside timer; identical fresh preparation for both modes.
        start = perf_counter()
        try:
            context = ExecutionContext("scipy")
            plan = PreparedSubduction(spacing, context=context, budget=owner,
                                      transport_lifetime=mode, **kwargs)
            row["execution_id"] = plan.execution_id
            row["initial_parent_budget"] = owner.statistics()
            transport = plan.transport
            row["initial_transport"] = dict(
                present=transport is not None,
                retained_payload_bytes=getattr(transport, "retained_payload_bytes", 0),
                retained_allowance_bytes=getattr(transport, "retained_allowance_bytes", 0))
            row["mesh"] = dict(triangles=len(plan.mesh.cells),
                               points=len(plan.mesh.points),
                               wedge_triangles=len(plan.wedge.cells))
            transport = None
            if solve:
                result = plan.solve("2a")
                row["scientific_parent_peak_bytes"] = owner.peak_reserved_bytes
                # Keep explicit accounting for the detached verification bytes.
                # Diagnostics are small; their complete encoded form must fit.
                numeric_bytes = sum(getattr(result, f.name).nbytes for f in fields(result)
                                    if isinstance(getattr(result, f.name), np.ndarray))
                lease = owner.reserve(numeric_bytes + 1024**2,
                                      category="benchmark-materialisation")
                lease.__enter__()
                snapshot_lease = lease
                payloads, inventory, stats = materialise(result, np)
                if sum(map(len, payloads.values())) > numeric_bytes + 1024**2:
                    raise ValueError("Materialised diagnostics exceed reserved allowance")
                row.update(numeric_fields=inventory, statistics=stats,
                           diagnostics_c=list(result.diagnostics_c),
                           nonlinear_iterations=result.iterations)
                for key in OPERATIONAL_SUBTREES:
                    if key in stats:
                        row[key] = stats[key]
        finally:
            result = None
            try:
                if plan is not None:
                    plan.close()
            finally:
                if context is not None:
                    context.close()
            row["elapsed_s"] = perf_counter() - start
            row["timed_parent_peak_bytes"] = owner.peak_reserved_bytes
            row["parent_after_close_bytes"] = owner.reserved_bytes
        if solve:
            # This scratch is outside the matched timer and its peak snapshot.
            with owner.reserve(1024**2, category="benchmark-byte-comparison"):
                reference_inventory = compare_bytes(payloads, inventory, reference_dir,
                                                    reference_inventory)
            row["numeric_bitwise_parity"] = True
        row["status"] = "PASS"
    except BaseException as exc:
        traceback.print_exc()  # Retain actionable local failure, not private paths in public JSON.
        row.update(status="FAIL", error_type=type(exc).__name__)
        # Exception messages can contain private paths: retain only their type.
    finally:
        payloads = None
        if snapshot_lease is not None:
            snapshot_lease.__exit__(None, None, None)
        plan = context = None
        gc.collect()
        row["final_parent_budget"] = owner.statistics()
        row["final_release"] = owner.reserved_bytes == 0
        if not row["final_release"]:
            row["status"] = "FAIL"
            row["release_error"] = "accounted reservation survived final release"
    return row, reference_inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="Atlas repository root")
    parser.add_argument("--report", type=Path, required=True, help="Output JSON path")
    args = parser.parse_args()
    tectonics = args.repo.resolve() / "tectonics"
    sys.path.insert(0, str(tectonics / "src"))
    import numpy as np
    import scipy
    from atlas_tectonics.subduction import PreparedSubduction
    from atlas_tectonics.reuse import ExecutionContext
    from atlas_tectonics.resources import WorkBudget

    fixture_path = tectonics / "cases" / "w08_subduction_r3.json"
    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes)
    kwargs = dict(source_id=fixture["adapter_id"] + ":" + sha256(fixture_bytes),
                  outflow_operator=fixture["thermal_outflow_operator"],
                  stabilisation="supg", mesh_grading="corner-r5",
                  coupling_trace="nodal-p2-v1")
    api = np, PreparedSubduction, ExecutionContext, WorkBudget, kwargs

    def source_inventory():
        return {p.name: sha256(p.read_bytes())
                for p in sorted((tectonics / "src" / "atlas_tectonics").glob("*.py"))}

    sources = source_inventory()
    report = dict(schema="atlas.transport-lifetime-benchmark.v1",
        source_status="WORKING NON-CANON", status="RUNNING",
        fixture="w08_subduction_r3.json", fixture_sha256=sha256(fixture_bytes),
        driver_sha256=sha256(Path(__file__).read_bytes()), sources=sources,
        environment=dict(python=platform.python_version(), system=platform.system(),
                         numpy=np.__version__, scipy=scipy.__version__),
        parameters=dict(kwargs, case="2a", coupled_spacing_km=6.,
                        construction_only_spacing_km=1.5, repeats=REPEATS,
                        owner_max_bytes=CAP_BYTES, native_threads=1),
        timing_scope="fresh ExecutionContext + plan + solve + materialised numeric fields and diagnostics + close",
        timing_excludes="imports, pretrial GC, byte comparison, report/reference I/O and final verification cleanup",
        memory_scope="WorkBudget accounting, not process RSS; materialisation allowance is separately labelled",
        parity_scope="all nine numeric result arrays, three diagnostics_c values and iteration count; direct byte equality; nested statistics recorded separately",
        identity_policy="result identity is not used for numeric parity",
        construction_scope="one construction and close per mode at 1.5km; no solve and no timing speedup claim",
        rows=[], construction_rows=[])
    args.report.parent.mkdir(parents=True, exist_ok=True)

    def write_report():
        args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    write_report()
    with tempfile.TemporaryDirectory(prefix="transport-lifetime-reference-") as temporary:
        reference_dir, reference_inventory = Path(temporary), None
        for repeat in range(REPEATS):
            order = MODES if repeat % 2 == 0 else MODES[::-1]
            for mode in order:
                row, reference_inventory = run_trial(mode, 6., True, api, reference_dir,
                                                     reference_inventory)
                row["repeat"] = repeat + 1
                report["rows"].append(row)
                write_report()
                print(json.dumps({key: row[key] for key in
                                  ("kind", "transport_lifetime", "repeat", "status", "elapsed_s", "final_release")}), flush=True)
                if row["status"] != "PASS":
                    report["status"] = "FAILED_PARTIAL"
                    write_report()
                    return 1
        for mode in MODES:
            row, _ = run_trial(mode, 1.5, False, api, reference_dir, None)
            report["construction_rows"].append(row)
            write_report()
            print(json.dumps({key: row[key] for key in
                              ("kind", "transport_lifetime", "status", "elapsed_s", "final_release")}), flush=True)
            if row["status"] != "PASS":
                report["status"] = "FAILED_PARTIAL"
                write_report()
                return 1
    measured = {mode: [row["elapsed_s"] for row in report["rows"]
                       if row["transport_lifetime"] == mode] for mode in MODES}
    retained, local = (statistics.median(measured[mode]) for mode in MODES)
    report["timings"] = dict(raw_seconds=measured, retained_median_s=retained,
        phase_local_median_s=local, phase_local_minus_retained_s=local-retained,
        phase_local_minus_retained_percent=100*(local-retained)/retained,
        positive_delta_means="phase-local slower")
    report["source_unchanged"] = (source_inventory() == sources
                                 and fixture_path.read_bytes() == fixture_bytes)
    report["all_numeric_outputs_bitwise_equal"] = all(r["numeric_bitwise_parity"] for r in report["rows"])
    report["all_final_released"] = all(r["final_release"] for r in report["rows"] + report["construction_rows"])
    report["status"] = "PASS" if report["source_unchanged"] else "FAIL_SOURCE_CHANGED"
    write_report()
    print(json.dumps(dict(status=report["status"], timings=report["timings"],
                         all_final_released=report["all_final_released"])), flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
