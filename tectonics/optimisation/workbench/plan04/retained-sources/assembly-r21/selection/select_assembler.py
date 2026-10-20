"""Select frozen Plan04 assembly tooling after exact live landing/caller receipts.

Metadata only: no Atlas import, science, composition construction, queue change
or readiness release. All outputs are exclusive new files in the owned route.
"""
from __future__ import annotations
import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ASSEMBLY = HERE.parent
PLAN04 = ASSEMBLY.parent
LIVE = PLAN04 / "live-r21"
T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
OUTPUT = T / "ac/n9/assembly-r21"
OPT = "fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014"
R_REL = OPT + "/resumability-r1"
R = T / R_REL
PROFILE = T / OPT / "plan04-live-profile-r21"
ASSEMBLER_SHA = "495a8d63f1bb1582a0027938645fab67e7225eb390329d8ec52cacbcf1d69e10"
PAYLOAD = ("compare_arms_r21.py", "dump_arm_r5.py", "array_bindings_r5.py",
           "array_compare_r21.py", "field_contracts.py", "write_captures_map_r3.py",
           "field_provenance.py")
ASSETS = {"launch_fresh_interval.py", *("n9-tools-r21/" + name for name in PAYLOAD)}
PROFILE_FILES = {"manifest.json", "derivation.json", "runtime-compatibility-policy.json",
                 "restart-profile-live-r21.json"}
EVIDENCE = {
    "test_assembly_plan04.py": "063ba6ba14a5e455499d0884711c36471b3ac4dd8c876df3994392fc918a8dc4",
    "tests-r1.log": "ac8a1970a7f38255426b05d49a071684c2df5cb171609d343c18e16d64bce273",
    "verify_inheritance.py": "4428d6cde8e4493a632fa7def2ad08b849ea1fbc1e27c80ac16f186b81d9e854",
    "inheritance-r1.log": "457a2c65520367a0e8040542514e58fd7274cb3b0014c6f41a9b93762ee62267",
    "lint-r1.log": "663e23657079f75f8e02f477cf661ec8177af710433c640d72247074d93730e3",
    "CONTRACT.txt": "d25e459ab6e73f11d56de56f938f3643cedecb26db4483241a13e844f7747850",
}


def need(ok, why):
    if not ok:
        raise ValueError(why)


def plain(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        need(not item.is_symlink() and not (hasattr(item, "is_junction") and item.is_junction()),
             "linked path refused: " + str(item))
    return path


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def read(path, expected):
    need(type(expected) is str and re.fullmatch("[0-9a-f]{64}", expected),
         "explicit lowercase source pin required")
    raw = plain(path).read_bytes()
    need(sha256(raw).hexdigest() == expected, "source drift: " + str(path))
    return raw


def document(path, expected):
    value = json.loads(read(path, expected), object_pairs_hook=unique)
    need(type(value) is dict, "record must be an object: " + str(path))
    return value


def reference(path, digest):
    return {"path": str(plain(path)), "sha256": digest}


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def select(options):
    prepared = document(LIVE / "PREPARED.json", options.prepared_sha256)
    need(set(prepared) == {"selection_sha256", "landing_manifest_sha256", "freeze_sha256",
                          "profile_files", "destination_profile", "assets"}, "PREPARED schema differs")
    selected = document(LIVE / "selection.json", prepared["selection_sha256"])
    need(selected["schema"] == "atlas.plan04.live-tool-selection.r1" and
         selected["status"] == "SELECTED_FOR_GUARDED_LIVE_TOOL_INTEGRATION",
         "live tool selection not established")
    need(selected["collective_review"] == "DEFERRED_BY_USER" and
         selected["actual_plan31_composition"] is None and
         selected["science_or_held_job_authority"] is False and
         selected["readiness_guards"] == {"REPAIRS_COMPLETE": False, "EXTRACTION_READY": False},
         "selection changes readiness, composition or scientific authority")
    assets = prepared["assets"]
    need(type(assets) is dict and set(assets) == ASSETS and selected["assets"] == assets,
         "exact eight selected assets required")
    payload_root = plain(R / "n9-tools-r21")
    need(payload_root.is_dir(), "live payload absent")
    actual = set()
    for path in payload_root.rglob("*"):
        plain(path)
        need(path.is_file() or path.is_dir(), "special payload entry refused")
        if path.is_file():
            actual.add(path.relative_to(R).as_posix())
    need(actual == ASSETS - {"launch_fresh_interval.py"}, "live payload inventory differs")
    asset_bytes = {name: read(R / name, digest) for name, digest in assets.items()}
    for name, guard in (("compare_arms_r21.py", "REPAIRS_COMPLETE"),
                        ("dump_arm_r5.py", "EXTRACTION_READY")):
        tree = ast.parse(asset_bytes["n9-tools-r21/" + name])
        values = [ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and
                  any(isinstance(target, ast.Name) and target.id == guard for target in node.targets)]
        need(values == [False], "technical guard changed: " + guard)
    landing = document(options.landing_receipt, options.landing_receipt_sha256)
    need(landing["status"] == "PASS" and landing.get("original_error") is None and
         not landing.get("rollback") and
         landing["manifest_sha256"] == prepared["landing_manifest_sha256"] and
         set(landing["applied"]) == ASSETS and landing["final_hashes"] == assets,
         "complete successful exact live landing required")
    need(plain(prepared["destination_profile"]) == plain(PROFILE), "wrong installed successor root")
    need(type(prepared["profile_files"]) is dict and set(prepared["profile_files"]) == PROFILE_FILES,
         "successor profile file set differs")
    successor = {name: document(PROFILE / name, pin)
                 for name, pin in prepared["profile_files"].items()}
    caller = document(options.caller_check, options.caller_check_sha256)
    need(caller["status"] == "PASS_SELECTED_TOOL_PROFILE_CALLER_CLOSURE" and
         plain(caller["profile"]) == plain(PROFILE / "restart-profile-live-r21.json") and
         caller["profile_sha256"] == prepared["profile_files"]["restart-profile-live-r21.json"] and
         caller["launcher_sha256"] == assets["launch_fresh_interval.py"],
         "selected caller receipt does not bind this successor")
    for key in ("workload_launched", "store_opened", "native_runtime_imported",
                "readiness_guards", "scientific_acceptance", "holds_released"):
        need(caller.get(key) is False, "caller receipt changed guarded scope: " + key)
    need(caller.get("plan31_composition") == "UNAVAILABLE" and
         caller.get("positive_publish_reopen") == "DEFERRED", "caller receipt scope differs")
    need(all(successor["manifest.json"]["files"].get(R_REL + "/" + name) == pin
             for name, pin in assets.items()), "installed manifest does not select the exact payload")
    derivation = successor["derivation.json"]
    need(derivation["native_identity_and_native_transfer_repair"] == "UNCHANGED" and
         derivation["collective_review"] == "DEFERRED_BY_USER" and
         derivation["plan31_replay"] == "ACTUAL_COMPOSITION_UNAVAILABLE" and
         derivation["holds_released"] is False, "successor derivation changes protected state")
    assembler = OUTPUT / "assemble_r3_plan04.py"
    read(assembler, ASSEMBLER_SHA)
    read(ASSEMBLY / "assemble_r3_plan04.py", ASSEMBLER_SHA)
    for name, pin in EVIDENCE.items():
        read(ASSEMBLY / name, pin)
    contract_path = OUTPUT / "payload-contract.json"
    selection_path = OUTPUT / "selection.json"
    plain(OUTPUT)
    need(OUTPUT.is_dir(), "frozen assembler route missing")
    need(not contract_path.exists() and not selection_path.exists(),
         "selection outputs already exist; retain all previous attempts")
    contract = {
        "schema": "atlas.private.plan04-tool-payload.r1",
        "selection": "Explicitly include the installed guarded Plan04 r21 launcher and seven tool assets "
                     "through this frozen assembler. Tool-only selection; no scientific composition selected.",
        "assets": assets,
    }
    contract_bytes = encoded(contract)
    record = {
        "schema": "atlas.plan04.assembler-selection.r21",
        "status": "SELECTED_GUARDED_ASSEMBLY_TOOLING_PENDING_PLAN31_BINDING",
        "authority": selected["authority"],
        "assembler": reference(assembler, ASSEMBLER_SHA),
        "inherited_plan06_assembler_sha256":
            "c84f98bf62116553b92103bd16a2d6f0fbf5d027c8273f6f90ab8fadfa80f45d",
        "payload_contract": reference(contract_path, sha256(contract_bytes).hexdigest()),
        "prepared": reference(LIVE / "PREPARED.json", options.prepared_sha256),
        "live_selection": reference(LIVE / "selection.json", prepared["selection_sha256"]),
        "landing_receipt": reference(options.landing_receipt, options.landing_receipt_sha256),
        "caller_check": reference(options.caller_check, options.caller_check_sha256),
        "successor_files": {name: reference(PROFILE / name, pin)
                            for name, pin in prepared["profile_files"].items()},
        "assets": assets,
        "boundary_evidence": {
            "result": "24/24 synthetic assembly controls; inherited AST PASS; focused lint 0 findings",
            "files": {name: reference(ASSEMBLY / name, pin) for name, pin in EVIDENCE.items()},
            "scope": "software construction only; not runtime/parity/scientific evidence",
            "resource_scope": "AST/lint ended 07:59:10 with possible q26 overlap; no isolated timing/resource claim",
        },
        "writer": reference(Path(__file__), sha256(Path(__file__).read_bytes()).hexdigest()),
        "collective_review": "DEFERRED_BY_USER",
        "readiness_guards": selected["readiness_guards"],
        "native_identity_and_native_transfer_repair": "UNCHANGED",
        "holds_released": False,
        "scientific_acceptance": False,
        "actual_plan31_composition": None,
        "next_binding_obligation": [
            "Select the actual Plan31 source composition explicitly; no historical or Plan06 substitution.",
            "Create a new staged R-shaped root with exactly these eight payload assets.",
            "Pin the launcher in its generation and every payload asset in the independent input binding "
            "with provenance and explicit source selection; retain any separately selected D5 contract.",
            "Run the frozen assembler --check, --pin and --compose with the pinned payload contract, "
            "reviewed dry input and a new permanent target, under existing authority/queue controls.",
            "Complete selected-source field semantics/correspondence, review and scientific prerequisites "
            "before any technical guard or held run is released.",
        ],
    }
    # Validation is complete before the first metadata write. A partial write is
    # retained and cannot be silently retried or mistaken for completed selection.
    with contract_path.open("xb") as stream:
        stream.write(contract_bytes)
    with selection_path.open("xb") as stream:
        stream.write(encoded(record))
    print(json.dumps({"status": record["status"],
                      "selection": reference(selection_path, sha256(selection_path.read_bytes()).hexdigest()),
                      "payload_contract": record["payload_contract"]}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-sha256", required=True)
    parser.add_argument("--landing-receipt", type=Path, required=True)
    parser.add_argument("--landing-receipt-sha256", required=True)
    parser.add_argument("--caller-check", type=Path, required=True)
    parser.add_argument("--caller-check-sha256", required=True)
    select(parser.parse_args())
