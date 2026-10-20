"""Source-derived mandatory W/E provenance diagnostics, never numerical approval.

Inputs cross the existing independent source/reader proof boundary. No files
named by a receipt are loaded; no producer/runtime is imported. Present reader
schemas have no authenticated invocation observation, so every applicable slot
remains REVIEW even when its output bytes are equal.
"""
from __future__ import annotations
import ast
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re

SCHEMA = "atlas.private.plan04-field-provenance.r3"
RECEIPT_SCHEMA = "atlas.private.plan04-producer-receipt.r3"
SHA = re.compile("[0-9a-f]{64}\\Z")
MODULES = {"integration_wall_measures.py": "W", "integration_exterior_mesh.py": "E"}
KNOWN = {
    "W": {"d6b7d472246af0e8a9415b01465f035c0c860c7b358126fd1bba5c0025e671e0",
          "a7a7dc432a45439aa47d912fd6d1424be7f7c1081d03bd079aa075be6550ebef"},
    "E": {"d338238e1abe11db8e01a4b4ee91f99443727fb082f9d9cb6799344e82d445f4",
          "4b5b11c46d5602ab20ad46a2401ef3c34f64e281d86cdf9c1efd127e3f22840d"},
}
MESH = "atlas.source-bound-exterior-thermal-mesh.v1"
SLOTS = {
    "W.wall-normal": {
        "family": "W", "producer": "_pose_vector", "callers": ["_wall_leaf"],
        "quantity": "posed cone normal", "units": None, "norm": "l2", "components": 3,
        "output_field": None, "error_meaning": "Euclidean radius in the input vector's units",
    },
    "W.volume-plane-normal": {
        "family": "W", "producer": "_pose_vector", "callers": ["_pose_planes"],
        "quantity": "posed cone normal for volume planes", "units": None, "norm": "l2", "components": 3,
        "output_field": None, "error_meaning": "Euclidean radius in the input vector's units",
    },
    "W.inverse-grid-vertex": {
        "family": "W", "producer": "_pose_vector", "callers": ["_measure_walls"],
        "quantity": "inverse-posed grid vertex", "units": None, "norm": "l2", "components": 3,
        "output_field": None, "error_meaning": "Euclidean radius in the input vector's units",
    },
    "E.representative-quaternion": {
        "family": "E", "producer": "_representative_pose",
        "callers": ["build_exterior_mesh", "_build_exterior_mesh_record"],
        "quantity": "representative quaternion", "units": "1", "norm": "l2", "components": 4,
        "output_field": "representative_quaternion",
        "error_meaning": "stored operator bound is 4*internal quaternion error; not an accepted comparison radius",
    },
    "E.pose-operator-error": {
        "family": "E", "producer": "_representative_pose",
        "callers": ["build_exterior_mesh", "_build_exterior_mesh_record"],
        "quantity": "rotation operator error bound", "units": "1", "norm": "scalar", "components": 1,
        "output_field": "pose_operator_error_bound",
        "error_meaning": "rotation operator distance bound; not a generic allowance on this scalar's change",
    },
}


class ProvenanceError(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise ProvenanceError(message)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def decoded(raw):
    def bad_constant(value):
        raise ProvenanceError("nonfinite JSON constant: " + value)
    need(type(raw) is bytes, "exact raw bytes required")
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=bad_constant)
    except (ValueError, UnicodeError) as error:
        raise ProvenanceError("record JSON invalid: " + str(error)) from error


def source_paths(inventory):
    """Only relevant selected paths, without selecting a source on the caller's behalf."""
    need(isinstance(inventory, Mapping), "source inventory must be a mapping")
    return sorted(path for path in inventory if type(path) is str and
                  PurePosixPath(path.replace("\\", "/")).name in MODULES)


def compile_catalog(source_pins, source_bytes):
    """Check full known source bytes, then derive producer/call-site identities."""
    paths = source_paths(source_pins)
    need(isinstance(source_bytes, Mapping) and set(source_bytes) == set(paths),
         "provide exactly the relevant selected W/E source bytes")
    catalog = {}
    for path in paths:
        expected, raw = source_pins[path], source_bytes[path]
        need(type(expected) is str and SHA.fullmatch(expected), "invalid selected source pin")
        need(type(raw) is bytes and sha256(raw).hexdigest() == expected,
             "selected source bytes differ: " + path)
        family = MODULES[PurePosixPath(path.replace("\\", "/")).name]
        need(family not in catalog, "ambiguous selected producer family: " + family)
        row = {"path": path, "sha256": expected, "family": family,
               "known": expected in KNOWN[family], "producer": None, "call_sites": []}
        if row["known"]:
            tree = ast.parse(raw)
            producer = "_pose_vector" if family == "W" else "_representative_pose"
            definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                           and node.name == producer]
            need(len(definitions) == 1, "pinned source producer definition missing/ambiguous")
            node = definitions[0]
            row["producer"] = {"symbol": producer, "line": node.lineno, "end_line": node.end_lineno,
                               "ast_sha256": sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()}
            occurrences = {}
            for function in tree.body:
                if not isinstance(function, ast.FunctionDef):
                    continue
                occurrences[function.name] = occurrences.get(function.name, 0) + 1
                for call in ast.walk(function):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == producer:
                        row["call_sites"].append({
                            "caller": function.name, "definition_ordinal": occurrences[function.name],
                            "line": call.lineno, "end_line": call.end_lineno,
                            "ast_sha256": sha256(ast.dump(call, include_attributes=False).encode()).hexdigest(),
                        })
            expected_callers = {"_wall_leaf", "_pose_planes", "_measure_walls"} if family == "W" else \
                {"build_exterior_mesh", "_build_exterior_mesh_record"}
            need({item["caller"] for item in row["call_sites"]} == expected_callers and
                 len(row["call_sites"]) == len(expected_callers), "pinned producer call sites differ")
        catalog[family] = row
    return catalog


def mandatory_slots(catalogs):
    """All known W/E routes selected in either arm; invocation absence is not inferred."""
    families = {family for catalog in catalogs.values() for family in catalog}
    return [name for name, slot in SLOTS.items() if slot["family"] in families]


class Context:
    """Verified-boundary inputs only. Raw record identity is checked again here.

    manifests/source_pins are from authenticated arm source inventories.
    source_bytes contains only source_paths(inventory), with exact selected bytes.
    records[arm][kind] = {'identity': independent reader target SHA, 'raw': bytes}.
    reader_pairs is the existing independently re-derived cross-arm SHA pairing.
    No observation sidecar, contract assertions or purported proof file is accepted.
    """
    def __init__(self, manifests, source_pins, source_bytes, records, reader_pairs):
        for value in (manifests, source_pins, source_bytes, records):
            need(isinstance(value, Mapping) and set(value) == {"before", "after"}, "complete arm pair required")
        need(all(type(pin) is str and SHA.fullmatch(pin) for pin in manifests.values()),
             "invalid authenticated source manifest identity")
        self.manifests = dict(manifests)
        self.catalogs = {arm: compile_catalog(source_pins[arm], source_bytes[arm]) for arm in manifests}
        self.records = {}
        for arm, mapping in records.items():
            need(isinstance(mapping, Mapping), "reader records must be a mapping")
            self.records[arm] = {}
            for kind, item in mapping.items():
                need(type(kind) is str and kind and type(item) is dict and
                     set(item) == {"identity", "raw"}, "reader record binding malformed")
                pin, raw = item["identity"], item["raw"]
                need(type(pin) is str and SHA.fullmatch(pin) and type(raw) is bytes and
                     sha256(raw).hexdigest() == pin, "dump record differs from independent reader target")
                # Keep only compact source-field references, not raw bytes or
                # large cell/face/trajectory records. Lazy Mapping is supported.
                record = decoded(raw)
                summary = {"identity": pin, "is_exterior": False}
                if type(record) is dict and record.get("schema") == MESH and \
                        record.get("physical_geometry_family") != "differential-plate-component-partition-v1":
                    fields = {}
                    for field in ("representative_quaternion", "pose_operator_error_bound"):
                        if field in record:
                            values = record[field] if field == "representative_quaternion" else [record[field]]
                            need(type(values) is list and len(values) == (4 if field == "representative_quaternion" else 1),
                                 "source-defined quantity shape differs: " + field)
                            for value in values:
                                need(type(value) is list and len(value) == 2 and
                                     all(type(q) is str and re.fullmatch(r"-?0x[0-9a-fA-F]+", q)
                                         for q in value) and int(value[1], 16) > 0,
                                     "source-defined exact encoding differs: " + field)
                            fields[field] = digest(record[field])
                    history, segments = record.get("trajectory_id"), record.get("trajectory_segments")
                    history_ok = type(history) is str and SHA.fullmatch(history) and type(segments) is list
                    summary.update(is_exterior=True, fields=fields,
                                   history={"trajectory_id": history if history_ok else None,
                                            "segments_sha256": digest(segments) if history_ok else None})
                    segments = values = value = None
                self.records[arm][kind] = summary
                del raw, record, item
        self.reader_pairs = set()
        for pair in reader_pairs:
            need(type(pair) in (list, tuple) and len(pair) == 2 and
                 all(type(pin) is str and SHA.fullmatch(pin) for pin in pair),
                 "independent reader identity pair malformed")
            self.reader_pairs.add(tuple(pair))
        self.slots = mandatory_slots(self.catalogs)


def emit_receipt(slot_id, context):
    """Emit complete known bindings and explicit missing bindings; never self-certify."""
    need(isinstance(context, Context), "verified-boundary Context required")
    need(slot_id in context.slots, "slot is not mandatory for these selected sources")
    slot = SLOTS[slot_id]
    arms, issues = {}, ["NO_AUTHENTICATED_PRODUCER_INVOCATION_CONTEXT",
                       "NO_SOURCE_PROVED_COMPARISON_BOUND"]
    for arm in ("before", "after"):
        source = context.catalogs[arm].get(slot["family"])
        outputs = []
        if source is None:
            issues.append(arm + ":SELECTED_PRODUCER_ABSENT")
        elif not source["known"]:
            issues.append(arm + ":UNREVIEWED_SELECTED_PRODUCER")
        elif slot["family"] == "E":
            for kind, item in sorted(context.records[arm].items()):
                if not item["is_exterior"]:
                    continue
                field = slot["output_field"]
                if field not in item["fields"]:
                    issues.append(arm + ":" + kind + ":MANDATORY_OUTPUT_FIELD_MISSING")
                    continue
                if item["history"]["trajectory_id"] is None:
                    issues.append(arm + ":" + kind + ":SOURCE_HISTORY_CONTEXT_MISSING")
                error = item["fields"].get("pose_operator_error_bound")
                if error is None:
                    issues.append(arm + ":" + kind + ":OPERATOR_ERROR_IDENTITY_MISSING")
                outputs.append({
                    "record_kind": kind, "record_identity": item["identity"],
                    "schema": MESH, "path": [kind, field], "value_sha256": item["fields"][field],
                    "representation": "source-exact-rational",
                    "projection": "source encoding only; no binary64 projection proved",
                    "history": deepcopy(item["history"]),
                    "error": {"path": [kind, "pose_operator_error_bound"],
                              "value_sha256": error,
                              "meaning": "rotation-operator bound = 4*internal quaternion error"},
                })
            if not outputs:
                issues.append(arm + ":NO_READER_BOUND_E_OUTPUT")
        else:
            issues.append(arm + ":W_INTERMEDIATE_OUTPUT_SCHEMA_AND_CALLER_UNITS_UNBOUND")
        arms[arm] = {
            "source": deepcopy(source),
            "call_sites": [deepcopy(row) for row in source["call_sites"]
                           if row["caller"] in slot["callers"]] if source and source["known"] else [],
            "observed_call_site": None, "refinement_level": None,
            "outputs": outputs,
        }
    correspondence = []
    old = {row["record_kind"]: row for row in arms["before"]["outputs"]}
    new = {row["record_kind"]: row for row in arms["after"]["outputs"]}
    for kind in sorted(set(old) | set(new)):
        a, b = old.get(kind), new.get(kind)
        if a and b and (a["record_identity"], b["record_identity"]) in context.reader_pairs:
            correspondence.append({
                "record_kind": kind, "before_record_identity": a["record_identity"],
                "after_record_identity": b["record_identity"],
                "before_quantity_identity": a["record_identity"] + "/" + slot["output_field"],
                "after_quantity_identity": b["record_identity"] + "/" + slot["output_field"],
                "scope": "reader-proved record pair and fixed source field; no invocation/row/projection proof",
            })
        else:
            issues.append(kind + ":INDEPENDENT_RECORD_CORRESPONDENCE_MISSING")
    return {
        "schema": RECEIPT_SCHEMA, "slot": slot_id, "mandatory": True,
        "composition": deepcopy(context.manifests),
        "quantity": {key: deepcopy(slot[key]) for key in
                     ("quantity", "units", "norm", "components", "error_meaning")},
        "arms": arms, "correspondence": correspondence,
        "applicable_radius": None, "comparison_bound": None,
        "verdict": "REVIEW", "issues": sorted(set(issues)),
        "authority": "diagnostic provenance only; no numerical allowance or guard release",
    }


def validate_receipt(receipt, context):
    """Re-derive every byte-independent field from verified inputs, never from receipt assertions."""
    if type(receipt) is not dict or type(receipt.get("slot")) is not str:
        return {"verdict": "FAIL", "code": "MALFORMED_PRODUCER_RECEIPT"}
    try:
        expected = emit_receipt(receipt["slot"], context)
    except ProvenanceError as error:
        return {"verdict": "FAIL", "code": "UNBOUND_PRODUCER_RECEIPT", "reason": str(error)}
    if receipt != expected:
        return {"verdict": "FAIL", "code": "PRODUCER_RECEIPT_CONTRADICTS_INDEPENDENT_INPUTS"}
    return {"verdict": "REVIEW", "code": "PROVENANCE_BOUND_NUMERICAL_CONTEXT_UNRESOLVED",
            "receipt_sha256": digest(expected), "issues": expected["issues"]}


def assess_records(manifests, source_pins, source_bytes, records, reader_pairs):
    """Comparator entry point: mandatory results even for byte-equal dumped records."""
    try:
        context = Context(manifests, source_pins, source_bytes, records, reader_pairs)
        receipts = [emit_receipt(slot, context) for slot in context.slots]
        return {
            "schema": SCHEMA, "verdict": "REVIEW" if receipts else "NOT_APPLICABLE",
            "scope": "known W/E producer routes only; no exhaustive Pressure/Geometry/Heat contract",
            "mandatory_slots": context.slots,
            "receipts": receipts, "receipt_sha256": [digest(row) for row in receipts],
            "issues": [row["slot"] + ":" + issue for row in receipts for issue in row["issues"]],
            "remaining_dependency": "Actual selected producer invocation/schema, caller units, norm/projection/"
                                    "level/history/radius applicability and independently proved correspondence; "
                                    "Heat requires its own propagated bound or independent verification.",
        }
    except (ProvenanceError, SyntaxError, TypeError, ValueError, KeyError) as error:
        return {"schema": SCHEMA, "verdict": "FAIL", "code": "PROVENANCE_INPUT_INTEGRITY",
                "reason": str(error), "issues": [str(error)],
                "mandatory_slots": [], "receipts": [], "receipt_sha256": []}
