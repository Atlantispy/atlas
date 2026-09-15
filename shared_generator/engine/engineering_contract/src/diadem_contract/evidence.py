"""Builders for standard benchmark and adoption evidence records."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .canonical import SemanticFingerprint
from .validation import validate_document


METRIC_FIELDS = (
    "wall_seconds",
    "cpu_seconds",
    "peak_ram_bytes",
    "disk_read_bytes",
    "disk_write_bytes",
    "files_opened",
    "data_read_bytes",
    "output_bytes",
    "context_bytes",
    "estimated_context_tokens",
    "disk_read_operations",
    "disk_write_operations",
    "measurement_methods",
)


def metric_set(**values: Any) -> dict[str, Any]:
    missing = [field for field in METRIC_FIELDS if field not in values]
    if missing:
        raise ValueError(f"missing benchmark metrics: {', '.join(missing)}")
    result = {field: values[field] for field in METRIC_FIELDS}
    measured = {field for field in METRIC_FIELDS if field not in {"context_bytes", "estimated_context_tokens", "disk_read_operations", "disk_write_operations", "measurement_methods"}}
    if any(isinstance(result[field], bool) or not isinstance(result[field], (int, float)) or result[field] < 0 for field in measured):
        raise ValueError("ordinary benchmark metrics must be non-negative numbers")
    methods = result["measurement_methods"]
    nullable = {"context_bytes", "estimated_context_tokens", "disk_read_operations", "disk_write_operations"}
    if not isinstance(methods, Mapping) or set(methods) != nullable:
        raise ValueError("measurement_methods must describe every nullable benchmark metric")
    for field in nullable:
        specification = methods[field]
        if not isinstance(specification, Mapping) or specification.get("basis") not in {"MEASURED", "ESTIMATED", "NOT_MEASURABLE"} or not specification.get("method"):
            raise ValueError(f"invalid measurement method for {field}")
        if specification["basis"] == "NOT_MEASURABLE":
            if result[field] is not None:
                raise ValueError(f"{field} must be null when not measurable")
        elif not (isinstance(result[field], int) and not isinstance(result[field], bool) and result[field] >= 0):
            raise ValueError(f"{field} must be a non-negative integer when measured or estimated")
    return result


def benchmark_record(
    *,
    benchmark_id: str,
    task: Mapping[str, Any],
    environment: Mapping[str, Any],
    reference_path_id: str,
    candidate_path_id: str,
    reference_metrics: Mapping[str, Any],
    candidate_metrics: Mapping[str, Any],
    reference_output_fingerprints: Sequence[str],
    candidate_output_fingerprints: Sequence[str],
    runs: int,
    artifact_family: str,
    parity_report_fingerprint: str,
    parity_pass: bool,
    resource_limits_pass: bool,
) -> dict[str, Any]:
    for fingerprint in [*reference_output_fingerprints, *candidate_output_fingerprints, parity_report_fingerprint]:
        SemanticFingerprint.parse(fingerprint)
    reference_wall = float(reference_metrics["wall_seconds"])
    candidate_wall = float(candidate_metrics["wall_seconds"])
    gain = 0.0 if reference_wall == 0 else (reference_wall - candidate_wall) / reference_wall
    document = {
        "schema": "diadem.engineering.benchmark.v1",
        "benchmark_id": benchmark_id,
        "task": dict(task),
        "environment": dict(environment),
        "identical_inputs": True,
        "reference": {
            "path_id": reference_path_id,
            "runs": runs,
            "metrics": dict(reference_metrics),
            "output_fingerprints": list(reference_output_fingerprints),
        },
        "candidate": {
            "path_id": candidate_path_id,
            "runs": runs,
            "metrics": dict(candidate_metrics),
            "output_fingerprints": list(candidate_output_fingerprints),
        },
        "comparison": {
            "artifact_family": artifact_family,
            "parity_pass": parity_pass,
            "parity_report_fingerprint": parity_report_fingerprint,
            "end_to_end_gain_fraction": gain,
            "resource_limits_pass": resource_limits_pass,
        },
        "status": "PASS" if parity_pass and resource_limits_pass else "FAIL",
    }
    result = validate_document(document)
    if not result.passed:
        raise ValueError(result.as_dict())
    return document


def adoption_record(
    *,
    decision_id: str,
    optimisation_id: str,
    owner: str,
    reason: str,
    feature_flag: str,
    evidence: Mapping[str, Any],
    minimum_gain: float,
    maximum_peak_ram_bytes: int,
    observed_gain: float,
    observed_peak_ram_bytes: int,
    parity_pass: bool,
    fault_tests_pass: bool,
    fallback_pass: bool,
    fallback_test_id: str,
    retirement_condition: str,
    decision: str,
    evidence_documents: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    document = {
        "schema": "diadem.engineering.adoption-decision.v1",
        "decision_id": decision_id,
        "optimisation_id": optimisation_id,
        "owner": owner,
        "reason": reason,
        "feature_flag": feature_flag,
        "evidence": dict(evidence),
        "thresholds": {
            "minimum_end_to_end_gain_fraction": minimum_gain,
            "maximum_peak_ram_bytes": maximum_peak_ram_bytes,
            "parity_required": True,
            "fault_tests_required": True,
        },
        "observed": {
            "end_to_end_gain_fraction": observed_gain,
            "peak_ram_bytes": observed_peak_ram_bytes,
            "parity_pass": parity_pass,
            "fault_tests_pass": fault_tests_pass,
            "fallback_pass": fallback_pass,
        },
        "fallback_test_id": fallback_test_id,
        "retirement_condition": retirement_condition,
        "decision": decision,
    }
    result = validate_document(document, evidence_documents=list(evidence_documents) if evidence_documents is not None else None)
    if not result.passed:
        raise ValueError(result.as_dict())
    return document
