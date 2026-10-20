"""36 exact frozen mutations, exact baseline, intended predicates, retained streams."""
import argparse
import ast
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import C, ROOT, P, digest, inputs, read_json, require, run_owned, verify_pins, write_new
from predicates import PREDICATES
from report import interpret


def declarations():
    source = C / "runs/mutants_r20.py"
    tree = ast.parse(source.read_bytes(), filename=str(source))
    value, = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "MUTANTS" for target in node.targets)]

    class Categories(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.copy_location(ast.Constant({"B": "behaviour", "P": "provenance",
                                                   "D": "diagnostic"}[node.id]), node)
    return ast.literal_eval(Categories().visit(value))


def generate(folder, source, adapter, selection):
    folder.mkdir()
    tool = folder / "compare_arms_r20.py"
    tool.write_text(source, encoding="utf-8", newline="\n")
    old_sha = selection["comparator_sha256"]
    require(adapter.count(old_sha) == 1, "Adapter comparator pin not unique")
    require(adapter.count("WORK = HERE.parent") == 1, "Adapter WORK anchor not unique")
    text = adapter.replace(old_sha, digest(tool)).replace(
        "WORK = HERE.parent", "WORK = Path(%r)" % selection["work_parent"])
    ast.parse(text)
    target = folder / "test_retained_r20.py"
    target.write_text(text, encoding="utf-8", newline="\n")
    return {"comparator": digest(tool), "adapter": digest(target)}


def collect(folder, source, adapter, selection, expected, predicates):
    generated = generate(folder, source, adapter, selection)
    process = run_owned(folder / "run", [str(P), "-B", "-s", "-P", str(ROOT / "run_cases.py"),
                                       str(folder / "test_retained_r20.py"), str(folder / "summary.json")],
                        folder, 120)
    stderr = (folder / "run/stderr.txt").read_text(encoding="utf-8")
    summary = read_json(folder / "summary.json") if (folder / "summary.json").is_file() else None
    events_path = folder / "summary.events.jsonl"
    events = []
    parse_errors = []
    if events_path.is_file():
        for number, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                events.append(json.loads(line))
            except ValueError as error:
                parse_errors.append("event line %d: %s" % (number, error))
    report = interpret(process, summary, events, stderr, expected, predicates)
    if (digest(folder / "compare_arms_r20.py") != generated["comparator"]
            or digest(folder / "test_retained_r20.py") != generated["adapter"]):
        parse_errors.append("Generated source changed during execution")
    if parse_errors:
        report.update(admitted=False, intended_kill=False, baseline_clean=False)
        report["errors"].extend(parse_errors)
    row = {"generated_pins": generated, "process": process, "report": report,
           "evidence": {str(path): digest(path) for path in
                        (folder / "summary.json", events_path,
                         folder / "run/stdout.txt", folder / "run/stderr.txt") if path.is_file()}}
    write_new(folder / "result.json", row)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("selection", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--selection-sha256", required=True)
    args = parser.parse_args()
    base = inputs()
    require(digest(args.selection) == args.selection_sha256, "Selection changed")
    selection = read_json(args.selection)
    source_pins = selection["pins"]
    verify_pins(source_pins)
    tool = Path(selection["comparator"]).read_text(encoding="utf-8")
    adapter = Path(selection["adapter"]).read_text(encoding="utf-8")
    contract = read_json(selection["contract"])
    mutants = declarations()
    require(list(mutants) == contract["mutant_order"] == list(PREDICATES), "Mutation declarations differ")
    for label, (category, old, new) in mutants.items():
        require(category == contract["mutant_categories"][label], "Mutation category differs")
        require(tool.count(old) == 1 and old != new, "Nonunique/no-op anchor: " + label)
        ast.parse(tool.replace(old, new))
    require(not args.output.exists(), "Output exists; no retry/overwrite")
    args.output.mkdir()
    expected = ["mutation_adapter.Causal." + name for name in contract["causal_names"]]
    result = {"selection": selection, "selection_sha256": args.selection_sha256,
              "baseline": None, "results": {}, "status": "INCOMPLETE", "errors": [],
              "scientific_capture": False, "readiness": False}
    try:
        result["baseline"] = collect(args.output / "baseline", tool, adapter, selection, expected, [])
        require(result["baseline"]["report"]["baseline_clean"], "Exact baseline not admitted; no mutant dispatch")
        for index, (label, (category, old, new)) in enumerate(mutants.items()):
            verify_pins(base)
            verify_pins(source_pins)
            row = collect(args.output / ("m%02d" % index), tool.replace(old, new), adapter,
                          selection, expected, PREDICATES[label])
            row["category"] = category
            result["results"][label] = row
            print(json.dumps({"label": label, "category": category, **row["report"]}), flush=True)
        verify_pins(base)
        verify_pins(source_pins)
        result["categories"] = {
            category: {"count": sum(row["category"] == category for row in result["results"].values()),
                       "intended_kills": [label for label, row in result["results"].items()
                                          if row["category"] == category and row["report"]["intended_kill"]],
                       "not_certified": [label for label, row in result["results"].items()
                                         if row["category"] == category and not row["report"]["intended_kill"]]}
            for category in ("behaviour", "provenance", "diagnostic")}
        result["status"] = ("PASS" if len(result["results"]) == 36 and all(
            row["report"]["intended_kill"] for row in result["results"].values()) else "NOT_ALL_CERTIFIED")
    except BaseException as error:
        import traceback
        result["errors"].append(type(error).__name__ + ": " + str(error))
        result["traceback"] = traceback.format_exc()
    write_new(args.output / "result.json", result)
    print(json.dumps({"status": result["status"], "categories": result.get("categories"),
                      "errors": result["errors"]}), flush=True)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
