"""Small primary observational comparison; no writes, network, or physical PASS.

Heimsath et al.2012 Table S1 selected factual numeric transcription. The
copyrighted source PDF is not redistributed. See PHYSICAL_EVIDENCE.md.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import materials


MAX_POINTS = 256
SOURCE_URL = ("https://media.springernature.com/original/springer-static/esm/"
              "art%3A10.1038%2Fngeo1380/MediaObjects/41561_2012_BFngeo1380_MOESM286_ESM.pdf")
SOURCE_BYTES = 1174062
SOURCE_SHA256 = "9e8b57f14c88505dea793ee8004f0bd32d9815281e20989618dfe403f3156fd8"
# Explicit table facts: (sample ID, depth cm, production m/Ma, reported error m/Ma).
CALIBRATION_RAW = (
    ("SG-103", 23, 78, 17), ("SG-104", 30, 21, 9),
    ("SG-105", 43, 48, 12), ("SG-106", 36, 51, 13),
    ("SG-107", 15, 164, 29), ("SG-108", 15, 113, 23),
    ("SG-110", 10, 106, 20), ("SG-111", 44, 63, 15),
    ("SG-112", 27, 44, 9), ("SG-113", 34, 44, 10),
)
HOLDOUT_RAW = (
    ("SG-07-031", 13, 210, 41), ("SG-07-032", 3, 210, 38),
    ("SG-07-033", 20, 92, 18), ("SG-07-034", 5, 132, 25),
    ("SG-07-035", 3, 146, 28), ("SG-07-038", 3, 178, 33),
    ("SG-07-041", 12, 83, 15), ("SG-07-042", 12, 98, 18),
)
PROTOCOL = {
    "version": 1,
    "source_sha256": SOURCE_SHA256,
    "calibration_rule": "all Table S1 point samples with average patch slope26degrees",
    "holdout_rule": "all Table S1 point samples with average patch slope21degrees",
    "calibration_ids": [r[0] for r in CALIBRATION_RAW],
    "holdout_ids": [r[0] for r in HOLDOUT_RAW],
    "excluded": "all other groups and all catchment sediment samples; no response-based exclusions",
    "cm_to_m": .01, "m_per_Ma_to_m_per_year": 1e-6,
    "estimator": "weighted least squares log(P)=a-lambda*h; weight=(P/error)^2; lambda>=0",
    "negative_decay_action": "constant weighted-log model, no new split",
    "uncertainty": "reported rate errors only; log errors use delta method; no nominal confidence claim",
    "holdout_selection": "metadata-selected same-study cross-patch, not blind external holdout",
    "physical_acceptance_threshold": None,
    "max_points": MAX_POINTS,
}
EXPECTED_DATA_SHA256 = "30c13c9e8ef68cf3a0eeb437189e34e612b6de24abab66bc97e3a2a1022d7eb3"
EXPECTED_PROTOCOL_SHA256 = "06fc95600bb52ba2ac7dc6229ca1eaccef6addb38d9c1711c76b144c8028de9d"


class EvidenceError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def freeze_identity():
    """Read-only identity calculation; never executes a fit."""
    return {"data_sha256": _digest({"calibration": CALIBRATION_RAW, "holdout": HOLDOUT_RAW}),
            "protocol_sha256": _digest(PROTOCOL)}


def _assert_frozen():
    if freeze_identity() != {"data_sha256": EXPECTED_DATA_SHA256,
                             "protocol_sha256": EXPECTED_PROTOCOL_SHA256}:
        raise EvidenceError("dataset/protocol differs from the before-fitting freeze")


def verify_primary_source(data):
    if type(data) is not bytes or len(data) != SOURCE_BYTES or not data.startswith(b"%PDF-"):
        raise EvidenceError("primary source byte inventory mismatch")
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise EvidenceError("primary source SHA mismatch")
    return {"status": "EXACT_PRIMARY_PDF", "bytes": len(data), "sha256": SOURCE_SHA256}


def _number(value, name, minimum=0., positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceError(name + ": finite numeric scalar required")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise EvidenceError(name + ": unrepresentable scalar") from exc
    if not math.isfinite(number) or number < minimum or (positive and number <= minimum):
        raise EvidenceError(name + ": outside numeric domain")
    return number


def observations():
    """Fresh copies in SI units; frozen raw transcription remains unchanged."""
    _assert_frozen()
    def convert(rows):
        return [{"sample": sample, "depth_m": depth * .01,
                 "rate_m_per_year": rate * 1e-6, "reported_error_m_per_year": error * 1e-6}
                for sample, depth, rate, error in rows]
    return {"calibration": convert(CALIBRATION_RAW), "holdout": convert(HOLDOUT_RAW)}


def _rows(rows, minimum_count=1):
    if not isinstance(rows, (list, tuple)) or not minimum_count <= len(rows) <= MAX_POINTS:
        raise EvidenceError("bounded observation count required")
    output = []
    seen = set()
    for row in rows:
        if type(row) is not dict or set(row) != {"sample", "depth_m", "rate_m_per_year", "reported_error_m_per_year"}:
            raise EvidenceError("observation schema mismatch")
        name = row["sample"]
        if not isinstance(name, str) or not name or len(name) > 128 or name in seen:
            raise EvidenceError("unique bounded sample IDs required")
        seen.add(name)
        output.append({"sample": name, "depth_m": _number(row["depth_m"], "depth"),
                       "rate_m_per_year": _number(row["rate_m_per_year"], "rate", positive=True),
                       "reported_error_m_per_year": _number(row["reported_error_m_per_year"], "error", positive=True)})
    return output


def fit_calibration(rows):
    """Fit only explicit training observations; no global holdout access."""
    rows = _rows(rows, 3)
    ratios = [r["rate_m_per_year"] / r["reported_error_m_per_year"] for r in rows]
    if any(not math.isfinite(r) or r <= 0 for r in ratios):
        raise EvidenceError("unrepresentable relative-error weights")
    scale = max(ratios)
    weights = [(r / scale) ** 2 for r in ratios]
    if any(w == 0 for w in weights):
        raise EvidenceError("relative-error weights underflow")
    weight = math.fsum(weights)
    x = [r["depth_m"] for r in rows]
    y = [math.log(r["rate_m_per_year"]) for r in rows]
    try:
        mean_x = math.fsum(w * value for w, value in zip(weights, x)) / weight
        mean_y = math.fsum(w * value for w, value in zip(weights, y)) / weight
        variance_x = math.fsum(w * (value - mean_x) ** 2 for w, value in zip(weights, x))
        covariance = math.fsum(w * (a - mean_x) * (b - mean_y) for w, a, b in zip(weights, x, y))
    except (OverflowError, ValueError) as exc:
        raise EvidenceError("unrepresentable weighted fit") from exc
    if not math.isfinite(variance_x) or variance_x <= 0 or not math.isfinite(covariance):
        raise EvidenceError("at least two distinct resolved cover depths required")
    slope = min(0., covariance / variance_x)
    intercept = mean_y - slope * mean_x
    try:
        bare_rate = math.exp(intercept)
    except OverflowError as exc:
        raise EvidenceError("unrepresentable fitted bare rate") from exc
    _number(bare_rate, "fitted bare rate", positive=True)
    _number(-slope, "fitted decay")
    cover_scale = None if slope == 0 else _number(-1. / slope, "fitted cover scale", positive=True)
    return {"bare_rate_m_per_year": bare_rate, "decay_per_m": -slope,
            "cover_scale_m": cover_scale,
            "constant_boundary_fit": slope == 0,
            "depth_support_m": [min(x), max(x)], "calibration_ids": [r["sample"] for r in rows],
            "estimator": PROTOCOL["estimator"]}


def predict(model, depth_m):
    depth = _number(depth_m, "prediction depth")
    bare = _number(model["bare_rate_m_per_year"], "bare rate", positive=True)
    decay = _number(model["decay_per_m"], "decay")
    value = bare * math.exp(-decay * depth)
    return _number(value, "predicted rate", positive=True)


def evaluate(model, rows):
    rows = _rows(rows)
    records = []
    for row in rows:
        predicted = predict(model, row["depth_m"])
        residual = predicted - row["rate_m_per_year"]
        records.append({**row, "predicted_m_per_year": predicted,
            "residual_m_per_year": residual,
            "residual_over_reported_error": residual / row["reported_error_m_per_year"],
            "outside_calibration_depth_support": not model["depth_support_m"][0] <= row["depth_m"] <= model["depth_support_m"][1]})
    n = len(records)
    metrics = {"count": n, "bias_m_per_year": math.fsum(r["residual_m_per_year"] for r in records) / n,
        "mae_m_per_year": math.fsum(abs(r["residual_m_per_year"]) for r in records) / n,
        "rmse_m_per_year": math.hypot(*(r["residual_m_per_year"] for r in records)) / math.sqrt(n),
        "relative_rmse": math.hypot(*(r["residual_m_per_year"] / r["rate_m_per_year"] for r in records)) / math.sqrt(n),
        "reported_error_normalised_rmse": math.hypot(*(r["residual_over_reported_error"] for r in records)) / math.sqrt(n),
        "outside_depth_support_count": sum(r["outside_calibration_depth_support"] for r in records),
        "within_one_reported_error": sum(abs(r["residual_over_reported_error"]) <= 1 for r in records),
        "within_two_reported_errors": sum(abs(r["residual_over_reported_error"]) <= 2 for r in records)}
    if any(isinstance(v, float) and not math.isfinite(v) for v in metrics.values()):
        raise EvidenceError("unrepresentable evaluation metrics")
    return {"metrics": metrics, "observations": records}


def _material_operator_bridge(model, rows):
    # The supplied field density range is NOT used as an invented per-point
    # measurement. Unit-density zero-time bookkeeping isolates only P(h).
    if model["cover_scale_m"] is None:
        raise EvidenceError("constant-limit fit has no finite material-operator cover scale")
    p = materials.SoilProductionParameters(model["bare_rate_m_per_year"], model["cover_scale_m"],
        1., 0., 1., 0., 1., 0., 0., 1., "ENGINEERING UNIT-DENSITY ZERO-TIME RATE CHECK ONLY")
    errors = []
    for row in rows:
        got = materials.soil_production_step(area_m2=1., rock_available_kg=1., regolith_kg=0.,
            mobile_kg=row["depth_m"], duration_years=0., parameters=p).initial_rate_m_per_year
        errors.append(abs(got - predict(model, row["depth_m"])))
    return {"maximum_absolute_rate_difference_m_per_year": max(errors),
            "observed_density_or_mass_yield_validation": False, "duration_years": 0.}


def run_evidence():
    """Reproduce frozen split without I/O other than own implementation hashing."""
    _assert_frozen()
    paths = [Path(__file__).resolve(), Path(materials.__file__).resolve()]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    data = observations()
    model = fit_calibration(data["calibration"])
    result = {"status": "OBSERVATIONAL_COMPONENT_COMPARISON_COMPLETED", "identity": freeze_identity(),
        "source": {"url": SOURCE_URL, "bytes": SOURCE_BYTES, "sha256": SOURCE_SHA256,
            "access": "publisher supplement; small factual transcription; no PDF redistributed",
            "licence": "2012 Macmillan Publishers Limited; all rights reserved; no open-data licence found"},
        "protocol": deepcopy(PROTOCOL), "model": model,
        "calibration": evaluate(model, data["calibration"]), "holdout": evaluate(model, data["holdout"]),
        "material_operator_initial_rate_bridge": _material_operator_bridge(model, data["calibration"] + data["holdout"]),
        "physical_validation_passed": False, "full_landform_family_implemented": False,
        "diadem_coefficients_changed": False, "production_authorised": False,
        "independent_external_study_holdout": False, "observations_are_synthetic": False}
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if before != after:
        raise EvidenceError("executed implementation changed during comparison")
    _assert_frozen()
    result["implementation_sha256"] = after
    return result
