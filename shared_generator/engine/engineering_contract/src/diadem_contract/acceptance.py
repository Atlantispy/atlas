"""Executable whole-engine output-preservation comparators."""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Any, Mapping, Sequence

from .canonical import canonical_json_bytes
from .ids import StructuredId


@dataclass(frozen=True)
class ComparisonResult:
    passed: bool
    comparator: str
    mismatch_count: int
    max_absolute_error: float | None = None
    max_relative_error: float | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "comparator": self.comparator,
            "mismatch_count": self.mismatch_count,
            "max_absolute_error": self.max_absolute_error,
            "max_relative_error": self.max_relative_error,
            "detail": self.detail,
        }


def _numeric_pairs(reference: Any, candidate: Any, path: str = "$"):
    if isinstance(reference, Mapping) and isinstance(candidate, Mapping):
        if set(reference) != set(candidate):
            raise ValueError(f"shape/key mismatch at {path}")
        for key in sorted(reference):
            yield from _numeric_pairs(reference[key], candidate[key], f"{path}.{key}")
        return
    if isinstance(reference, Sequence) and not isinstance(reference, (str, bytes, bytearray)):
        if not isinstance(candidate, Sequence) or isinstance(candidate, (str, bytes, bytearray)):
            raise ValueError(f"shape/type mismatch at {path}")
        if len(reference) != len(candidate):
            raise ValueError(f"length mismatch at {path}")
        for index, (left, right) in enumerate(zip(reference, candidate)):
            yield from _numeric_pairs(left, right, f"{path}[{index}]")
        return
    if isinstance(reference, bool) or isinstance(candidate, bool):
        if reference != candidate:
            raise ValueError(f"non-numeric mismatch at {path}")
        return
    if isinstance(reference, (int, float)) and isinstance(candidate, (int, float)):
        yield path, float(reference), float(candidate)
        return
    if reference != candidate:
        raise ValueError(f"non-numeric mismatch at {path}")


def _float32_ordered(value: float) -> int:
    bits = struct.unpack(">I", struct.pack(">f", value))[0]
    return (~bits & 0xFFFFFFFF) if bits & 0x80000000 else (bits | 0x80000000)


def _ulp_distance(left: float, right: float, dtype: str) -> int:
    if dtype == "float32":
        return abs(_float32_ordered(left) - _float32_ordered(right))
    left_bits = struct.unpack(">Q", struct.pack(">d", left))[0]
    right_bits = struct.unpack(">Q", struct.pack(">d", right))[0]
    left_ordered = (~left_bits & 0xFFFFFFFFFFFFFFFF) if left_bits & (1 << 63) else left_bits | (1 << 63)
    right_ordered = (~right_bits & 0xFFFFFFFFFFFFFFFF) if right_bits & (1 << 63) else right_bits | (1 << 63)
    return abs(left_ordered - right_ordered)


def _normalise_topology(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or "nodes" not in value or "edges" not in value:
        raise ValueError("topology comparator requires nodes and edges")
    nodes = sorted(value["nodes"], key=lambda node: canonical_json_bytes(node.get("id")))
    edges = sorted(
        value["edges"],
        key=lambda edge: canonical_json_bytes(
            [edge.get("source"), edge.get("target"), edge.get("key", "")]
        ),
    )
    remainder = {key: child for key, child in value.items() if key not in {"nodes", "edges"}}
    return {**remainder, "nodes": nodes, "edges": edges}


def compare_artifact(
    reference: Any,
    candidate: Any,
    rule: Mapping[str, Any],
    *,
    context: Mapping[str, str] | None = None,
) -> ComparisonResult:
    """Compare a published artefact under one preservation-matrix rule."""

    comparator = rule["comparator"]
    if comparator == "EXACT_BYTES":
        if not isinstance(reference, (bytes, bytearray)) or not isinstance(candidate, (bytes, bytearray)):
            raise TypeError("EXACT_BYTES requires bytes")
        passed = bytes(reference) == bytes(candidate)
        return ComparisonResult(passed, comparator, 0 if passed else 1)
    if comparator == "EXACT_CANONICAL":
        passed = canonical_json_bytes(reference) == canonical_json_bytes(candidate)
        return ComparisonResult(passed, comparator, 0 if passed else 1)
    if comparator == "EXACT_ARRAY_BITS":
        if not isinstance(reference, (bytes, bytearray)) or not isinstance(candidate, (bytes, bytearray)):
            raise TypeError("EXACT_ARRAY_BITS requires canonical array bytes")
        passed = bytes(reference) == bytes(candidate)
        return ComparisonResult(passed, comparator, 0 if passed else 1)
    if comparator == "STRUCTURAL_TOPOLOGY":
        passed = canonical_json_bytes(_normalise_topology(reference)) == canonical_json_bytes(
            _normalise_topology(candidate)
        )
        return ComparisonResult(passed, comparator, 0 if passed else 1)
    if comparator == "NUMERIC_TOLERANCE":
        required_scope = {name: rule.get(name) for name in ("producer_id", "layer_id", "unit")}
        if any(not isinstance(value, str) or not value for value in required_scope.values()):
            return ComparisonResult(False, comparator, 1, detail="numeric tolerance rule is not producer/layer/unit scoped")
        try:
            layer = StructuredId.decode(required_scope["layer_id"])
        except (TypeError, ValueError) as exc:
            return ComparisonResult(False, comparator, 1, detail=f"numeric tolerance has invalid layer ID: {exc}")
        if layer.kind != "layer":
            return ComparisonResult(False, comparator, 1, detail="numeric tolerance layer_id is not a layer ID")
        if context is None:
            return ComparisonResult(False, comparator, 1, detail="numeric tolerance requires producer/layer/unit comparison context")
        mismatched_scope = [name for name, expected in required_scope.items() if context.get(name) != expected]
        if mismatched_scope:
            return ComparisonResult(False, comparator, 1, detail="numeric tolerance context mismatch: " + ", ".join(mismatched_scope))
        tolerance = rule["tolerance"]
        absolute = float(tolerance["absolute"])
        relative = float(tolerance["relative"])
        max_ulps = int(tolerance["max_ulps"])
        dtype = tolerance["dtype"]
        mismatch = 0
        max_absolute = 0.0
        max_relative = 0.0
        try:
            pairs = list(_numeric_pairs(reference, candidate))
        except ValueError as exc:
            return ComparisonResult(False, comparator, 1, detail=str(exc))
        for _, left, right in pairs:
            if math.isnan(left) or math.isnan(right):
                equal = tolerance.get("nan_policy") == "EQUAL_IF_BOTH" and math.isnan(left) and math.isnan(right)
                if not equal:
                    mismatch += 1
                continue
            if math.isinf(left) or math.isinf(right):
                if left != right:
                    mismatch += 1
                continue
            error = abs(left - right)
            denominator = max(abs(left), abs(right), 1e-300)
            rel_error = error / denominator
            max_absolute = max(max_absolute, error)
            max_relative = max(max_relative, rel_error)
            within_abs_rel = error <= absolute + relative * max(abs(left), abs(right))
            within_ulp = _ulp_distance(left, right, dtype) <= max_ulps
            if not (within_abs_rel or within_ulp):
                mismatch += 1
        return ComparisonResult(
            mismatch == 0,
            comparator,
            mismatch,
            max_absolute_error=max_absolute,
            max_relative_error=max_relative,
        )
    if comparator == "NOT_PUBLISHED":
        return ComparisonResult(True, comparator, 0, detail="internal state excluded from published parity")
    raise ValueError(f"unknown comparator: {comparator}")


def rule_for_family(matrix: Mapping[str, Any], family_id: str) -> Mapping[str, Any]:
    matches = [item for item in matrix["artifact_families"] if item["family_id"] == family_id]
    if len(matches) != 1:
        raise KeyError(f"expected exactly one preservation rule for {family_id!r}")
    return matches[0]
