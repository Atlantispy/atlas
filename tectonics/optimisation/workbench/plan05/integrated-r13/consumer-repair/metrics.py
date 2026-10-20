"""Plan12 prediction and receipt adaptation; no dispatch, queue writes or sampling."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTEGRATION = HERE.parent
TASK = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
GIB = 1 << 30
MIB = 1 << 20
HISTORY_NAMES = ("h12-r1", "h1c-r4a")
ARRAYS = {"enthalpy_j", "input_capacity_j_k", "input_enthalpy_j",
          "input_source_w", "temperature_k"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(value, name, *, positive=False):
    require(type(value) in (int, float) and math.isfinite(value)
            and (value > 0 if positive else value >= 0),
            "Missing/invalid observed " + name)
    return value


def _read_json(path):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "Duplicate history key: " + key)
            value[key] = item
        return value

    def invalid(value):
        raise ValueError("Nonfinite history: " + value)

    return json.loads(Path(path).read_text(encoding="utf8"),
                      object_pairs_hook=pairs, parse_constant=invalid)


def _bound_writer(selection, writer):
    path = (INTEGRATION / "ab_heat_r13.py").resolve()
    require(Path(writer.__file__).resolve() == path
            and Path(writer.predict.__code__.co_filename).resolve() == path,
            "Prediction must use the selected writer.predict")
    sha = digest(path)
    require(selection["source_pins"].get(str(path)) == sha,
            "Prediction writer source changed or is unbound")
    require(selection["source_pins"].get(str(Path(__file__).resolve())) == digest(__file__),
            "Consumer metrics source changed or is unbound")
    return sha


def load_history(selection, writer):
    """Read precisely the two r2 histories, each pinned by the consumer selection."""
    writer_sha = _bound_writer(selection, writer)
    expected = [(TASK / "hs/evidence" / name / "summary.json").resolve()
                for name in HISTORY_NAMES]
    references = selection.get("prediction_history")
    require(isinstance(references, list) and len(references) == 2,
            "Exactly the two r2 prediction histories are required")
    rows = []
    for reference, path in zip(references, expected, strict=True):
        require(isinstance(reference, dict) and set(reference) == {"path", "sha256"}
                and Path(reference["path"]).is_absolute()
                and Path(reference["path"]).resolve() == path,
                "Prediction history differs from the exact r2 input route")
        require(reference["sha256"] == digest(path)
                and selection["source_pins"].get(str(path)) == reference["sha256"],
                "Prediction history changed or is not source-bound")
        document = _read_json(path)
        require(isinstance(document, dict) and isinstance(document.get("arms"), list)
                and all(isinstance(arm, dict) for arm in document["arms"]),
                "Malformed prediction history")
        rows.extend((str(path), arm) for arm in document["arms"])
    return dict(rows=rows, inputs=deepcopy(references), writer_sha256=writer_sha)


def _decimal_environment(name):
    try:
        value = Decimal(os.environ.get(name, "0"))
    except InvalidOperation as error:
        raise ValueError("Invalid queue resource environment: " + name) from error
    require(value.is_finite() and value > 0, "Missing queue resource environment: " + name)
    return value


def predict_arm(selection, writer, arm, history, completed, *, cli_gib=None):
    """Return the per-arm gate; the owned launcher performs the bounded wait.

    Existing writer.predict alone decides which mode/layout/input/worker history
    matches. Proof records never become time/prof measurements. Missing input in
    the two old files retains only that predictor's established W4 default.
    """
    require(_bound_writer(selection, writer) == history["writer_sha256"],
            "Writer changed after history loading")
    require(arm["mode"] in ("time", "prof"), "Consumer prediction mode differs")
    # The full gate already checks current source pins at every arm boundary;
    # retain and verify the exact history references associated with this cache.
    require(history["inputs"] == selection.get("prediction_history"),
            "Prediction history selection changed")
    predicted, basis = writer.predict(
        arm, history["rows"] + [("this run", item) for item in completed], cli_gib)
    require(type(predicted) in (int, float) and math.isfinite(predicted) and predicted > 0,
            "Start gate: no positive finite peak prediction; " + str(basis))
    require(isinstance(basis, str) and basis.strip(), "Prediction basis missing")
    raw_gate = predicted * 1.2 + 2
    require(math.isfinite(raw_gate), "Prediction start gate overflowed")
    queue_gate = round(raw_gate, 1)
    # Preserve the queue's decimal booking boundary, not a binary64 artefact.
    require(_decimal_environment("RUNQ_TICKET_GIB") >= Decimal(str(predicted)),
            "Queue booking below dynamic prediction")
    require(_decimal_environment("RUNQ_MEM_NEED_GIB") >= Decimal(str(queue_gate)),
            "Queue memory admission below dynamic prediction")
    need = max(raw_gate, queue_gate)
    return dict(input=writer.INPUT, predicted_peak_gib=predicted,
                prediction_basis=basis, prediction_history=deepcopy(history["inputs"]),
                prediction_writer_sha256=history["writer_sha256"],
                start_gate_gib=need, required_start_gate_bytes=math.ceil(need * GIB),
                wait_policy=dict(interval_seconds=15, maximum_seconds=600,
                                 effective_maximum_seconds=120,
                                 effective_limit_basis="Later queue protocol safeguard"))


def start_observation(prediction, *, available_bytes, waited_seconds):
    """Record real availability/wait; retain refused observations before raising."""
    number(available_bytes, "available bytes")
    number(waited_seconds, "gate wait seconds")
    # Preserve actual clock observations, including scheduler overshoot at the
    # deadline. The supervisor stops waiting at the effective limit.
    return dict(free_gib_at_start=available_bytes / GIB, gate_waited_s=waited_seconds,
                gate_wait_limit_reached=waited_seconds >=
                prediction["wait_policy"]["effective_maximum_seconds"],
                start_gate_passed=available_bytes >= prediction["required_start_gate_bytes"])


def _sha(value, name):
    require(isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value),
            "Missing/invalid native " + name)
    return value


def summary_metrics(native_arm, process_stage, *, machine_busy_cpu_seconds):
    """Copy real native observations without inventing an observed PID count.

    parent_peak_mib is the native caller's OS high-water mark; worker_peak_mib
    is the largest native worker-reported high-water mark. They are not the old
    r8 sampled launcher/group peaks. The complete owned-job sampled peak remains
    independent, and writer.predict takes the greater estimate as before.
    """
    ab = native_arm["ab"]
    calls = ab["calls"]
    require(isinstance(calls, list) and len(calls) == 2, "Two native heat-call receipts required")
    busy = number(machine_busy_cpu_seconds, "machine busy CPU seconds")
    wall = number(process_stage["wall_seconds"], "whole-arm wall seconds", positive=True)
    tree = number(process_stage["peak_sampled_tree_rss_bytes"], "owned-job tree peak bytes")
    free = number(process_stage["free_low_bytes"], "owned-job minimum free bytes")
    parent_cpu = number(ab["parent_cpu_seconds"], "parent CPU seconds")
    parent_peak = number(ab["parent_peak_working_set"], "native parent peak bytes", positive=True)
    worker_cpu = [number(call["worker_compute_seconds"], "worker CPU seconds") for call in calls]
    worker_peaks = [number(call["worker_working_set_peak_max"], "native worker peak bytes",
                           positive=True) for call in calls]
    reconstruction = [number(call["seconds"], "reconstruction seconds") for call in calls]
    legacy = number(native_arm["legacy"]["seconds"], "legacy seconds")
    compact = number(native_arm["compact"]["seconds"], "compact seconds")
    exact = _sha(ab["exact_growth_sha256"], "exact-growth identity")
    resources = _sha(ab["gmp_resources_sha256"], "resource-helper identity")
    arrays = native_arm["arrays"]
    require(isinstance(arrays, dict) and set(arrays) == ARRAYS, "Five native array identities required")
    for name, identity in arrays.items():
        _sha(identity, "array identity " + name)
    result_id = _sha(native_arm["compact"]["result_id"], "result identity")
    own = parent_cpu + sum(worker_cpu)
    return dict(
        status=native_arm["status"], leaks=len(ab["leaks"]),
        used=[call["workers"] for call in calls], fallback=[call["fallback"] for call in calls],
        legacy_s=legacy, compact_s=compact, recon_s=reconstruction, worker_cpu_s=worker_cpu,
        parent_cpu_seconds=parent_cpu, accounted_cpu_seconds=own,
        machine_busy_cpu_seconds=busy,
        other_load_cpus=(busy - own) / wall,
        other_load_basis="Observed machine busy delta minus native parent CPU and worker compute CPU, "
                         "divided by owned-arm wall time; includes unaccounted process/OS work and "
                         "sampling-window differences, is not an isolated external-load measurement.",
        arm_wall_seconds=wall, tree_peak_mib=tree / MIB, available_low_mib=free / MIB,
        parent_peak_mib=parent_peak / MIB, worker_peak_mib=max(worker_peaks) / MIB,
        parent_peak_working_set_bytes=parent_peak, worker_peak_bytes_by_call=worker_peaks,
        parent_peak_basis="Native caller OS peak working set; excludes launcher wrappers.",
        worker_peak_basis="Largest reported native worker OS peak working set; excludes launcher wrappers.",
        worker_processes=None,
        worker_processes_basis="Distinct worker PIDs are not present in the retained native receipt.",
        arrays=deepcopy(arrays), result_id=result_id,
        exact_growth=exact[:12], exact_growth_sha256=exact,
        gmp_resources=resources[:12], gmp_resources_sha256=resources)
