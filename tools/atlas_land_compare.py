"""Run the reviewed capture and comparison stages."""

from collections import Counter
from hashlib import sha256
import os
from pathlib import Path
from types import ModuleType

from atlas_land import Incomplete, canonical, decode, digest, require, save

CAPTURED = "CAPTURED_AFTER_CERTIFICATION_BEFORE_END"
CAPTURE_SCHEMA = "atlas.private.end-preissue-capture.v1"


def load_source(round_, binding):
    path = round_.path(binding["path"])
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == binding["sha256"], f"Source fingerprint differs for {path}")
    module = ModuleType(path.stem)
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec", dont_inherit=True), vars(module))
    return module


def producer_notice(evidence, field, path):
    for line in Path(evidence["stdout"]).read_bytes().splitlines():
        if not line.startswith(b"{"):
            continue
        record = decode(line)
        if record.get(field) and Path(record[field]).resolve() == path:
            return {"path": str(path), "sha256": record["sha256"]}
    raise Incomplete(f"Producer omitted its receipt for {path}", **evidence)


def produce(round_, route, work, name):
    run = route["capture"]
    marker = round_.local("capture-stages", run)
    home = round_.path(run["home"])
    attempt = home / "attempt-r1"
    receipt_path = attempt / "run-interval/end-capture-receipt.json"
    root_path = home / "end-root-receipt.json"
    operands_dir = round_.path(run["operands_output"])
    require(home != operands_dir and not operands_dir.is_relative_to(home), "Capture and operands destinations overlap")
    checkpoint = decode(marker.read_bytes()) if marker.is_file() else {}
    evidence = dict(checkpoint.get("stages", {}))
    runtime = round_.path(run["runtime"])
    helper_python = round_.path(run["helper_python"])
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith(("PYTHON", "ATLAS_"))}
    env.update(PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1", ATLAS_HEAT_WORKERS_STRICT="1")
    receipt = checkpoint.get("receipt")
    if receipt is None:
        marker_capture = round_.local("capture-receipt", run)
        if marker_capture.is_file():
            receipt = decode(marker_capture.read_bytes())
        else:
            heavy = (helper_python, "-B", round_.checked(run["capture_guard"]),
                     "--memory-mib", run["capture_memory_mib"], "--seconds", run["capture_seconds"], "--")
            config = ("--config", round_.path(run["config"]["path"]), "--config-sha256", run["config"]["sha256"])
            require(config[1].is_relative_to(home), "Capture config is outside the bound home")
            root = run.get("retained_root")
            marker_root = round_.local("capture-root", run)
            if marker_root.is_file():
                root = decode(marker_root.read_bytes())
            entry = round_.checked(run["interval_entry"])
            interval = receipt_path.parent
            require(not interval.exists(), f"Capture destination is occupied: {interval}")
            if root is None:
                require(not root_path.exists(), f"Existing root needs its issued binding: {root_path}")
                prefix = round_.checked(run["prefix_entry"])
                evidence["root"] = round_.launch(f"{name}-root", (*heavy, runtime, "-B", "-I", prefix, "prefix", *config),
                                                 work, work, cwd=home, env=env)
                root = producer_notice(evidence["root"], "receipt", root_path)
                save(marker_root, root)
            require(round_.path(root["path"]) == root_path, "Selected root is from a different capture home")
            evidence["interval"] = round_.launch(
                f"{name}-interval", (*heavy, runtime, "-B", "-s", "-P", entry, *config, "--root-sha256", root["sha256"]),
                work, work, cwd=home, env=env,
            )
            receipt = producer_notice(evidence["interval"], "receipt", receipt_path)
            save(marker_capture, receipt)
    operands = checkpoint.get("operands")
    if operands is None:
        require(not operands_dir.exists(), f"Operands destination is occupied: {operands_dir}")
        marker_kit = round_.local("capture-operands-kit", run)
        if marker_kit.is_file():
            kit_ref = decode(marker_kit.read_bytes())
            kit_path = round_.path(kit_ref["path"])
            kit_bytes = kit_path.read_bytes()
            require(sha256(kit_bytes).hexdigest() == kit_ref["sha256"], f"Fingerprint differs for {kit_path}")
            kit = decode(kit_bytes)
        else:
            kit = work / f"{name}-operands-kit"
            maker = round_.checked(run["operands_maker"])
            evidence["kit"] = round_.launch(f"{name}-kit", (helper_python, "-B", "-I", maker, home, kit),
                                           work, work, env=env)
            kit_path = kit / "OPERANDS-KIT.json"
            kit_bytes = kit_path.read_bytes()
            kit = decode(kit_bytes)
            save(marker_kit, {"path": str(kit_path), "sha256": sha256(kit_bytes).hexdigest()})
        require(Path(kit["home"]).resolve() == home and kit["receipt_sha256"] == receipt["sha256"],
                "Operands kit does not bind the selected capture")
        reconstruct = round_.checked({"path": str(kit_path.with_name("reconstruct_operands_gp.py")),
                                      "sha256": kit["maker"]["output_sha256"]})
        guard = round_.checked(run["operands_guard"])
        operands_dir.mkdir(parents=True)
        target = operands_dir / "operands.json"
        evidence["operands"] = round_.launch(
            f"{name}-operands", (runtime, "-B", guard, "--memory-mib", run["operands_memory_mib"],
                                 "--seconds", run["operands_seconds"], "--", runtime, "-B", "-s", "-P",
                                 reconstruct, target), work, work, cwd=home, env=env,
        )
        operands = producer_notice(evidence["operands"], "output", target)
        save(marker, {"receipt": receipt, "operands": operands, "stages": evidence})
    return receipt, operands, evidence


def end_arm(round_, contract, arm, temp, name):
    if "capture" in arm:
        receipt_ref, operands_ref, stages = produce(round_, arm, temp, name)
    else:
        receipt_ref, operands_ref, stages = arm["receipt"], arm["operands"], {}
    receipt = round_.json(receipt_ref)
    require((receipt["schema"], receipt["status"]) == (CAPTURE_SCHEMA, CAPTURED), "Invalid END receipt")
    for key in ("package_tree", "config_sha256", "profile_sha256"):
        require(arm["identity"][key] == receipt[key], f"{name} capture disagrees with {key}")
    lineage = {key: receipt[key] for key in ("package_tree", "config_sha256", "profile_sha256")}
    if arm.get("profile"):
        profile = round_.json(arm["profile"])
        require(arm["profile"]["sha256"] == receipt["profile_sha256"], "Receipt profile differs")
        if "qualification_status" in profile:
            lineage["qualification_status"] = profile["qualification_status"]
        else:  # a reference arm built before landing 1 keeps it in its source list
            installed_ref = profile["source_manifest"]
            manifest = round_.json({**installed_ref, "path": str(Path(profile["workspace"]) / installed_ref["path"])})
            installed = manifest["installed_binding"]
            require(installed["native_tree_sha256"] == receipt["package_tree"], "Receipt native tree differs")
            lineage["qualification_status"] = installed["qualification_status"]

    directory = round_.path(receipt_ref["path"]).parent
    graph_record = receipt["graph"]
    graph = contract.artifact(directory, graph_record, "end-closed-graph.json.gz", verify_pin=False)
    contract.artifact(directory, receipt["proposal"], "differential-proposal-01.json")
    if "decoded_graph" in arm:
        graph_path = round_.checked(arm["decoded_graph"])
        require(digest(graph) == graph_record["sha256"], f"{name} compressed graph digest differs")
        full_sha, size = arm["decoded_graph"]["sha256"], graph_path.stat().st_size
    else:
        graph_path = temp / f"{name}-graph.json"
        full_sha, size = contract.decode_graph(graph, graph_path, graph_record)
        if "decoded_sha256" in arm:
            require(full_sha == arm["decoded_sha256"], f"{name} decoded graph digest differs")
    require(size == graph_record["canonical_bytes"], f"{name} decoded graph size differs")
    live = receipt["live"]
    require(graph_record["canonical_sha256"] == live["graph_id"], f"{name} issued graph ID disagrees")
    values = round_.json(operands_ref)
    require(values["schema"] == "q363.reconstructed-operands.v1", "Wrong operands schema")
    for key, expected in (("graph_sha256", live["graph_id"]), ("profile_sha256", receipt["profile_sha256"]),
                          ("proposal_sha256", receipt["proposal"]["sha256"])):
        require(values[key] == expected, f"{name} operands disagree with {key}")
    partition, supports = values["partition"], values["supports"]
    require(type(partition) is dict and type(supports) is list, f"{name} partition or supports are invalid")
    require(len(supports) == live["support_count"] == len(partition["support_ids"]), f"{name} support count differs")
    require(sha256(canonical(partition["support_ids"])).hexdigest() == live["support_order_sha256"],
            f"{name} support order differs")
    evidence = {**lineage, "receipt": receipt_ref, "operands": operands_ref, "stages": stages,
                "graph": {"path": str(graph_path), "sha256": full_sha, "bytes": size,
                          "compressed_sha256": graph_record["sha256"], "issued_id": live["graph_id"]}}
    return evidence, contract.identifiers(receipt), partition, supports


def compare_end(round_, settings, work):
    extraction = load_source(round_, settings["extraction"])
    parity = load_source(round_, settings["comparator"])
    left, left_ids, left_partition, left_supports = end_arm(round_, extraction, settings["reference"], work, "reference")
    right, right_ids, right_partition, right_supports = end_arm(round_, extraction, settings["candidate"], work, "candidate")
    differences = {}
    for label, a, b in (("identifiers", left_ids, right_ids), ("partition", left_partition, right_partition),
                        ("supports", left_supports, right_supports)):
        found = parity.first_difference(a, b, label)
        if found is not None:
            differences[label] = found
    if left["graph"]["sha256"] != right["graph"]["sha256"]:
        a, b = (decode(Path(x["graph"]["path"]).read_bytes()) for x in (left, right))
        differences["graph"] = parity.first_difference(a, b, "graph") or "graph: full decoded bytes differ"
    return {"exit": int(bool(differences)), "differences": differences, "reference": left, "candidate": right,
            "comparator": settings["comparator"], "first_difference": next(iter(differences.values()), None)}


def resolved_exports(round_, settings, work):
    exports = []
    for name in ("reference", "candidate"):
        arm = settings[name]
        if "export_index" in arm:
            ref = arm["export_index"]
            index = round_.path(ref["path"])
        else:
            store = arm["export"]
            complete = round_.local("export", store)
            if complete.is_file():
                ref = decode(complete.read_bytes())
                index = round_.path(ref["path"])
            else:
                target = work / f"{name}-export"
                if "legacy_binding" in store:
                    exporter = Path(__file__).with_name("atlas_land_export.py")
                    switches = ("--settings", round_.checked(store["legacy_binding"]))
                else:
                    exporter = round_.checked(store["producer"])
                    switches = ()
                prior = store.get("decoded_export")
                args = ("mesh", round_.path(prior)) if prior else ("complete",)
                round_.launch(f"{name}-export", (round_.path(store["python"]), "-B", "-I", exporter,
                                                *switches, *args, round_.path(store["home"]), target), work, work)
                index = target / "export.json"
                ref = {"path": str(index), "sha256": digest(index)}
                save(complete, ref)
        exports.append({"path": str(index), "sha256": ref["sha256"], "restart": arm.get("restart")})
    return exports


def compare_exports(round_, settings, work):
    exports = resolved_exports(round_, settings, work)
    destination = work / "decoded-differences.json"
    binding = work / "decoded-inputs.json"
    save(binding, {"exports": exports, "decoder": settings["decoder"]})
    comparer = round_.checked(settings["comparator"])
    evidence = round_.launch("decoded-compare", (round_.path(settings["python"]), "-B", "-I", comparer, "compare",
                                                binding, destination), work, work, allowed=(0, 1))
    raw = destination.read_bytes()
    report = decode(raw)
    require((report["exit"], report["verdict"]) == (evidence["child_exit"], "PASS" if evidence["child_exit"] == 0 else "FAIL"),
            "Decoded comparer exit and report disagree")
    for expected, measured in zip(exports, report["exports"], strict=True):
        require(expected["path"] == measured["path"] and expected["sha256"] == measured["sha256"]
                and (expected["restart"] is None or expected["restart"] == measured["restart"]),
                "Decoded comparer did not bind the requested exports")
    return {"exit": report["exit"], "report": {"path": str(destination), "sha256": sha256(raw).hexdigest()},
            "exports": report["exports"], "comparator": settings["comparator"], "stage": evidence}, report


def row_key(row):
    return tuple(row[key] for key in ("file", "path", "a", "b"))


def disposition(round_, raw, report, approval):
    rows = report["unexplained_first"]
    unresolved = report["n_unexplained"]
    unpaired = report["unpaired"]
    unmatched = unpaired["not_decoded_identities_differ"] or any(
        unpaired[group][name] for group in ("restart", "records") for name in ("a", "b")
    )
    require(raw["exit"] == int(bool(unresolved or unmatched)), "Decoded report does not account for its exit")
    known = dict(report["known_counts"])
    first = rows[0] if rows else next((group for group in ("restart", "records")
                                      if any(unpaired[group].values())),
                                     "undecoded identities" if unmatched else None)
    result = {**raw, "known_counts": known, "n_unexplained": unresolved, "unpaired": unpaired,
              "float_values_differ": report["float_values_differ"], "first_difference": first}
    if approval is None:
        return result
    policy = round_.json(approval)
    require(policy["kind"] == "historical-e24" and policy["exports"] == raw["exports"]
            and policy["comparator"] == raw["comparator"], "Historical approval does not bind this replay")
    original = round_.json(policy["strict"])
    accepted = round_.json(policy["accepted"])
    eligible = Counter(row_key(row) for row in accepted["known_all"] if row["kind"] == "declared_split")
    require(original["n_unexplained"] == 9 and accepted["n_unexplained"] == 0
            and eligible.total() == 9 and eligible == Counter(map(row_key, original["unexplained_first"])),
            "The historical verdict does not account for the exact nine rows")
    changed = []
    remaining = []
    for row in rows:
        key = row_key(row)
        if row["kind"] == "digest_not_one_to_one" and eligible[key]:
            eligible[key] -= 1
            changed.append(row)
        else:
            remaining.append(row)
    known["declared_split"] = len(changed)
    unresolved -= len(changed)
    complete = len(rows) == report["n_unexplained"] or unresolved > 0
    require(complete, "Truncated strict report cannot establish the historical disposition")
    exit_code = int(bool(unresolved or unmatched or len(changed) != 9))
    return {**result, "exit": exit_code, "strict_exit": raw["exit"], "n_unexplained": unresolved,
            "first_difference": remaining[0] if remaining else (first if unresolved or unmatched else None),
            "declared_split": changed, "historical_approval": approval, "unexplained_rows": remaining}


def compare(round_):
    settings = round_.config["comparison"]
    mode = settings["kind"]
    require(mode != "end-capture" or "historical_approval" not in settings,
            "historical_approval applies only to decoded-exports")
    raw_scope = {key: value for key, value in settings.items() if key != "historical_approval"}
    marker = round_.local("comparison-raw", raw_scope)
    if marker.is_file():
        strict = decode(marker.read_bytes())
        report = round_.json(strict["report"]) if mode == "decoded-exports" else None
    else:
        work = round_.stage("compare")
        if mode == "decoded-exports":
            strict, report = compare_exports(round_, settings, work)
        else:
            require(mode == "end-capture", f"Unknown comparison contract: {mode}")
            strict = compare_end(round_, settings, work)
            report = None
        save(marker, strict)
    approval = settings.get("historical_approval")
    result = disposition(round_, strict, report, approval) if report is not None else strict
    result = {**result, "status": "PASS" if result["exit"] == 0 else "FAIL", "strict_result": str(marker)}
    output = round_.local("comparison-result", settings)
    ref = {"path": str(output), "sha256": digest(output)} if output.is_file() else save(output, result)
    return {**result, "result": ref}
