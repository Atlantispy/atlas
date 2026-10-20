"""Validate and emit Plan12 invocations. No process/queue dispatch entry point."""
import argparse
import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("plan12_successor_proof_gate", HERE / "proof_gate.py")
GATE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GATE)


def build_plan(manifest_path, sha):
    selection = GATE.validate_selection(manifest_path, sha)
    out = GATE.absolute(selection["output"])
    GATE.require(not out.exists(), "Consumer output exists; refusing reuse")
    python = GATE.TASK / ".r44-env/Scripts/python.exe"
    writer = GATE.INTEGRATION / "ab_heat_r13.py"
    base_environment = {key: value for key, value in os.environ.items()
                        if not key.upper().startswith("PYTHON")}
    base_environment.update(PYTHONHASHSEED="0", ATLAS_HS_DIR=str(GATE.TASK / "hs"))
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        base_environment[key] = "1"
    arms = []
    for index, arm in enumerate(GATE.SCHEDULE):
        environment = dict(base_environment)
        if arm["mode"] == "prof":
            environment.update(PYTHONPATH=str(GATE.TASK / "hs/workerprof"),
                               HS_PROF_DIR=str(out / ("arm-" + str(index))))
        arms.append(dict(index=index, **arm, argv=[
            str(python), "-B", "-s", "-P", str(writer), "child", arm["mode"],
            str(GATE.TASK / "hs" / arm["layout"]), str(out), str(index),
            "--consumer-selection", str(Path(manifest_path).resolve()), sha],
            environment=environment))
    return dict(schema="plan12.successor-launch-plan.r1", queue_ticket="q22",
                manifest_sha256=sha, output=str(out), arms=arms,
                checker_argv=[str(python), "-B", "-s", "-P",
                              str(GATE.TASK / "hs/scripts/check_arms.py"), str(out), "11"],
                execution="NO_DISPATCH; caller must own queued supervision, per-arm admission and finality")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    plan = build_plan(args.manifest, args.manifest_sha256)
    # Do not print inherited environment contents. The in-process supervisor
    # receives them through build_plan(); CLI is a safe route inspection.
    for arm in plan["arms"]:
        arm["environment"] = {key: value for key, value in arm["environment"].items()
                              if key.startswith("PYTHON") or key in
                              ("ATLAS_HS_DIR", "HS_PROF_DIR", "OPENBLAS_NUM_THREADS",
                               "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
                               "VECLIB_MAXIMUM_THREADS")}
    print(json.dumps(plan, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
