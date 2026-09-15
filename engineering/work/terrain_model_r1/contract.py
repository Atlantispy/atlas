"""Read-only terrain-design intake. Never authorises or executes generation.

Validation here checks declared binding metadata, NOT the scientific truth of
sources, spatial coverage, ownership approvals or physical acceptance. Gate B
therefore remains INCOMPLETE even for a structurally complete recipe.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import stat
from pathlib import Path

SCHEMA = "diadem.terrain.recipe-intake.v1"
PACKAGE_SCHEMA = "diadem.physical.generator-terrain-design.v1"
PACKAGE_SHA256 = "0b30f42deea8c4e9f8fc8066dd9c837fb49cf2a63ec777ae0511569886c7f70e"
FAMILIES = {
    "L01": "Structural mountains and belts",
    "L02": "Soil-mantled hills, weathered uplands, bedrock slopes and failure",
    "L03": "Fluvial valleys, widening, fans and erosional/depositional lowlands",
    "L04": "Glacial and periglacial terrain",
    "L05": "Carbonate/evaporite karst and subsurface exchange",
    "L06": "Volcanic and other constructive terrain",
    "L07": "Lakes, enclosed basins, wetlands and organic accretion",
    "L08": "Coasts, deltas, estuaries and shore-connected relief",
    "L09": "Arid, episodic-drainage and aeolian terrain",
    "L10": "Mixed histories and process transitions",
    "L11": "Submerged lake/sea-bed relief",
}
GROUPS = {"frame", "structure", "history", "forcing", "base_levels", "constraints", "numerics"}
TEST_IDS = {f"T{i:02d}" for i in range(1, 13)} | {f"W{i:02d}" for i in range(1, 13)} | {f"CF{i:02d}" for i in range(1, 9)}
SHA = re.compile(r"^[0-9a-f]{64}$")


def load_json(path: Path, *, max_bytes=1024 * 1024):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"duplicate JSON key: {key}")
            out[key] = value
        return out
    def constant(value):
        raise ValueError(f"non-finite JSON constant: {value}")
    path = _regular(path)
    with path.open("rb") as source:
        data = source.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("JSON input exceeds bounded metadata read limit")
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant)


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().upper() not in {"UNKNOWN", "TBD", "INCOMPLETE"}


def _regular(path):
    """Reject symlink/reparse traversal; do not follow arbitrary indirections."""
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"linked/reparse path: {path}")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"not a regular file: {path}")
    return path.resolve(strict=True)


def file_pin(path, *, max_bytes=16 * 1024 * 1024):
    path = _regular(path)
    before = path.stat()
    if before.st_size > max_bytes:
        raise ValueError(f"read limit exceeded: {path}")
    with path.open("rb") as source:
        data = source.read(max_bytes + 1)
    after = path.stat()
    signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if len(data) > max_bytes or signature(before) != signature(after):
        raise ValueError(f"source changed during read: {path}")
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def verify_package(manifest_path: Path, expected_sha256: str = PACKAGE_SHA256):
    issues, verified = [], []
    try:
        if not isinstance(expected_sha256, str) or not SHA.fullmatch(expected_sha256):
            raise ValueError("invalid expected manifest hash")
        manifest_pin = file_pin(manifest_path, max_bytes=24576)
        if manifest_pin["sha256"] != expected_sha256:
            raise ValueError("package manifest hash mismatch")
        manifest = load_json(manifest_path)
        if manifest.get("schema") != PACKAGE_SCHEMA:
            raise ValueError("unsupported package schema")
        files, specialists = manifest.get("files"), manifest.get("specialist_sources")
        if not isinstance(files, list) or not isinstance(specialists, list) or not files or len(files) + len(specialists) > 16:
            raise ValueError("invalid bounded package inventory")
        seen = set()
        for item in files + specialists:
            raw_path = item["path"]
            path = Path(raw_path)
            if not path.is_absolute():
                path = Path(manifest_path).parent / path
            pin = file_pin(path, max_bytes=24576)
            key = pin["path"].casefold()
            if key in seen:
                raise ValueError("duplicate package file")
            seen.add(key)
            if type(item.get("bytes")) is not int or not isinstance(item.get("sha256"), str) or not SHA.fullmatch(item["sha256"]):
                raise ValueError(f"invalid package pin: {path.name}")
            if pin["bytes"] != item["bytes"] or pin["sha256"] != item["sha256"]:
                raise ValueError(f"package file mismatch: {path.name}")
            verified.append(pin)
        for pin in verified:
            if file_pin(pin["path"], max_bytes=24576) != pin:
                raise ValueError("package member changed during verification")
        # A second manifest check prevents mixed metadata if it changed mid-read.
        if file_pin(manifest_path, max_bytes=24576) != manifest_pin:
            raise ValueError("package manifest changed during verification")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        issues.append({"path": "package", "code": "PACKAGE_INTEGRITY", "owner": "Engineering", "message": str(error)})
    return {"status": "FAIL" if issues else "PASS", "issues": issues, "verified": verified,
            "source_status": "WORKING NON-CANON", "generation_authorised": False}


def _validate_recipe(recipe: dict):
    issues = []
    def add(path, code, owner, message, severity="INCOMPLETE"):
        issues.append(dict(path=str(path), code=str(code), owner=owner if _text(owner) else "Engineering",
                           message=message if isinstance(message, str) else "Malformed diagnostic binding.", severity=severity))
    def need_text(value, path, owner="Engineering"):
        if not _text(value):
            add(path, "MISSING_BINDING", owner, "A non-placeholder binding is required.")
    def mapping(value, path):
        if not isinstance(value, dict):
            add(path, "TYPE", "Engineering", "Expected an object.", "FAIL")
            return {}
        return value
    def rows(value, path):
        if not isinstance(value, list):
            add(path, "TYPE", "Engineering", "Expected a list.", "FAIL")
            return []
        out, seen = [], set()
        for index, raw in enumerate(value):
            row = mapping(raw, f"{path}[{index}]")
            identifier = row.get("id")
            if not _text(identifier):
                add(path, "MISSING_ID", "Engineering", "Every row needs a stable ID.", "FAIL")
            elif identifier in seen:
                add(path, "DUPLICATE_ID", "Engineering", f"Duplicate ID: {identifier}", "FAIL")
            else:
                seen.add(identifier)
            out.append(row)
        return out
    def finite(value, path):
        if isinstance(value, float) and not math.isfinite(value):
            add(path, "NONFINITE", "Engineering", "NaN/infinity are not valid bindings.", "FAIL")
        elif isinstance(value, dict):
            for k, v in value.items():
                finite(v, f"{path}.{k}")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                finite(v, f"{path}[{i}]")
    def positive(value, path, *, integer=False):
        if value is None:
            add(path, "MISSING_NUMBER", "Engineering", "A positive numerical value is required.")
        elif not _number(value) or value <= 0 or (integer and type(value) is not int):
            add(path, "INVALID_NUMBER", "Engineering", "Expected a finite positive number of the declared type.", "FAIL")
    def record_state(row, path, owner):
        state = row.get("state")
        if state not in {"BOUND", "UNKNOWN", "CONFLICT", "INACTIVE"}:
            add(path, "INVALID_STATE", owner, "Expected BOUND, UNKNOWN, CONFLICT or INACTIVE.", "FAIL")
        elif state in {"UNKNOWN", "CONFLICT"}:
            add(path, state, owner, row.get("reason") or "An explicit owner binding is required.", "FAIL" if state == "CONFLICT" else "INCOMPLETE")
        need_text(row.get("owner"), path + ".owner", owner)
        if state in {"BOUND", "INACTIVE"}:
            need_text(row.get("reason"), path + ".reason", owner)
            refs(row.get("source_ids"), path + ".source_ids", owner)
        return state
    def refs(value, path, owner):
        if not isinstance(value, list) or not value:
            add(path, "MISSING_EVIDENCE", owner, "At least one bound source ID is required.")
        else:
            for identifier in value:
                if not isinstance(identifier, str) or identifier not in source_ids:
                    add(path, "UNKNOWN_SOURCE", owner, f"Unbound source ID: {identifier!r}", "FAIL")

    recipe = mapping(recipe, "recipe")
    finite(recipe, "recipe")
    if recipe.get("schema") != SCHEMA:
        add("schema", "SCHEMA", "Engineering", "Unsupported recipe-intake version.", "FAIL")
    if recipe.get("world_id") != "diadem" or recipe.get("world_state") != "fixed_snapshot":
        add("world_id", "SCOPE", "Engineering", "Only the Diadem fixed-snapshot contract is in scope.", "FAIL")
    if recipe.get("source_status") != "WORKING NON-CANON":
        add("source_status", "SCOPE", "Engineering", "This new candidate recipe is WORKING NON-CANON.", "FAIL")
    need_text(recipe.get("snapshot_id"), "snapshot_id", "GEO")
    if recipe.get("mode") not in {"process_constrained_reconstruction", "process_evolution"}:
        add("mode", "MODE", "Engineering", "An explicit supported construction mode is required.")

    sources = rows(recipe.get("sources"), "sources")
    source_ids = {row["id"] for row in sources if _text(row.get("id"))}
    for row in sources:
        path = "sources." + str(row.get("id"))
        for field in ("path", "source_status", "owner", "role"):
            need_text(row.get(field), path + "." + field)
        if not isinstance(row.get("sha256"), str) or not SHA.fullmatch(row["sha256"]):
            add(path, "SOURCE_HASH", "Engineering", "Source hash must be lowercase SHA-256.", "FAIL")
        if type(row.get("bytes")) is not int or row["bytes"] < 0:
            add(path, "SOURCE_SIZE", "Engineering", "Source bytes must be a non-negative integer.", "FAIL")

    frame = mapping(recipe.get("frame"), "frame")
    for field in ("id", "crs", "origin", "x_direction", "y_direction", "horizontal_datum", "vertical_datum", "validity", "boundaries"):
        need_text(frame.get(field), "frame." + field, "Physical")
    if frame.get("horizontal_unit") != "m" or frame.get("vertical_unit") != "m":
        add("frame.units", "UNITS", "Engineering", "Normalised terrain frame must use metres; other source units need explicit adapters.", "FAIL")
    if frame.get("x_direction") is not None and frame.get("x_direction") not in ("east", "west"):
        add("frame.x_direction", "AXES", "Engineering", "Normalised x must be east or west; other frames need a registered adapter.", "FAIL")
    if frame.get("y_direction") is not None and frame.get("y_direction") not in ("north", "south"):
        add("frame.y_direction", "AXES", "Engineering", "Normalised y must be north or south, orthogonal to x.", "FAIL")
    for field in ("spacing_m", "effective_support_m"):
        positive(frame.get(field), "frame." + field)
    refs(frame.get("source_ids"), "frame.source_ids", "Physical")

    groups = rows(recipe.get("input_groups"), "input_groups")
    for missing in sorted(GROUPS - {r.get("id") for r in groups if _text(r.get("id"))}):
        add("input_groups", "MISSING_GROUP", "Engineering", f"Required group missing: {missing}")
    for row in groups:
        record_state(row, "input_groups." + str(row.get("id")), row.get("owner") or "GEO")
        if row.get("state") == "BOUND":
            need_text(row.get("binding"), "input_groups." + str(row.get("id")) + ".binding", row.get("owner") or "GEO")

    coverage = mapping(recipe.get("coverage"), "coverage")
    record_state(coverage, "coverage", "Physical")
    refs(coverage.get("domain_inventory_source_ids"), "coverage.domain_inventory_source_ids", "Physical")
    need_text(coverage.get("coverage_proof"), "coverage.coverage_proof", "Physical")
    if coverage.get("additional_family_inventory") not in {"COMPLETE_NONE", "COMPLETE_LISTED"}:
        add("coverage.additional_family_inventory", "ADDITIONAL_FAMILIES_UNKNOWN", "Physical", "Inventory exceptional, organic/biogenic and other applicable additional families.")
    families = rows(recipe.get("families"), "families")
    for missing in sorted(FAMILIES.keys() - {r.get("id") for r in families if _text(r.get("id"))}):
        add("families", "MISSING_FAMILY", "Physical", f"Required family missing: {missing}")
    for row in families:
        path, owner = "families." + str(row.get("id")), row.get("owner") or "Physical"
        state = record_state(row, path, owner)
        if state == "BOUND":
            if row.get("support") not in {"REFERENCE_IMPLEMENTED", "VALIDATED_APPROXIMATION", "PLANNED_IMPLEMENTATION"}:
                add(path, "UNSUPPORTED_FAMILY", owner, "Active family needs an explicit implementation/approximation choice.")
            need_text(row.get("algorithm"), path + ".algorithm")
            need_text(row.get("domain_binding"), path + ".domain_binding", owner)
            need_text(row.get("parameter_binding"), path + ".parameter_binding", owner)
    if coverage.get("additional_family_inventory") == "COMPLETE_LISTED" and not any(r.get("id") not in FAMILIES for r in families):
        add("coverage", "ADDITIONAL_FAMILY_LIST_EMPTY", "Physical", "Additional-family inventory says listed but has no additional records.", "FAIL")

    constraint_inventory = mapping(recipe.get("constraint_inventory"), "constraint_inventory")
    record_state(constraint_inventory, "constraint_inventory", "Physical/GEO")
    for row in rows(recipe.get("constraints"), "constraints"):
        path, owner = "constraints." + str(row.get("id")), row.get("owner") or "Physical"
        for field in ("geometry_binding", "reason", "source_status", "conflict_policy", "owner"):
            need_text(row.get(field), path + "." + field, owner)
        refs(row.get("source_ids"), path + ".source_ids", owner)
        if row.get("role") not in {"hard", "soft", "reference"}:
            add(path, "CONSTRAINT_ROLE", owner, "Unknown constraint role.", "FAIL")
        interval = row.get("interval")
        if not isinstance(interval, list) or len(interval) != 2 or not all(_number(x) for x in interval) or interval[0] > interval[1]:
            add(path, "CONSTRAINT_INTERVAL", owner, "Ordered finite numerical constraint interval required.", "FAIL")
        need_text(row.get("units"), path + ".units", owner)
        if row.get("role") == "hard" and row.get("derived_predecessor") is not False:
            refs(row.get("owner_decision_source_ids"), path + ".owner_decision_source_ids", owner)
            add(path, "HARD_DERIVED_OWNER_REVIEW", owner, "Independent owner review must establish the hard role; ancestry or an asserted approval is not proof.")

    tests = rows(recipe.get("tests"), "tests")
    for missing in sorted(TEST_IDS - {r.get("id") for r in tests if _text(r.get("id"))}):
        add("tests", "MISSING_TEST", "Engineering", f"Required test/applicability record missing: {missing}")
    split_hashes = {"calibration": set(), "holdout": set()}
    for row in tests:
        path, owner = "tests." + str(row.get("id")), row.get("owner") or "Engineering/Physical"
        if record_state(row, path, owner) != "BOUND":
            continue
        fixture = mapping(row.get("fixture"), path + ".fixture")
        for field in ("regime", "parameters", "expected", "method", "requirements"):
            need_text(row.get(field), path + "." + field, owner)
        refs(fixture.get("source_ids"), path + ".fixture.source_ids", owner)
        shape = fixture.get("shape")
        if not isinstance(shape, list) or len(shape) != 2 or any(type(x) is not int or x < 1 for x in shape):
            add(path, "FIXTURE_SHAPE", owner, "Two positive integer dimensions required.", "FAIL")
        positive(fixture.get("spacing_m"), path + ".fixture.spacing_m")
        if type(fixture.get("seed")) is not int or fixture["seed"] < 0:
            add(path, "SEED", "Engineering", "Explicit non-negative integer seed required (zero for deterministic fixtures).", "FAIL")
        split = fixture.get("split")
        if split not in {"analytical", "calibration", "holdout", "regression"}:
            add(path, "SPLIT", owner, "One explicit fixture split is required.", "FAIL")
        for source_id in fixture.get("source_ids", []) if isinstance(fixture.get("source_ids"), list) else []:
            if split in split_hashes:
                for source in sources:
                    if source.get("id") == source_id:
                        split_hashes[split].add(source.get("sha256"))
        tolerance = mapping(row.get("tolerance"), path + ".tolerance")
        for field in ("metric", "units", "scale_definition", "justification"):
            need_text(tolerance.get(field), path + ".tolerance." + field, owner)
        for field in ("atol", "rtol"):
            value = tolerance.get(field)
            if value is None:
                add(path + ".tolerance." + field, "UNBOUND_TOLERANCE", owner, "Numerical tolerance must be frozen before scoring.")
            elif not _number(value) or value < 0:
                add(path + ".tolerance." + field, "INVALID_TOLERANCE", owner, "Tolerance must be finite, non-negative and not Boolean.", "FAIL")
        if row.get("acceptance_layer") not in {"logical", "numerical", "physical"}:
            add(path, "ACCEPTANCE_LAYER", owner, "Separate logical, numerical and physical checks.", "FAIL")
        if row.get("acceptance_layer") == "physical":
            band = tolerance.get("physical_band")
            if not isinstance(band, list) or len(band) != 2 or not all(_number(x) for x in band) or band[0] > band[1]:
                add(path, "PHYSICAL_BAND", "Physical", "A matched-regime numerical physical band must be bound.")
    if split_hashes["calibration"] & split_hashes["holdout"]:
        add("tests", "HOLDOUT_LEAKAGE", "Physical/Engineering", "Calibration and holdout source hashes overlap, including aliases.", "FAIL")

    coupling = mapping(recipe.get("coupling"), "coupling")
    record_state(coupling, "coupling", "Physical/Water/Climate")
    for field in ("method", "stopping_rule", "limits", "influence_proof", "c1_compatibility", "meltwater_producer", "mass_basis"):
        need_text(coupling.get(field), "coupling." + field, "Physical/Water/Climate")
    if _text(coupling.get("mass_basis")) and coupling["mass_basis"] not in {"rock_derived", "actual_chemical_with_external_constituents", "reconstruction_geometric_change"}:
        add("coupling.mass_basis", "MASS_BASIS", "Physical/Climate", "Do not equate rock-derived mass with actual chemical mass without external constituents.", "FAIL")
    downstream = mapping(recipe.get("downstream"), "downstream")
    record_state(downstream, "downstream", "Engineering/GEO")
    need_text(downstream.get("influence_rule"), "downstream.influence_rule", "Engineering/Water/Climate")
    need_text(downstream.get("compatibility_rule"), "downstream.compatibility_rule", "Engineering/GEO")
    dependents = downstream.get("dependent_products")
    expected_dependents = {"refinement", "gradients", "water", "climate", "soils", "sites", "resources", "habitats", "routes"}
    if not isinstance(dependents, list) or any(not isinstance(item, str) for item in dependents) or not expected_dependents.issubset(dependents):
        add("downstream.dependent_products", "DEPENDENCY_COVERAGE", "Engineering/GEO", "Account for refinement, gradients, water, climate, soils, sites, resources, habitats and routes.")
    resources = mapping(recipe.get("development_resources"), "development_resources")
    for field in ("max_cells", "max_workers", "memory_mib", "storage_mib", "wall_seconds"):
        positive(resources.get(field), "development_resources." + field, integer=True)
    need_text(resources.get("cancellation_rule"), "development_resources.cancellation_rule")
    for row in tests:
        fixture = row.get("fixture")
        shape = fixture.get("shape") if isinstance(fixture, dict) else None
        cap = resources.get("max_cells")
        if isinstance(shape, list) and len(shape) == 2 and all(type(x) is int and x > 0 for x in shape) and type(cap) is int and shape[0] * shape[1] > cap:
            add("tests." + str(row.get("id")), "DEVELOPMENT_ENVELOPE", "Engineering", "Fixture exceeds the declared bounded development cell envelope.", "FAIL")
    failed = any(issue["severity"] == "FAIL" for issue in issues)
    return {"binding_validation": "FAIL" if failed else "INCOMPLETE" if issues else "PASS",
            "gate_b": "INCOMPLETE", "production_ready": False, "model_implemented": False,
            "issues": issues, "notice": "Metadata validation is not source verification, spatial coverage proof, scientific approval or permission to run."}


def validate_recipe(recipe: dict):
    """Malformed data fail closed; no declaration can manufacture a run gate."""
    try:
        return _validate_recipe(recipe)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        return {"binding_validation": "FAIL", "gate_b": "INCOMPLETE", "production_ready": False,
                "model_implemented": False, "issues": [{"path": "recipe", "code": "MALFORMED_VALUE",
                "owner": "Engineering", "message": str(error), "severity": "FAIL"}],
                "notice": "No generation was performed or authorised."}
