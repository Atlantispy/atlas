"""Explicit successor pins, complete supplemental baseline, selected intended faults."""
import argparse
import ast
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from support import P, digest, read_json, require, run_owned, verify_pins, write_new
from report import interpret

DEPENDENCIES = ("fixture_migration.py", "field_contracts.py", "array_bindings_r5.py",
                "array_compare_r21.py")


def declarations():
    return {
        "source exact selectors omitted": ("behaviour", "21",
            "selectors.extend((kind, name) for name in ('time_s', 'max_geometry_volume_error_m3'))",
            "selectors.extend([])", "FAIL", "EXACT_UNAFFECTED_CHANGED"),
        "r5 observation validation omitted": ("behaviour", "22",
            "B.validate_dump_evidence(sys.modules[__name__], record, arm, proof, observer_pin)",
            "pass  # fault: no r5 observation validation", "FAIL",
            "complete interpreter/environment observation changed"),
        "root metadata comparison omitted": ("behaviour", "24",
            "root_compare.compare(root_before, root_after, ('root_metadata',))",
            "pass  # fault: no cross-arm root comparison", "REVIEW", "root_metadata"),
        "array correspondence omitted": ("behaviour", "25",
            "layouts=(layouts['before'], layouts['after'])", "layouts=None", None, None),
        "missing source context warning omitted": ("behaviour", "26",
            "review.extend('i%d source field %s unresolved: %s' %\n"
            "                      (interval, '.'.join(row['path']), row['code']) for row in compiled['unresolved'])",
            "review.extend([])", None, None),
        "outer composition ignored": ("behaviour", "27",
            "supplied.get('composition') == manifests", "True", "FAIL", "composition"),
        "source checked header suppression omitted": ("behaviour", "28",
            "suppressed = set(consumed) | allowed_headers", "suppressed = set(consumed)", None, None),
        "whole composite family validation omitted": ("behaviour", "29",
            "        validate_composite_coverage(C, dump, folder)",
            "        pass  # fault: missing whole-family validation", "FAIL", "network"),
        "peer branch breaks supplemental": ("behaviour-supplement", "30",
            "                    live.discard(arm)\n            continue\n",
            "                    live.discard(arm)\n            break\n", "FAIL", "after arm interval width gate"),
        "unproved stop API defence omitted": ("api-defence-only", "31",
            "row.get('unproved_stop_fail')", "False", None, None),
        "legacy header allowance restored": ("field-behaviour", "32",
            "sub = Comparer(ids, scalar_coverage, legacy_headers=False)",
            "sub = Comparer(ids, scalar_coverage, legacy_headers=True)", None, None),
    }


def normal_anchor(source, old):
    return old.replace("\n", "\r\n") if "\r\n" in source else old


def generate(folder, source, base, template, dependency_changes=None):
    folder.mkdir()
    (folder / "compare_arms_r20.py").write_bytes(source.encode())
    text = (base / "test_retained_r20.py").read_text()
    old_cmp = digest(base / "compare_arms_r20.py")
    require(text.count(old_cmp) == 1, "Comparator selection pin anchor")
    text = text.replace(old_cmp, digest(folder / "compare_arms_r20.py"))
    for name in DEPENDENCIES:
        original = (base / name).read_bytes()
        replacement = (dependency_changes or {}).get(name, original)
        (folder / name).write_bytes(replacement)
        if replacement != original:
            old_pin = digest(base / name)
            require(text.count(old_pin) == 1, "Dependency pin change must be explicit")
            text = text.replace(old_pin, digest(folder / name))
        old, new = repr(str(base / name)), repr(str(folder / name))
        require(text.count(old) == 1, "Dependency selection path: " + name)
        text = text.replace(old, new)
    ast.parse(text)
    (folder / "adapter_base.py").write_text(text, encoding="utf-8", newline="\n")
    wrapper = template.replace("@ADAPTER_SHA256@", digest(folder / "adapter_base.py"))
    ast.parse(wrapper)
    (folder / "test_retained_r20.py").write_text(wrapper, encoding="utf-8", newline="\n")
    pins = {str(p): digest(p) for p in folder.glob("*.py")}
    write_new(folder / "GENERATED-PINS.json", {"pins": pins})
    return pins


def predicate(template, case, status, needle):
    if status is not None:
        return {"case": case, "status": status, "needle": needle,
                "retained_line": 85 if case == "24" else 79}
    tree = ast.parse(template)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Causal")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                  and node.name.startswith("test_causal_" + case + "_"))
    wanted = {"25": "assertIsNone", "26": "assertTrue", "28": "assertFalse", "31": "assertEqual",
              "32": "assertEqual"}[case]
    calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == wanted]
    if case == "26":
        calls = [node for node in calls if "source field" in ast.unparse(node)]
    require(len(calls) == 1, "Direct predicate assertion must be unique")
    return {"case": case, "adapter_line": calls[0].lineno}


def collect(folder, source, base, template, expected, predicates, dependency_changes=None):
    pins = generate(folder, source, base, template, dependency_changes)
    process = run_owned(folder / "run", [str(P), "-B", "-s", "-P",
        str(HERE.parent / "run_cases.py"), str(folder / "test_retained_r20.py"),
        str(folder / "summary.json")], folder, 120)
    summary_path = folder / "summary.json"
    events_path = folder / "summary.events.jsonl"
    summary = read_json(summary_path) if summary_path.is_file() else None
    events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.is_file() else []
    report = interpret(process, summary, events, (folder / "run/stderr.txt").read_text(),
                       expected, predicates)
    verify_pins(pins)
    result = {"process": process, "report": report, "generated_pins": pins,
              "evidence": {str(p): digest(p) for p in
                          (summary_path, events_path, folder / "run/stdout.txt", folder / "run/stderr.txt")
                          if p.is_file()}}
    write_new(folder / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("selection", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--selection-sha256", required=True)
    args = parser.parse_args()
    require(digest(args.selection) == args.selection_sha256, "Selection bytes changed")
    selected = read_json(args.selection)
    verify_pins(selected["pins"])
    admission = read_json(selected["retained_result"])
    require(admission["passed"] and admission["group"] == "all", "Exact retained71 not admitted")
    base = Path(selected["base"])
    source = (base / "compare_arms_r20.py").read_bytes().decode()
    template = (HERE / "cases_template.py").read_text()
    tree = ast.parse(template)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Causal")
    names = sorted(n.name for n in cls.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_causal_"))
    expected = ["mutation_adapter.Causal." + name for name in names]
    faults = declarations()
    binding_source = (base / "array_bindings_r5.py").read_bytes().decode()
    for label, (_, _, old, new, _, _) in faults.items():
        target = binding_source if label == "whole composite family validation omitted" else source
        old, new = normal_anchor(target, old), normal_anchor(target, new)
        require(target.count(old) == 1 and old != new, "Fault anchor missing/ambiguous: " + label)
        ast.parse(target.replace(old, new))
    require(not args.output.exists(), "Output already exists")
    args.output.mkdir()
    result = {"selected": selected, "expected": expected, "results": {}, "readiness": False,
              "scientific_capture": False, "status": "INCOMPLETE"}
    result["baseline"] = collect(args.output / "baseline", source, base, template, expected, [])
    write_new(args.output / "baseline-admission.json", result["baseline"]["report"])
    require(result["baseline"]["report"]["baseline_clean"], "Supplemental baseline not admitted")
    for index, (label, (category, case, old, new, status, needle)) in enumerate(faults.items()):
        verify_pins(selected["pins"])
        dependency_changes = {}
        mutated = source.replace(normal_anchor(source, old), normal_anchor(source, new))
        if label == "whole composite family validation omitted":
            import hashlib
            binding = binding_source.replace(normal_anchor(binding_source, old),
                                             normal_anchor(binding_source, new)).encode()
            dependency_changes["array_bindings_r5.py"] = binding
            original_pin = digest(base / "array_bindings_r5.py")
            require(source.count(original_pin) == 1, "Comparator component-pin anchor")
            mutated = source.replace(original_pin, hashlib.sha256(binding).hexdigest())
        row = collect(args.output / ("m%02d" % index),
                      mutated, base, template, expected, [predicate(template, case, status, needle)],
                      dependency_changes)
        row["category"] = category
        result["results"][label] = row
        print(json.dumps({"label": label, "category": category, **row["report"]}), flush=True)
    result["status"] = "PASS" if all(r["report"]["intended_kill"] for r in result["results"].values()) else "NOT_ALL_CERTIFIED"
    verify_pins(selected["pins"])
    write_new(args.output / "result.json", result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
