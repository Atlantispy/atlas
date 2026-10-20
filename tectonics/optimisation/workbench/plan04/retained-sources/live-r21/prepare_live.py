"""Prepare one explicit guarded live-tool landing and additive profile successor.

This is source/configuration construction only. It neither launches a workload
nor clears readiness, science, queue or per-job holds. All writes are exclusive.
"""
from __future__ import annotations

import ast
import copy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
W = HERE.parents[2]
T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
OPT = "fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014"
R_REL = OPT + "/resumability-r1"
R = T / R_REL
OLD_REL = OPT + "/plan02-live-profile-r2"
NEW_REL = OPT + "/plan04-live-profile-r21"
TOOLS = HERE.parent / "integrated-r24"
OLD = {
    "manifest.json": "06d7ad00e2afb5754355ea29f9fa3f49ca5535738390d0b44f84ea05c43beed9",
    "restart-profile-live-r2.json": "0cc665a8f129905f4b91be786e8f699b497c251af2d949ca6ca69d19657cbc95",
    "runtime-compatibility-policy.json": "2123ecd92cfcfcce76cc437789b509f819ea16bb4c8e04fc7c13704361611367",
}
OLD_LF = "a4d335fd5fa58dffd0c3a0d9f92241f28d3a292ac567e748800e113ec3563717"
PAYLOAD = ("compare_arms_r21.py", "dump_arm_r5.py", "array_bindings_r5.py",
           "array_compare_r21.py", "field_contracts.py", "field_provenance.py",
           "write_captures_map_r3.py")


def need(ok, message):
    if not ok:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def pin(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path, value):
    raw = encoded(value)
    with path.open("xb") as stream:
        stream.write(raw)
    return sha256(raw).hexdigest()


def derive(old, selection, selection_sha):
    manifest = copy.deepcopy(old["manifest.json"])
    lf = R_REL + "/launch_fresh_interval.py"
    need(manifest["files"].get(lf) == OLD_LF, "unexpected predecessor LF pin")
    expected = {"launch_fresh_interval.py", *("n9-tools-r21/" + name for name in PAYLOAD)}
    need(set(selection["assets"]) == expected, "unexpected selected asset set")
    need(all(type(h) is str and re.fullmatch("[0-9a-f]{64}", h)
             for h in selection["assets"].values()), "invalid selected asset hash")
    changes = {R_REL + "/" + path: digest for path, digest in selection["assets"].items()}
    need(not (set(changes) - {lf}) & set(manifest["files"]), "payload path already selected")
    manifest["files"].update(changes)
    manifest["plan04_tool_derivation"] = {
        "schema": "atlas.plan04.live-tool-source-delta.r1",
        "predecessor_manifest": {"path": OLD_REL + "/manifest.json", "sha256": OLD["manifest.json"]},
        "selection": {"path": str(HERE / "selection.json"), "sha256": selection_sha},
        "changed": {lf: {"before": OLD_LF, "after": changes[lf]}},
        "added": {p: h for p, h in changes.items() if p != lf},
        "native_sources_changed": False,
        "scientific_acceptance": False,
    }
    manifest_sha = sha256(encoded(manifest)).hexdigest()
    derivation = {
        "schema": "atlas.plan04.live-profile-derivation.r1",
        "predecessor": {n: {"path": OLD_REL + "/" + n, "sha256": h} for n, h in OLD.items()},
        "source_selection": {"path": str(HERE / "selection.json"), "sha256": selection_sha},
        "manifest": {"path": NEW_REL + "/manifest.json", "sha256": manifest_sha},
        "native_identity_and_native_transfer_repair": "UNCHANGED",
        "readiness": "GUARDED_PENDING_SELECTED_PLAN31_AND_SOURCE_BOUND_FIELD_PROOF",
        "collective_review": "DEFERRED_BY_USER",
        "positive_publish_reopen": "DEFERRED",
        "plan31_replay": "ACTUAL_COMPOSITION_UNAVAILABLE",
        "holds_released": False,
    }
    policy = copy.deepcopy(old["runtime-compatibility-policy.json"])
    policy["current"]["source_manifest_path"] = NEW_REL.split("/", 1)[1] + "/manifest.json"
    policy["current"]["source_manifest_sha256"] = manifest_sha
    policy["evidence"][OLD_REL.split("/", 1)[1] + "/runtime-compatibility-policy.json"] = OLD["runtime-compatibility-policy.json"]
    policy["evidence"][NEW_REL.split("/", 1)[1] + "/derivation.json"] = sha256(encoded(derivation)).hexdigest()
    profile = copy.deepcopy(old["restart-profile-live-r2.json"])
    profile["source_manifest"] = {"path": NEW_REL + "/manifest.json", "sha256": manifest_sha}
    profile["compatibility_policy"] = {"path": NEW_REL + "/runtime-compatibility-policy.json",
                                     "sha256": sha256(encoded(policy)).hexdigest()}
    profile["output_directory"] = str(T / NEW_REL / "runs/direct-r21")
    profile["completed_query_directory"] = NEW_REL + "/completed-queries/direct-r21"
    return {"manifest.json": manifest, "derivation.json": derivation,
            "runtime-compatibility-policy.json": policy, "restart-profile-live-r21.json": profile}


def prepare(evidence_paths):
    need(evidence_paths, "completed executable evidence required")
    old = {}
    for name, digest in OLD.items():
        path = T / OLD_REL / name
        need(pin(path) == digest, "predecessor drift: " + name)
        old[name] = json.loads(path.read_bytes())
    need(pin(R / "launch_fresh_interval.py") == OLD_LF, "live launcher changed during window")
    need(not (R / "n9-tools-r21").exists(), "tool destination already exists")
    need(not (T / NEW_REL).exists(), "profile successor already exists")
    for filename, guard in (("compare_arms_r21.py", "REPAIRS_COMPLETE"), ("dump_arm_r5.py", "EXTRACTION_READY")):
        tree = ast.parse((TOOLS / filename).read_bytes())
        values = [ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == guard
                                                          for t in node.targets)]
        need(values == [False], "technical readiness guard changed: " + guard)
    assets = {"launch_fresh_interval.py": pin(TOOLS / "launch_fresh_interval.py")}
    assets.update({"n9-tools-r21/" + name: pin(TOOLS / name) for name in PAYLOAD})
    evidence = [{"path": str(Path(p).resolve()), "sha256": pin(Path(p))} for p in evidence_paths]
    selection = {
        "schema": "atlas.plan04.live-tool-selection.r1",
        "status": "SELECTED_FOR_GUARDED_LIVE_TOOL_INTEGRATION",
        "authority": "OWNER's 20 October Plan04 ownership and implementation/integration transfer",
        "owner_thread": "01a15805-aa13-7e43-abf7-fce3f487b8b2",
        "assets": assets,
        "evidence": evidence,
        "readiness_guards": {"REPAIRS_COMPLETE": False, "EXTRACTION_READY": False},
        "collective_review": "DEFERRED_BY_USER",
        "actual_plan31_composition": None,
        "science_or_held_job_authority": False,
    }
    selected_sha = write(HERE / "selection.json", selection)
    docs = derive(old, selection, selected_sha)
    profile_pins = {name: write(HERE / name, value) for name, value in docs.items()}
    entries = []
    for destination, digest in assets.items():
        entries.append(dict(source_root="tools", source=Path(destination).name,
                            destination=destination, sha256=digest,
                            expected_live_sha256=OLD_LF if destination == "launch_fresh_interval.py" else None,
                            new_destination=destination != "launch_fresh_interval.py"))
    # The existing transaction keeps the prior live launcher and all failed evidence.
    landing = dict(schema="atlas.plan02.live-landing.v1", source_roots={"tools": str(TOOLS)},
                   destination_root=str(R),
                   selection_record={"path": str(HERE / "selection.json"), "sha256": selected_sha},
                   entries=entries, dependencies=[],
                   notes=["Plan04-owned exact live-tool landing; no science or guard release.",
                          "Exclusive path window confirmed by Plan02; native_transfer remains unchanged."])
    landing_sha = write(HERE / "landing-manifest.json", landing)
    # Only unaffected bindings belong here; the replaced launcher is checked by
    # the transaction's destination preconditions, then by its applied-row checks.
    current = [T / OLD_REL / name for name in OLD]
    current += [R / name for name in (
        "launch_monitored_interval.py", "run_fresh_interval.py", "run_prepared_restart.py",
        "reopen_fresh_restart.py", "reopen_prepared_restart.py", "start_gate.py", "native_transfer.py")]
    need(pin(R / "native_transfer.py") == "7588e9790ff4fe41475b467661e1122e308d0194d45586bc13c2ec080313c2d1",
         "Plan02 native transfer repair drift")
    freeze = dict(schema="atlas.plan02.live-freeze.v1", manifest_sha256=landing_sha,
                  selection_sha256=selected_sha, destination_root=str(R),
                  checked_by="Plan04 implementation owner under explicit user transfer",
                  checked_at_utc=datetime.now(timezone.utc).isoformat(), status="CLEAR_FOR_EXACT_LANDING",
                  evidence=evidence, current_bindings=[{"path": str(p), "sha256": pin(p)} for p in current])
    freeze_sha = write(HERE / "live-freeze.json", freeze)
    result = dict(selection_sha256=selected_sha, landing_manifest_sha256=landing_sha,
                  freeze_sha256=freeze_sha, profile_files=profile_pins,
                  destination_profile=str(T / NEW_REL), assets=assets)
    write(HERE / "PREPARED.json", result)
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", action="append", required=True)
    options = parser.parse_args()
    prepare(options.evidence)
