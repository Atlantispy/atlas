"""Verify exact unchanged boundaries before reusing retained executable evidence."""
import ast
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def need(ok, why):
    if not ok:
        raise ValueError(why)


def definitions(path):
    return {node.name: ast.dump(node, include_attributes=False)
            for node in ast.parse(path.read_bytes()).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


base = HERE.parent / "causal-r20/compare_arms_r20.py"
need(sha256(base.read_bytes()).hexdigest() == "e4c93e5262f9931f355495e0b8bf57848ffa0bb179fa0692385d63a58d66a4ce",
     "frozen r20 differs")
before, after = definitions(base), definitions(HERE / "compare_arms_r21.py")
changed = {name for name in set(before) & set(after) if before[name] != after[name]}
need(not set(before) - set(after), "predecessor definitions were removed")
need(changed == {"Comparer", "load_dump", "load_contract", "reader_pairs", "compare",
                 "validate_dump_descriptors"},
     "unexpected predecessor changes: " + repr(changed))
need(set(after) - set(before) ==
     {"component", "source_inventories", "header_producer", "scrub_quantities", "header_paths",
      "ProvedRecordBytes"},
     "unexpected added definitions")
retained = HERE.parent / "caller-controls-r21/selected-r1/compare_arms_r21.py"
need(sha256(retained.read_bytes()).hexdigest() == "79cb825948355f75aceaa66d0d7ae132bbe960e894cc4d82a16f17af0eb02092",
     "retained caller snapshot changed")
tested = definitions(retained)
caller_changes = {name for name in set(tested) & set(after) if tested[name] != after[name]}
need(caller_changes == {"Comparer", "compare", "scrub_quantities", "validate_dump_descriptors"},
     "changed capture-map/dump caller boundary: " + repr(caller_changes))
old_map = HERE.parent / "caller-controls-r21/selected-r1/write_captures_map_r3.py"
new_map = HERE / "write_captures_map_r3.py"
need(definitions(old_map) == definitions(new_map), "capture map executable functions changed")
old_ast, new_ast = ast.parse(old_map.read_bytes()), ast.parse(new_map.read_bytes())
for tree in (old_ast, new_ast):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "COMPARATOR_SHA256"
                                                for t in node.targets):
            node.value = ast.Constant("<explicit-successor-pin>")
need(ast.dump(old_ast) == ast.dump(new_ast), "map changed beyond explicit comparator pin")
need(sha256((HERE / "launch_fresh_interval.py").read_bytes()).hexdigest() ==
     "1504e560fff09a78811501920f7fce31371666a16087eae15c5b5728c7ef0e0c", "LF successor differs")
mask_baseline = HERE.parent / "integrated-r21/compare_arms_r21.py"
need(sha256(mask_baseline.read_bytes()).hexdigest() ==
     "d270aabde3f7277cc973d324e1f1b0fc1b0db2c69b9b4560db506ca56e53dcef",
     "retained mask-control source changed")
mask_definitions = definitions(mask_baseline)
need(all(mask_definitions[name] == after[name]
         for name in ("scrub_quantities", "header_paths", "Comparer")),
     "changed tested quantity masking semantics")
need((HERE / "test_record_masks_r2.py").read_bytes() ==
     (mask_baseline.parent / "test_record_masks_r2.py").read_bytes(),
     "mask controls changed")
print(json.dumps({"status": "PASS_UNCHANGED_SOURCE_BOUNDARIES",
                  "comparator_sha256": sha256((HERE / "compare_arms_r21.py").read_bytes()).hexdigest(),
                  "r20_changed_definitions": sorted(changed),
                  "caller_snapshot_changed_definitions": sorted(caller_changes),
                  "source_reuse": ["unchanged proof and causal helper functions",
                                  "actual LF capture/map/load_captures caller controls",
                                  "unchanged dump implementation and frozen component controls",
                                  "four quantity masking controls on exact unchanged helper AST"],
                  "new_record_semantics": "requires selected successor adapter and provenance propagation controls"}))
