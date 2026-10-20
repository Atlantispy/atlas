"""Close isolated historical mutation obligations on the exact final r24 source."""
import argparse
import ast
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from support import digest, load_source, read_json, require, verify_pins, write_new

REUSED_DRIVER = HERE.parent / "integrated-focused-r3/driver.py"
REUSED_DRIVER_SHA = "f2303afa5a25a267405ec34903e5c0e9171767e9b23d19893b64f58d81f6b1bc"
D = load_source(REUSED_DRIVER, "frozen_focused_r3_driver", REUSED_DRIVER_SHA)


def declarations():
    return {
        "observer path omitted with coherent termination": {
            "category": "behaviour",
            "cases": ("51", "52", "53", "54"),
            "old": "    prove(entry is not None and file_sha(entry) == observer_pin,\n",
            "new": "    prove(True,\n",
            "status": "FAIL",
            "needle": "not an ordinary file with the pinned observer bytes",
        },
        "peer branch breaks isolated": {
            "category": "behaviour",
            "cases": ("56",),
            "old": "                    live.discard(arm)\n            continue\n",
            "new": "                    live.discard(arm)\n            break\n",
            "status": "FAIL",
            "needle": "after arm interval width gate",
        },
        "unproved stop API defence omitted": {
            "category": "api-defence-only",
            "cases": ("57",),
            "old": "row.get('unproved_stop_fail')",
            "new": "False",
        },
    }


def predicates(template, fault):
    if fault["category"] == "api-defence-only":
        tree = ast.parse(template)
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name.startswith("test_causal_57_"))
        calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "assertEqual"]
        require(len(calls) == 1, "Direct API assertion must be unique")
        return [{"case": "57", "adapter_line": calls[0].lineno}]
    return [{"case": case, "status": fault["status"], "needle": fault["needle"],
             "retained_line": 79} for case in fault["cases"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("selection", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--selection-sha256", required=True)
    args = parser.parse_args()
    require(digest(args.selection) == args.selection_sha256, "Selection changed")
    selected = read_json(args.selection)
    verify_pins(selected["pins"])
    admission = read_json(selected["retained_result"])
    require(admission["passed"] and admission["group"] == "all", "Exact retained71 required")
    base = Path(selected["base"])
    source = (base / "compare_arms_r20.py").read_bytes().decode()
    require(digest(base / "compare_arms_r20.py") ==
            "5f6d97aa222d7a06d12bf87a49d3c5a59a4d271301bb16dc887530e25d3c62cf",
            "This supplement requires the selected final r24 comparator")
    template = (HERE / "cases_template.py").read_text()
    cls = next(node for node in ast.parse(template).body
               if isinstance(node, ast.ClassDef) and node.name == "Causal")
    names = sorted(node.name for node in cls.body if isinstance(node, ast.FunctionDef)
                   and node.name.startswith("test_causal_"))
    require(len(names) == 7, "Expected seven explicit checks")
    expected = ["mutation_adapter.Causal." + name for name in names]
    faults = declarations()
    for fault in faults.values():
        old, new = (D.normal_anchor(source, fault[key]) for key in ("old", "new"))
        require(source.count(old) == 1 and old != new, "Fault anchor missing or ambiguous")
        ast.parse(source.replace(old, new))
        predicates(template, fault)
    require(not args.output.exists(), "Output already exists")
    args.output.mkdir()
    result = {"selected": selected, "expected": expected, "results": {},
              "readiness": False, "scientific_capture": False, "status": "INCOMPLETE"}
    result["baseline"] = D.collect(args.output / "baseline", source, base, template, expected, [])
    write_new(args.output / "baseline-admission.json", result["baseline"]["report"])
    require(result["baseline"]["report"]["baseline_clean"], "Baseline not admitted")
    for index, (label, fault) in enumerate(faults.items()):
        verify_pins(selected["pins"])
        mutated = source.replace(D.normal_anchor(source, fault["old"]),
                                 D.normal_anchor(source, fault["new"]))
        wanted = predicates(template, fault)
        row = D.collect(args.output / ("m%02d" % index), mutated, base, template,
                        expected, wanted)
        row["category"] = fault["category"]
        report = row["report"]
        matched_cases = {match["predicate"]["case"] for match in report["matched"]}
        report["all_predicates_met"] = (report["intended_kill"]
            and matched_cases == set(fault["cases"])
            and not report["other_failure_indices"]
            and report["failure_count"] == len(fault["cases"]))
        row["declared_predicates"] = wanted
        result["results"][label] = row
        print(json.dumps({"label": label, "category": row["category"], **report}), flush=True)
    result["status"] = ("PASS" if all(row["report"]["all_predicates_met"]
                                    for row in result["results"].values())
                        else "NOT_ALL_CERTIFIED")
    verify_pins(selected["pins"])
    write_new(args.output / "result.json", result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
