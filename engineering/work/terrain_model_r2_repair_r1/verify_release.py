"""Two fresh-process, bounded release checks; no performance gain claim."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

import fixtures
import physical_evidence
import transient_verification
import workflow

HERE=Path(__file__).resolve().parent


def closure_pins():
    return [{"name":p.relative_to(HERE).as_posix(),"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}
            for p in sorted(HERE.rglob("*")) if p.suffix in {".py",".json",".md",".ps1"}
            for data in [workflow.read_bytes(p)]]


def require_test_success(tested,log):
    # The first independently reviewed suite contained 234 tests. A missing
    # module or empty discovery cannot silently become a passing release.
    if tested.testsRun<234 or not tested.wasSuccessful() or tested.skipped:
        raise RuntimeError("reviewed test inventory incomplete or failed\n"+log)


def peak_working_set():
    if sys.platform!="win32":return None
    class Counters(ctypes.Structure):
        _fields_=[("cb",wintypes.DWORD),("PageFaultCount",wintypes.DWORD),
            *[(name,ctypes.c_size_t) for name in ("PeakWorkingSetSize","WorkingSetSize","QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage","QuotaPeakNonPagedPoolUsage","QuotaNonPagedPoolUsage","PagefileUsage","PeakPagefileUsage")]]
    kernel=ctypes.WinDLL("kernel32",use_last_error=True);psapi=ctypes.WinDLL("psapi",use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


def worker(root,number):
    start=time.perf_counter();pins=workflow.implementation_pins();closure=closure_pins()
    stream=io.StringIO();tests=unittest.defaultTestLoader.discover(str(HERE),pattern="test_*.py")
    tested=unittest.TextTestRunner(stream=stream,verbosity=1).run(tests)
    require_test_success(tested,stream.getvalue())
    measurements=[];results={}
    for recipe in fixtures.suite():
        source=root/"recipes"/(recipe["scenario_id"]+".json")
        output=root/f"process-{number:02d}"/recipe["scenario_id"]
        before=time.perf_counter();receipt=workflow.run(source,output)
        elapsed=time.perf_counter()-before
        before=time.perf_counter();reused=workflow.run(source,output,resume=True)
        reuse_elapsed=time.perf_counter()-before
        results[recipe["scenario_id"]]=hashlib.sha256(workflow.read_bytes(output/"RESULT.json")).hexdigest()
        measurements.append({"scenario":recipe["scenario_id"],"commit_wall_seconds":elapsed,
            "verified_reuse_wall_seconds":reuse_elapsed,"output_bytes":sum(p.stat().st_size for p in output.iterdir()),
            "generation_id":receipt["generation_id"],"reuse_status":reused["status"]})
    recovery=root/f"process-{number:02d}"/"recovery-check"
    source=root/"recipes"/(fixtures.suite()[0]["scenario_id"]+".json")
    try:workflow.run(source,recovery,interrupt_at="after_products")
    except RuntimeError as exc:
        if str(exc)!="injected interruption after products":raise
    else:raise AssertionError("interruption injection did not happen")
    workflow.run(source,recovery,resume=True)
    if workflow.read_bytes(recovery/"RESULT.json")!=workflow.read_bytes(root/f"process-{number:02d}"/fixtures.suite()[0]["scenario_id"]/"RESULT.json"):
        raise AssertionError("recovered logical bytes differ")
    try:workflow.execute(fixtures.near_flat_capture_regression())
    except ValueError as exc:
        if "relative link relief" not in str(exc):raise
        unsupported=str(exc)
    else:raise AssertionError("known unsupported capture no longer rejected; review required")
    evidence=physical_evidence.run_evidence()
    transient=transient_verification.run_verification()
    if pins!=workflow.implementation_pins() or closure!=closure_pins():raise ValueError("implementation changed during release verification")
    report={"process":number,"implementation":pins,"source_closure":closure,"tests":{"run":tested.testsRun,"failures":len(tested.failures),
        "errors":len(tested.errors),"skipped":len(tested.skipped),"log":stream.getvalue()},
        "results_sha256":results,"measurements":measurements,"recovery":"EXACT_PRODUCTS_AFTER_INJECTED_INTERRUPTION",
        "known_unsupported_capture":unsupported,"transient":transient,"observational_comparison":evidence,
        "whole_worker_wall_seconds":time.perf_counter()-start,"peak_working_set_bytes":peak_working_set(),
        "resource_boundary":"worker Python peak includes tests, receipts, recovery and observation comparison; excludes child-process working sets (including PowerShell); wall time includes those child executions; not standalone terrain peak",
        "optimisation_speedup_percent":None,"production_authorised":False}
    workflow.write_json_new(root/f"process-{number:02d}.json",report)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--worker",type=int,choices=(1,2));args=parser.parse_args()
    root=workflow.unlinked(args.output);allowed=HERE.parents[1]/"outputs"/"terrain-model-r2-repair-r1"
    if not root.is_relative_to(allowed.resolve()) or root==allowed.resolve():raise ValueError("release output outside candidate root")
    if args.worker:
        worker(root,args.worker);return
    root.mkdir(parents=True,exist_ok=False);(root/"recipes").mkdir()
    pins=workflow.implementation_pins();closure=closure_pins()
    for recipe in fixtures.suite():workflow.write_json_new(root/"recipes"/(recipe["scenario_id"]+".json"),recipe)
    for number in (1,2):
        completed=subprocess.run([sys.executable,"-B",str(__file__),"--output",str(root),"--worker",str(number)],
                                 capture_output=True,text=True,timeout=120)
        if completed.returncode:raise RuntimeError(completed.stdout+completed.stderr)
    first=workflow.read_json(root/"process-01.json");second=workflow.read_json(root/"process-02.json")
    for key in ("results_sha256","implementation","source_closure","transient","observational_comparison","known_unsupported_capture"):
        if workflow.canonical(first[key])!=workflow.canonical(second[key]):raise ValueError("fresh-process parity differs:"+key)
    if workflow.implementation_pins()!=pins or closure_pins()!=closure:raise ValueError("release source drift")
    report={"status":"BOUNDED_REFERENCE_RELEASE_VERIFIED_NOT_WHOLE_MODEL_ACCEPTANCE","fresh_processes":2,
        "tests_per_process":[r["tests"]["run"] for r in (first,second)],"scenarios":len(first["results_sha256"]),
        "exact_logical_parity":True,"exact_observational_comparison_parity":True,
        "peak_working_set_bytes":[r["peak_working_set_bytes"] for r in (first,second)],
        "whole_worker_wall_seconds":[r["whole_worker_wall_seconds"] for r in (first,second)],
        "implementation":pins,"source_closure":closure,"results_sha256":first["results_sha256"],
        "resource_boundary":first["resource_boundary"],"optimisation_speedup_percent":None,
        "physical_acceptance":False,"production_authorised":False,"canon_changed":False}
    workflow.write_json_new(root/"REFERENCE_VERIFICATION.json",report)
    print(json.dumps({k:v for k,v in report.items() if k not in {"implementation","source_closure","results_sha256"}},indent=2))


if __name__=="__main__":main()
