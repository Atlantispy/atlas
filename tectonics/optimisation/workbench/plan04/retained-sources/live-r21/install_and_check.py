"""Install additive profile metadata and verify the real selected caller boundary.

No native runtime, store, producer, reader or science workload is executed.
The old profile and every protected composition remain unchanged.
"""
from __future__ import annotations
import argparse
import importlib
import importlib.util
import json
from pathlib import Path
import sys

_prepare_spec = importlib.util.spec_from_file_location(
    "plan04_live_delta", Path(__file__).resolve().parent / "prepare_live.py")
D = importlib.util.module_from_spec(_prepare_spec)
_prepare_spec.loader.exec_module(D)

LAND = D.HERE.parent.parent / "plan02/live-integration-r1/land_selected.py"
LAND_SHA = "5ba8f49277f8779df9f06cd48f187b0652235ba1680aa7bf6cc044bfc341b072"


def load_io():
    D.need(D.pin(LAND) == LAND_SHA, "landing implementation drift")
    spec = importlib.util.spec_from_file_location("plan04_landing_io", LAND)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def documents():
    prepared = json.loads((D.HERE / "PREPARED.json").read_bytes())
    old = {}
    for name, pin in D.OLD.items():
        path = D.T / D.OLD_REL / name
        D.need(D.pin(path) == pin, "historical profile drift")
        old[name] = json.loads(path.read_bytes())
    selection = json.loads((D.HERE / "selection.json").read_bytes())
    D.need(D.pin(D.HERE / "selection.json") == prepared["selection_sha256"], "selection drift")
    docs = {}
    for name, pin in prepared["profile_files"].items():
        path = D.HERE / name
        D.need(D.pin(path) == pin, "staged profile changed: " + name)
        docs[name] = json.loads(path.read_bytes())
    D.need(docs == D.derive(old, selection, prepared["selection_sha256"]), "unexpected profile delta")
    # The native identity and all repair policy entries must remain unchanged.
    old_policy = old["runtime-compatibility-policy.json"]
    new_policy = docs["runtime-compatibility-policy.json"]
    for key in old_policy:
        if key not in ("current", "evidence"):
            D.need(old_policy[key] == new_policy[key], "compatibility policy changed: " + key)
    for key, value in old_policy["current"].items():
        if key not in ("source_manifest_path", "source_manifest_sha256"):
            D.need(new_policy["current"][key] == value, "native current identity changed: " + key)
    return prepared, docs


def install(receipt_path, receipt_sha):
    io = load_io()
    prepared, _ = documents()
    D.need(D.pin(receipt_path) == receipt_sha, "landing receipt changed")
    receipt = json.loads(receipt_path.read_bytes())
    D.need(receipt["status"] == "PASS" and receipt.get("original_error") is None
           and not receipt.get("rollback")
           and receipt["manifest_sha256"] == prepared["landing_manifest_sha256"]
           and set(receipt["applied"]) == set(prepared["assets"])
           and receipt["final_hashes"] == prepared["assets"], "incomplete tool landing")
    for name, digest in prepared["assets"].items():
        D.need(D.pin(D.R / name) == digest, "installed tool drift")
    target = D.T / D.NEW_REL
    io.plain_path(target, missing_leaf=True)
    D.need(not target.exists(), "retain existing profile successor")
    payload = {n: (D.HERE / n).read_bytes() for n in prepared["profile_files"]}
    target.mkdir(exist_ok=False)
    # Failure leaves its partial new target for diagnosis; never silently retry.
    for name, data in payload.items():
        io.exclusive_write(target / name, data)
    for name in ("runs", "completed-queries"):
        (target / name).mkdir()
    return {"status": "PASS_ADDITIVE_PROFILE_INSTALL", "target": str(target),
            "files": {name: D.pin(target / name) for name in payload}}


def check():
    D.need(sys.dont_write_bytecode, "use -B")
    D.need(Path(sys.executable).resolve() == (D.T / ".r44-env/Scripts/python.exe").resolve(),
           "selected Atlas interpreter required")
    prepared, docs = documents()
    target = D.T / D.NEW_REL
    for name, pin in prepared["profile_files"].items():
        D.need(D.pin(target / name) == pin, "installed profile drift")
    for name, pin in prepared["assets"].items():
        D.need(D.pin(D.R / name) == pin, "selected tool bytes differ")
    names = ("run_prepared_restart", "reopen_prepared_restart", "launch_monitored_interval",
             "launch_fresh_interval")
    D.need(not any(name in sys.modules for name in names), "fresh consumer-check process required")
    sys.path.insert(0, str(D.R))
    RUN, RO, LM, LF = [importlib.import_module(name) for name in names]
    for name, module in zip(names, (RUN, RO, LM, LF), strict=True):
        D.need(Path(module.__file__).resolve() == D.R / (name + ".py"), "caller shadow: " + name)
    D.need(RO.RUN is RUN and LF.RUN is RUN and LF.LM is LM and LF.SG is RUN.SG,
           "caller/helper identities differ")
    path = target / "restart-profile-live-r21.json"
    profile = RUN.RestartProfile.read(path, prepared["profile_files"][path.name])
    sources = RUN.RestartSources(profile)
    bound = LF._pinned_sources(profile)
    workspace, manifest = LM._pinned_manifest(profile.record())
    LM._bound_file(workspace, manifest, D.R / "launch_fresh_interval.py", LF._SELF_SHA, "selected LF")
    D.need(LF._SELF_SHA == prepared["assets"]["launch_fresh_interval.py"], "loaded LF identity differs")
    with sources.selected():
        native_transfer = importlib.import_module("native_transfer")
        D.need(Path(native_transfer.__file__).resolve() == D.R / "native_transfer.py",
               "native transfer repair shadowed")
        D.need(callable(native_transfer._historical_collar_fields), "native transfer repair lost")
        imported = sources.check_imported()
        D.need(RO._own_pin(sources) == D.R / "reopen_prepared_restart.py", "prepared reader not bound")
    command = RUN.command(profile, sys.executable, stop_before_advance=True)
    monitored, runner_path, _ = LM.load_runner(path, prepared["profile_files"][path.name])
    D.need(runner_path == D.R / "run_prepared_restart.py", "monitored caller changed")
    D.need(monitored.command(monitored.RestartProfile.read(path, prepared["profile_files"][path.name]),
                             sys.executable, stop_before_advance=True) == command,
           "monitored/direct caller command mismatch")
    D.need(not any(n == "atlas_tectonics" or n.startswith("atlas_tectonics.") for n in sys.modules),
           "native runtime unexpectedly imported")
    # Load actual selected comparison components through the pinned loader.
    tool = D.R / "n9-tools-r21/compare_arms_r21.py"
    spec = importlib.util.spec_from_file_location("plan04_selected_comparator", tool)
    comparator = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = comparator
    spec.loader.exec_module(comparator)
    loaded = {name: str(comparator.component(name).__file__) for name in comparator.COMPONENT_PINS}
    D.need(comparator.REPAIRS_COMPLETE is False, "premature comparison readiness release")
    return dict(status="PASS_SELECTED_TOOL_PROFILE_CALLER_CLOSURE", profile=str(path),
                profile_sha256=prepared["profile_files"][path.name],
                launcher_sha256=LF._SELF_SHA, bound_orchestration=bound,
                selected_components=loaded, imported_source_pins=imported,
                native_execution_identity=docs["runtime-compatibility-policy.json"]["current"]["execution_identity"],
                workload_launched=False, store_opened=False, native_runtime_imported=False,
                readiness_guards=False, positive_publish_reopen="DEFERRED",
                plan31_composition="UNAVAILABLE", scientific_acceptance=False, holds_released=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--landing-receipt", type=Path)
    parser.add_argument("--landing-receipt-sha256")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with args.out.open("x", encoding="utf8") as stream:
        try:
            if args.install:
                D.need(args.landing_receipt is not None and args.landing_receipt_sha256,
                       "exact landing receipt required")
                result = install(args.landing_receipt, args.landing_receipt_sha256)
            else:
                result = check()
        except Exception as error:
            result = dict(status="FAIL", error_type=type(error).__name__, error=str(error))
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "output": str(args.out)}))
    sys.exit(0 if result["status"].startswith("PASS_") else 1)
