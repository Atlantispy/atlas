"""Dependency-free validators for Phase-1 engineering evidence records."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .canonical import SemanticFingerprint
from .ids import StructuredId


SCHEMAS = {
    "diadem.engineering.preservation-matrix.v1",
    "diadem.engineering.benchmark.v1",
    "diadem.engineering.corruption-test.v1",
    "diadem.engineering.cancellation-test.v1",
    "diadem.engineering.fallback-test.v1",
    "diadem.engineering.adoption-decision.v1",
}


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message}


@dataclass(frozen=True)
class ValidationResult:
    schema: str | None
    passed: bool
    issues: tuple[ValidationIssue, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "passed": self.passed,
            "issues": [issue.as_dict() for issue in self.issues],
        }


class _Check:
    def __init__(self, document: Any):
        self.document = document
        self.issues: list[ValidationIssue] = []

    def require(self, condition: bool, path: str, message: str) -> None:
        if not condition:
            self.issues.append(ValidationIssue(path, message))

    def fields(self, document: Mapping[str, Any], names: set[str], path: str = "$") -> None:
        for name in sorted(names):
            self.require(name in document, f"{path}.{name}", "required field is missing")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_preservation(document: Mapping[str, Any], check: _Check) -> None:
    check.fields(document, {"schema", "contract_id", "version", "status", "artifact_families", "adoption_gates"})
    check.require(document.get("status") == "ACTIVE_ENGINEERING_CONTRACT", "$.status", "contract must be active")
    families = document.get("artifact_families")
    check.require(isinstance(families, list) and bool(families), "$.artifact_families", "must be a non-empty list")
    if not isinstance(families, list):
        return
    identifiers: list[str] = []
    allowed = {"EXACT_BYTES", "EXACT_CANONICAL", "EXACT_ARRAY_BITS", "NUMERIC_TOLERANCE", "STRUCTURAL_TOPOLOGY", "NOT_PUBLISHED"}
    for index, family in enumerate(families):
        path = f"$.artifact_families[{index}]"
        check.require(isinstance(family, dict), path, "family must be an object")
        if not isinstance(family, dict):
            continue
        check.fields(family, {"family_id", "scope", "comparator", "preserves"}, path)
        identifiers.append(family.get("family_id"))
        comparator = family.get("comparator")
        check.require(comparator in allowed, f"{path}.comparator", "unknown comparator")
        if comparator == "NUMERIC_TOLERANCE":
            check.fields(family, {"producer_id", "layer_id", "unit"}, path)
            check.require(isinstance(family.get("producer_id"), str) and bool(family.get("producer_id")), f"{path}.producer_id", "numeric tolerance requires a producer scope")
            check.require(isinstance(family.get("unit"), str) and bool(family.get("unit")), f"{path}.unit", "numeric tolerance requires a unit scope")
            try:
                layer = StructuredId.decode(family.get("layer_id"))
                check.require(layer.kind == "layer", f"{path}.layer_id", "must be a layer structured ID")
            except (TypeError, ValueError):
                check.require(False, f"{path}.layer_id", "numeric tolerance requires a valid layer structured ID")
            tolerance = family.get("tolerance")
            check.require(isinstance(tolerance, dict), f"{path}.tolerance", "numeric comparator requires tolerance")
            if isinstance(tolerance, dict):
                check.fields(tolerance, {"absolute", "relative", "max_ulps", "dtype", "nan_policy"}, f"{path}.tolerance")
                check.require(_is_number(tolerance.get("absolute")) and tolerance.get("absolute", -1) >= 0, f"{path}.tolerance.absolute", "must be non-negative")
                check.require(_is_number(tolerance.get("relative")) and tolerance.get("relative", -1) >= 0, f"{path}.tolerance.relative", "must be non-negative")
                check.require(isinstance(tolerance.get("max_ulps"), int) and not isinstance(tolerance.get("max_ulps"), bool) and tolerance.get("max_ulps", -1) >= 0, f"{path}.tolerance.max_ulps", "must be a non-negative integer")
                check.require(tolerance.get("dtype") in {"float32", "float64"}, f"{path}.tolerance.dtype", "must be float32 or float64")
    check.require(len(identifiers) == len(set(identifiers)), "$.artifact_families", "family IDs must be unique")


def _validate_metric_set(value: Any, path: str, check: _Check) -> None:
    check.require(isinstance(value, dict), path, "metrics must be an object")
    if not isinstance(value, dict):
        return
    required_measured = {
        "wall_seconds",
        "cpu_seconds",
        "peak_ram_bytes",
        "disk_read_bytes",
        "disk_write_bytes",
        "files_opened",
        "data_read_bytes",
        "output_bytes",
    }
    nullable_measured = {
        "context_bytes",
        "estimated_context_tokens",
        "disk_read_operations",
        "disk_write_operations",
    }
    required = required_measured | nullable_measured | {"measurement_methods"}
    check.fields(value, required, path)
    for name in required_measured:
        if name in value:
            check.require(_is_number(value[name]) and value[name] >= 0, f"{path}.{name}", "must be a non-negative number")
    methods = value.get("measurement_methods")
    check.require(isinstance(methods, dict), f"{path}.measurement_methods", "must be an object")
    if not isinstance(methods, dict):
        return
    check.fields(methods, nullable_measured, f"{path}.measurement_methods")
    for name in sorted(nullable_measured):
        method = methods.get(name)
        method_path = f"{path}.measurement_methods.{name}"
        check.require(isinstance(method, dict), method_path, "must be an object")
        if not isinstance(method, dict):
            continue
        check.fields(method, {"basis", "method"}, method_path)
        basis = method.get("basis")
        check.require(basis in {"MEASURED", "ESTIMATED", "NOT_MEASURABLE"}, f"{method_path}.basis", "invalid measurement basis")
        check.require(isinstance(method.get("method"), str) and bool(method.get("method")), f"{method_path}.method", "measurement method must be non-empty")
        observed = value.get(name)
        if basis == "NOT_MEASURABLE":
            check.require(observed is None, f"{path}.{name}", "NOT_MEASURABLE values must be null, never a fabricated zero")
        elif basis in {"MEASURED", "ESTIMATED"}:
            check.require(
                isinstance(observed, int) and not isinstance(observed, bool) and observed >= 0,
                f"{path}.{name}",
                f"{basis} count/byte values must be non-negative integers",
            )


def _validate_benchmark(document: Mapping[str, Any], check: _Check) -> None:
    check.fields(document, {"schema", "benchmark_id", "task", "environment", "identical_inputs", "reference", "candidate", "comparison", "status"})
    check.require(document.get("status") in {"PASS", "FAIL"}, "$.status", "must be PASS or FAIL")
    check.require(document.get("identical_inputs") is True, "$.identical_inputs", "reference and candidate must use identical semantic inputs")
    task = document.get("task")
    check.require(isinstance(task, dict), "$.task", "must be an object")
    if isinstance(task, dict):
        check.fields(task, {"name", "semantic_input_fingerprint"}, "$.task")
        try:
            SemanticFingerprint.parse(task.get("semantic_input_fingerprint"))
        except (TypeError, ValueError):
            check.require(False, "$.task.semantic_input_fingerprint", "invalid semantic fingerprint")
    reference_value = document.get("reference")
    candidate_value = document.get("candidate")
    if isinstance(reference_value, dict) and isinstance(candidate_value, dict):
        check.require(reference_value.get("path_id") != candidate_value.get("path_id"), "$", "reference and candidate paths must differ")
    for side in ("reference", "candidate"):
        value = document.get(side)
        check.require(isinstance(value, dict), f"$.{side}", "must be an object")
        if isinstance(value, dict):
            check.fields(value, {"path_id", "runs", "metrics", "output_fingerprints"}, f"$.{side}")
            check.require(isinstance(value.get("runs"), int) and value.get("runs", 0) >= 3, f"$.{side}.runs", "at least three runs are required")
            _validate_metric_set(value.get("metrics"), f"$.{side}.metrics", check)
            fingerprints = value.get("output_fingerprints")
            check.require(isinstance(fingerprints, list) and bool(fingerprints), f"$.{side}.output_fingerprints", "must be non-empty")
            if isinstance(fingerprints, list):
                for index, fingerprint in enumerate(fingerprints):
                    try:
                        SemanticFingerprint.parse(fingerprint)
                    except (TypeError, ValueError):
                        check.require(False, f"$.{side}.output_fingerprints[{index}]", "invalid semantic fingerprint")
    comparison = document.get("comparison")
    check.require(isinstance(comparison, dict), "$.comparison", "must be an object")
    if isinstance(comparison, dict):
        check.fields(comparison, {"artifact_family", "parity_pass", "parity_report_fingerprint", "end_to_end_gain_fraction", "resource_limits_pass"}, "$.comparison")
        try:
            SemanticFingerprint.parse(comparison.get("parity_report_fingerprint"))
        except (TypeError, ValueError):
            check.require(False, "$.comparison.parity_report_fingerprint", "invalid semantic fingerprint")
        if document.get("status") == "PASS":
            check.require(comparison.get("parity_pass") is True, "$.comparison.parity_pass", "PASS requires parity")
            check.require(comparison.get("resource_limits_pass") is True, "$.comparison.resource_limits_pass", "PASS requires bounded resources")


def _validate_fault_common(document: Mapping[str, Any], check: _Check, expected_schema: str) -> None:
    check.fields(document, {"schema", "test_id", "target_path_id", "fault", "expected", "observed", "status"})
    check.require(document.get("schema") == expected_schema, "$.schema", "wrong fault-test schema")
    check.require(document.get("status") in {"PASS", "FAIL"}, "$.status", "must be PASS or FAIL")
    for name in ("fault", "expected", "observed"):
        check.require(isinstance(document.get(name), dict), f"$.{name}", "must be an object")


def _validate_corruption(document: Mapping[str, Any], check: _Check) -> None:
    _validate_fault_common(document, check, "diadem.engineering.corruption-test.v1")
    expected = document.get("expected") or {}
    observed = document.get("observed") or {}
    check.fields(expected, {"detected", "published_partial_forbidden", "rebuild_from_authority", "unaffected_data_recoverable"}, "$.expected")
    check.fields(observed, {"detected", "published_partial", "rebuilt_from_authority", "unaffected_data_recovered"}, "$.observed")
    if document.get("status") == "PASS":
        check.require(observed.get("detected") is True, "$.observed.detected", "PASS requires detection")
        check.require(observed.get("published_partial") is False, "$.observed.published_partial", "PASS forbids partial publication")
        check.require(observed.get("rebuilt_from_authority") is True, "$.observed.rebuilt_from_authority", "PASS requires verified authority rebuild")
        check.require(observed.get("unaffected_data_recovered") is True, "$.observed.unaffected_data_recovered", "PASS requires unaffected-data recovery")


def _validate_cancellation(document: Mapping[str, Any], check: _Check) -> None:
    _validate_fault_common(document, check, "diadem.engineering.cancellation-test.v1")
    expected = document.get("expected") or {}
    observed = document.get("observed") or {}
    check.fields(expected, {"last_committed_digest_preserved", "staging_disposition", "resume_required"}, "$.expected")
    check.fields(observed, {"last_committed_digest_preserved", "staging_disposition", "resume_digest_equal"}, "$.observed")
    if document.get("status") == "PASS":
        check.require(observed.get("last_committed_digest_preserved") is True, "$.observed.last_committed_digest_preserved", "PASS must preserve the last commit")
        check.require(observed.get("resume_digest_equal") is True, "$.observed.resume_digest_equal", "PASS requires clean-replay-equivalent resume")


def _validate_fallback(document: Mapping[str, Any], check: _Check) -> None:
    check.fields(document, {"schema", "test_id", "optimised_path_id", "reference_path_id", "trigger", "capability_self_test", "fallback", "parity", "status"})
    check.require(document.get("status") in {"PASS", "FAIL"}, "$.status", "must be PASS or FAIL")
    check.require(document.get("optimised_path_id") != document.get("reference_path_id"), "$", "optimised and reference paths must differ")
    fallback = document.get("fallback") or {}
    parity = document.get("parity") or {}
    check.fields(fallback, {"selected", "reason_recorded", "telemetry_recorded"}, "$.fallback")
    check.fields(parity, {"artifact_family", "passed", "report_fingerprint"}, "$.parity")
    if document.get("status") == "PASS":
        check.require(fallback.get("selected") is True, "$.fallback.selected", "PASS requires fallback selection")
        check.require(fallback.get("reason_recorded") is True, "$.fallback.reason_recorded", "PASS requires a recorded fallback reason")
        check.require(fallback.get("telemetry_recorded") is True, "$.fallback.telemetry_recorded", "PASS requires fallback telemetry")
        check.require(parity.get("passed") is True, "$.parity.passed", "PASS requires output parity")


def _validate_adoption(document: Mapping[str, Any], check: _Check) -> None:
    check.fields(document, {"schema", "decision_id", "optimisation_id", "owner", "reason", "feature_flag", "evidence", "thresholds", "observed", "fallback_test_id", "retirement_condition", "decision"})
    decision = document.get("decision")
    check.require(decision in {"ADOPT", "REJECT", "CONDITIONAL"}, "$.decision", "unknown decision")
    evidence = document.get("evidence") or {}
    thresholds = document.get("thresholds") or {}
    observed = document.get("observed") or {}
    check.fields(evidence, {"benchmark_id", "corruption_test_id", "cancellation_test_id", "fallback_test_id", "parity_report_fingerprint"}, "$.evidence")
    check.fields(thresholds, {"minimum_end_to_end_gain_fraction", "maximum_peak_ram_bytes", "parity_required", "fault_tests_required"}, "$.thresholds")
    check.fields(observed, {"end_to_end_gain_fraction", "peak_ram_bytes", "parity_pass", "fault_tests_pass", "fallback_pass"}, "$.observed")
    if decision == "ADOPT":
        check.require(observed.get("parity_pass") is True, "$.observed.parity_pass", "ADOPT requires parity")
        check.require(observed.get("fault_tests_pass") is True, "$.observed.fault_tests_pass", "ADOPT requires fault tests")
        check.require(observed.get("fallback_pass") is True, "$.observed.fallback_pass", "ADOPT requires fallback")
        minimum_gain = thresholds.get("minimum_end_to_end_gain_fraction")
        maximum_ram = thresholds.get("maximum_peak_ram_bytes")
        check.require(
            _is_number(observed.get("end_to_end_gain_fraction"))
            and _is_number(minimum_gain)
            and observed["end_to_end_gain_fraction"] >= minimum_gain,
            "$.observed.end_to_end_gain_fraction",
            "gain is below the adoption threshold",
        )
        check.require(
            _is_number(observed.get("peak_ram_bytes"))
            and _is_number(maximum_ram)
            and observed["peak_ram_bytes"] <= maximum_ram,
            "$.observed.peak_ram_bytes",
            "peak RAM exceeds the adoption threshold",
        )


_VALIDATORS: dict[str, Callable[[Mapping[str, Any], _Check], None]] = {
    "diadem.engineering.preservation-matrix.v1": _validate_preservation,
    "diadem.engineering.benchmark.v1": _validate_benchmark,
    "diadem.engineering.corruption-test.v1": _validate_corruption,
    "diadem.engineering.cancellation-test.v1": _validate_cancellation,
    "diadem.engineering.fallback-test.v1": _validate_fallback,
    "diadem.engineering.adoption-decision.v1": _validate_adoption,
}

_EVIDENCE_REFERENCE_TYPES = {
    "benchmark_id": ("diadem.engineering.benchmark.v1", "benchmark_id"),
    "corruption_test_id": ("diadem.engineering.corruption-test.v1", "test_id"),
    "cancellation_test_id": ("diadem.engineering.cancellation-test.v1", "test_id"),
    "fallback_test_id": ("diadem.engineering.fallback-test.v1", "test_id"),
}


def _validate_adoption_evidence_resolution(
    document: Mapping[str, Any],
    check: _Check,
    evidence_documents: list[Mapping[str, Any]] | None,
) -> None:
    if document.get("schema") != "diadem.engineering.adoption-decision.v1" or document.get("decision") != "ADOPT":
        return
    if evidence_documents is None:
        check.require(False, "$", "ADOPT must be validated as part of an evidence bundle")
        return
    evidence = document.get("evidence") or {}
    for field, (expected_schema, id_field) in _EVIDENCE_REFERENCE_TYPES.items():
        identifier = evidence.get(field)
        matches = [
            candidate
            for candidate in evidence_documents
            if candidate.get("schema") == expected_schema and candidate.get(id_field) == identifier
        ]
        check.require(
            len(matches) == 1,
            f"$.evidence.{field}",
            f"ADOPT reference must resolve exactly once to {expected_schema}",
        )
        if len(matches) == 1:
            resolved = validate_document(matches[0])
            check.require(resolved.passed, f"$.evidence.{field}", "ADOPT reference must resolve to schema-valid evidence")
            check.require(matches[0].get("status") == "PASS", f"$.evidence.{field}", "ADOPT reference must resolve to PASS evidence")
    check.require(
        document.get("fallback_test_id") == evidence.get("fallback_test_id"),
        "$.fallback_test_id",
        "fallback reference disagrees with evidence block",
    )


def validate_document(
    document: Any,
    *,
    evidence_documents: list[Mapping[str, Any]] | None = None,
) -> ValidationResult:
    check = _Check(document)
    if not isinstance(document, dict):
        check.require(False, "$", "document must be an object")
        return ValidationResult(None, False, tuple(check.issues))
    schema = document.get("schema")
    check.require(schema in _VALIDATORS, "$.schema", "unsupported or missing schema")
    if schema in _VALIDATORS:
        _VALIDATORS[schema](document, check)
        _validate_adoption_evidence_resolution(document, check, evidence_documents)
    return ValidationResult(schema, not check.issues, tuple(check.issues))


def validate_file(path: str | Path) -> ValidationResult:
    with Path(path).open("r", encoding="utf-8") as handle:
        return validate_document(json.load(handle))


def validate_bundle(directory: str | Path) -> dict[str, Any]:
    root = Path(directory)
    results = []
    documents: dict[str, Mapping[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        documents[path.name] = document
    supplied_evidence = list(documents.values())
    for filename, document in documents.items():
        result = validate_document(document, evidence_documents=supplied_evidence)
        results.append({"file": filename, **result.as_dict()})
    bundle_issues: list[dict[str, str]] = []
    index: dict[tuple[str, str], Mapping[str, Any]] = {}
    id_field = {schema: field for schema, field in _EVIDENCE_REFERENCE_TYPES.values()}
    for document in documents.values():
        schema = document.get("schema")
        field = id_field.get(schema)
        if field and isinstance(document.get(field), str):
            key = (schema, document[field])
            if key in index:
                bundle_issues.append({"path": "$", "message": f"duplicate bundle evidence ID: {document[field]}"})
            index[key] = document
    passed = bool(results) and all(item["passed"] for item in results) and not bundle_issues
    return {"passed": passed, "results": results, "bundle_issues": bundle_issues}
