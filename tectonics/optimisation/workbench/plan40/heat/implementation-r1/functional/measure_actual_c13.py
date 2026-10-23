"""Complete imported C13 component arms; timing requires externally granted GO."""
if not __debug__:
    raise RuntimeError("Optimised Python is refused: correctness assertions required")

import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
PINS = {
    "check_functional.py": "bd05f15b48b5bdc757985fc223520e0f0a823239577c339f50676ed16972b091",
    "RESULTS-r1.json": "09bd1d47220b444a9768188f75eb9a7b7da7365b654deb93c9802b2c7ebb7427",
    "private_heat_polygon_numerics_40b_r1.py": "5991aca3ed26e65e2290be6c1ee4052f15b74a1e770b9606849263e25b12f00c",
    "private_heat_polygon_moment_40b_r1.py": "de56233d0272555e7998f1dc5418a65c017abcb7a51e3a48aaea62738ca4bfd0",
    "private_heat_functionals_kernel_40b_r1.py": "0c9606475fb7e6576d94680c0d7b2757e8088c0d94bc20564e842ea45c3a1c59",
}
PREDECESSORS = {
    "private_heat_polygon_moment_inventory_r1.py": "3702ff5135b841929eb06d83204292531d10ff6b7dcbc2717f2c24f9660137fc",
    "private_heat_polygon_moment_inventory_r4.py": "ad0183ef0ba511d23c7810e6a9a4f8c37599f229fe19604e1f94bc3d3a892e2a",
    "private_heat_functionals_kernel_r1.py": "a48f115e8018b9c2d831ce1442cba1060a22d0a5fdbc39b6c8165674a0b0ab56",
}


def pinned(path, expected):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError("Pinned input changed: " + path.name)
    return raw


def load_component(args):
    # Reuse only the already checked setup/fixtures, stopping before invoke or
    # any correctness execution. Successors themselves use ordinary imports.
    raw = {name: pinned(HERE / name, expected) for name, expected in PINS.items()}
    evidence = json.loads(raw["RESULTS-r1.json"])
    if evidence["status"] != "PASS" or evidence["candidate"] != "C13":
        raise ValueError("Bounded correctness evidence is not passing C13")
    tree = ast.parse(raw["check_functional.py"])
    cut = next(i for i, node in enumerate(tree.body)
               if isinstance(node, ast.FunctionDef) and node.name == "invoke")
    setup = ast.Module(body=tree.body[:cut], type_ignores=[])
    env = {"__file__": str(HERE / "check_functional.py"), "__name__": "c13_checked_setup"}
    old_argv = sys.argv
    sys.argv = [str(HERE / "check_functional.py"), "--repo", str(args.repo),
                "--testing", str(args.testing), "--output", str(args.output)]
    try:
        exec(compile(setup, str(HERE / "check_functional.py"), "exec"), env)
    finally:
        sys.argv = old_argv
    for name, expected in PREDECESSORS.items():
        path, _ = env["source"](name)
        pinned(path, expected)
    return env


def run_arm(env, candidate):
    # The clock surrounds this entire function: budget/poll construction,
    # M.admit (including START fence and full plan), numerical/source work,
    # retained transfer, diagnostic export, owner retirement and budget checks.
    function = env["NEW" if candidate else "BASE"].second_moment
    values, accounting = [], []
    fence_before = env["fence_calls"]
    for name, face in env["cases"].items():
        budget, poll = env["Budget"](64 << 20), env["Poll"]()
        owner = function(face, budget=budget, cancel=poll)
        try:
            value = owner.value
            matrix, plan = value["moment"], value["inventory"]
            assert len(matrix) == 3 and len({id(row) for row in matrix}) == 3
            # Diagnostic export is included equally in both arms. Hashing and
            # comparison occur afterwards, outside clocks and live owners.
            values.append((name, env["freeze"](matrix), env["freeze"](plan.__dict__)))
            accounting.append({"case": name, "plan_bytes": plan.total_bytes,
                               "retained_bytes": budget.reserved_bytes,
                               "peak_bytes": budget.peak_reserved_bytes,
                               "polls": poll.calls})
            value = matrix = plan = None
        finally:
            owner.close()
        if budget.reserved_bytes != 0:
            raise AssertionError("Native owner charge survived close")
    return {"values": values, "work": accounting,
            "component_calls": len(values),
            "start_component_fence_calls": env["fence_calls"] - fence_before}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--testing", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", choices=("C13",), default="C13")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--smoke", action="store_true", help="Default; same loop, clock calls refused")
    mode.add_argument("--benchmark", action="store_true")
    parser.add_argument("--queue-go", action="store_true", help="Not authority; requires external queue GO")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be new")
    if args.benchmark and not args.queue_go:
        parser.error("Benchmark requires external queue GO and --queue-go")
    record = {"schema": "plan40b.actual-c13-measurement.r1", "status": "FAIL",
              "candidate": "C13", "mode": "benchmark" if args.benchmark else "smoke",
              "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "implementation_and_evidence_pins": PINS, "predecessor_pins": PREDECESSORS,
              "samples": [], "candidates": {"C13": {"status": "FAIL"}}}
    original_clocks = {name: getattr(time, name) for name in
                       ("perf_counter", "perf_counter_ns", "process_time", "process_time_ns")}
    def forbidden_clock():
        raise RuntimeError("Smoke attempted a performance clock call")
    if not args.benchmark:
        for name in original_clocks:
            setattr(time, name, forbidden_clock)
    clock = original_clocks["perf_counter"] if args.benchmark else forbidden_clock
    try:
        began = clock() if args.benchmark else None
        env = load_component(args)
        if args.benchmark:
            record["component_load_setup_seconds"] = clock() - began
        record["source_bindings"] = env["ns"]["bindings"]
        record["workload_sha256"] = env["digest"](env["cases"])
        record["runtime"] = {"python": sys.version, "gmpy2": env["G"].version()}
        expected = None
        preflight = {}
        for candidate in (False, True):
            output = run_arm(env, candidate)
            signature = env["digest"](output.pop("values"))
            if expected is not None and signature != expected:
                raise AssertionError("Baseline/candidate preflight mismatch")
            expected = signature
            preflight["candidate" if candidate else "baseline"] = {"result_digest": signature, **output}
        record["preflight"] = preflight
        for block in range(3):
            order = (False, True, True, False) if block % 2 == 0 else (True, False, False, True)
            for position, candidate in enumerate(order):
                began = clock() if args.benchmark else None
                output = run_arm(env, candidate)
                seconds = clock() - began if args.benchmark else None
                signature = env["digest"](output.pop("values"))
                if signature != expected:
                    raise AssertionError("Sample output differs from preflight")
                row = {"block": block, "position": position, "order": "ABBA" if block % 2 == 0 else "BAAB",
                       "arm": "candidate" if candidate else "baseline", "result_digest": signature,
                       "equal_outside_timing": True, **output}
                if args.benchmark:
                    row["seconds"] = seconds
                record["samples"].append(row)
        record.update(status="PASS", candidates={"C13": {"status": "PASS", "component": "actual admitted polygon module"}},
                      sampled_component_calls=48, preflight_component_calls=8,
                      performance_clock_sentinel_active=not args.benchmark,
                      limits=["Synthetic four-shape component workload; no whole-heat speed inference",
                              "Original START private fence explicitly injected with selected component hash checks in both arms",
                              "Candidate's additional source/callable checks execute unchanged inside every measured component call",
                              "Native plan, owner, retained transfer and close executed; whole-runtime/worker/issuer qualification absent",
                              "Diagnostic canonical export included symmetrically; comparison and hashing outside timing",
                              "One-time imports/fixture setup reported separately; per-call setup and retirement included",
                              "Existing four-case/thirteen-fault proof reused unchanged; no science or worker run"])
    except Exception as error:
        record["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        for name, value in original_clocks.items():
            setattr(time, name, value)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
    print(json.dumps({"status": record["status"], "candidate": "C13", "mode": record["mode"],
                      "samples": len(record["samples"]), "error": record.get("error")}))
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
