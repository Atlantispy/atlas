"""By-need start gate: the one source of the guarded runner's memory limits and its start gate.

Michael, 16 Oct 2026: start gates by need (~14:05), and "I don't trust the 10GB amount" (~18:3x). With his
applications open the machine idles at about 8-9 GB available, so the blanket 10 GiB start gate refused every
route (1) stage at preflight. It is replaced by the queue's own rule (runq mem_need):

    gate = predicted peak + ceil(predicted peak / 5) + 1 GiB free floor + 1 GiB allowance

The allowance leaves room for small jobs that start after this one. The predicted peak is the largest
guard-sampled tree peak of a completed PASS of the same step, stage and interval, from the run records the
caller names. Only when there is no such record does an explicit declared booking stand in, as in runq; with
neither, the gate refuses. Nothing is defaulted, and a record that is not a completed PASS of that step, stage
and interval is refused rather than skipped (the caller reads its own records and passes their peaks here).

The in-run guards are unchanged and are what protect the machine: 12 GiB tree RSS, 1 GiB available floor and
the 16 GiB logical budget. A prediction that is too low can only start a run that those guards then stop
cleanly; it cannot change a result. A gate above the available memory refuses before the caller writes any
output.

Production also requires seed 0 (parallel_binding raises without it; parallel_selection silently falls back to
serial under a random seed), so every stage start is admitted only when hash randomisation is off, and the
admitted record carries that flag.

Route (1) (launch_fresh_interval, run_fresh_interval, reopen_fresh_restart): stage_peaks reads the launcher's
own stage records, the launcher decides and admits before it writes anything, and hands the decision to each
guarded child (ARGUMENT); the child admits it again against its own free memory at its start and records the
admitted dict, with start_available_bytes in its guard_limits holding that gate.
"""
import json
import sys
from hashlib import sha256
from pathlib import Path

RSS_BYTES, FREE_BYTES, LOGICAL_BYTES = 12 << 30, 1 << 30, 16 << 30
ALLOWANCE_BYTES = 1 << 30
SCHEMA = 'atlas.private.start-gate.r1'
MEASURED, BOOKING = 'largest measured peak of a completed PASS', 'declared booking (no completed PASS record)'


class StartGateRefused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise StartGateRefused(message)


def _bytes(value):
    return type(value) is int and value > 0


def gate_bytes(predicted_peak_bytes):
    """The predicted peak with a fifth more (rounded up), the free floor and the allowance, in exact bytes."""
    require(_bytes(predicted_peak_bytes), 'the start gate needs a positive integer predicted peak')
    return predicted_peak_bytes + -(-predicted_peak_bytes // 5) + FREE_BYTES + ALLOWANCE_BYTES


def decide(key, *, measured=(), booking=None):
    """The prediction and gate for one step of one stage and interval; refuses when it has no prediction.

    ``key``: what the records must match (for example step, stage and interval), recorded as given.
    ``measured``: (source, peak bytes) for every completed PASS record of that key the caller read; the source
    names the record (path and SHA-256). ``booking``: None, or (bytes, basis) declared by whoever launches.
    """
    require(type(key) is dict and key and all(type(name) is str for name in key), 'an explicit gate key is required')
    measured = list(measured)
    require(all(type(item) is tuple and len(item) == 2 and type(item[0]) is str and item[0] and _bytes(item[1])
                for item in measured), 'each measured peak needs its record and positive integer bytes')
    require(len({source for source, _ in measured}) == len(measured), 'a record was given twice')
    if booking is not None:
        require(type(booking) is tuple and len(booking) == 2 and _bytes(booking[0]) and type(booking[1]) is str
                and booking[1].strip(), 'a declared booking needs positive integer bytes and its basis')
    if measured:
        predicted, basis = max(peak for _, peak in measured), MEASURED
    elif booking is not None:
        predicted, basis = booking[0], BOOKING
    else:
        raise StartGateRefused('no completed PASS record of %s and no declared booking: the start gate has no '
                               'prediction and refuses (there is no default)' % (key,))
    return {'schema': SCHEMA, 'key': dict(key), 'predicted_peak_bytes': predicted, 'basis': basis,
            'measured': [{'record': source, 'peak_bytes': peak} for source, peak in measured],
            'booking': None if booking is None else {'bytes': booking[0], 'basis': booking[1],
                                                     'used': not measured},
            'gate_bytes': gate_bytes(predicted), 'margin': '1/5', 'free_floor_bytes': FREE_BYTES,
            'allowance_bytes': ALLOWANCE_BYTES}


def admit(decision, available_bytes, flags=None):
    """The decision with this start's available memory and seed flag; refuses a random seed or a gate above it.

    ``flags``: the interpreter's sys.flags unless given (tests pass a stand-in).
    """
    flags = sys.flags if flags is None else flags
    require(getattr(flags, 'hash_randomization', None) == 0,
            'production requires seed 0: run with PYTHONHASHSEED=0 and without -I or -E')
    gate = decision.get('gate_bytes') if type(decision) is dict else None
    if not (type(gate) is int and decision.get('schema') == SCHEMA and decision.get('basis') in (MEASURED, BOOKING)
            and gate == gate_bytes(decision.get('predicted_peak_bytes'))):
        raise StartGateRefused('start gate decision differs from its own prediction')
    if not (type(available_bytes) is int and available_bytes >= gate):
        raise StartGateRefused('start gate refused: %s bytes available, the gate is %d (predicted peak %d bytes, '
                               '%s)' % (available_bytes, gate, decision['predicted_peak_bytes'], decision['basis']))
    return dict(decision, available_bytes=available_bytes, hash_randomization=0)


STAGE_SCHEMA = 'atlas.private.fresh-interval-stage.r1'
STAGE_PASS = ('ADOPTED', 'ADOPTED_WIDTH_GATE_STOP_BEFORE_INTERVAL_2')
STAGE_STEPS = ('runner', 'reader', 'finalise', 'adopt')
GUARDED_STEPS = ('runner', 'reader')
# The guard (private_heat_continuation_guard_r3) samples {parent_rss, process_tree_rss}; the gate predicts the tree.
TREE_PEAK = 'process_tree_rss'
ARGUMENT = '--start-gate'


def stage_key(stage, interval):
    """The gate key of one route (1) stage: its name and interval number."""
    require(type(stage) is str and stage and type(interval) is int and interval >= 0,
            'a route (1) gate key needs the stage name and a non-negative integer interval')
    return {'route': 'fresh-interval', 'stage': stage, 'interval': interval}


def _stage_peak(record, key):
    """The larger guarded step's sampled peak of a completed PASS record of key's stage and interval, else None."""
    steps = record.get('steps') if type(record) is dict else None
    if not (type(steps) is list and all(type(step) is dict for step in steps) and
            tuple(step.get('name') for step in steps) == STAGE_STEPS and all(step.get('ok') is True for step in steps)
            and record.get('schema') == STAGE_SCHEMA and record.get('status') in STAGE_PASS and
            record.get('stage') == key['stage'] and type(record.get('interval')) is int and
            record.get('interval') == key['interval']):
        return None
    resources = [step.get('resources') for step in steps if step['name'] in GUARDED_STEPS]
    samples = [item.get('sampled_peak_bytes') if type(item) is dict else None for item in resources]
    peaks = [sample.get(TREE_PEAK) if type(sample) is dict else None for sample in samples]
    sized = [peak for peak in peaks if type(peak) is int and peak > 0]
    return max(sized) if sized and len(sized) == len(peaks) else None


def stage_peaks(paths, key):
    """(source, peak) for decide() from the stage records a launcher was given (--peak-record).

    Each record must be a completed PASS of key's stage and interval: the stage schema, status ADOPTED (or the
    width gate stop, which is adopted too), its four steps in order and all ok, and both guarded steps with a
    positive integer guard-sampled process-tree peak (resources.sampled_peak_bytes.process_tree_rss). Its peak
    is the larger of the two, the stage peak. A record that does
    not qualify refuses; it is never skipped. The source is the resolved path and the SHA-256 of the bytes read.
    """
    require(type(paths) in (list, tuple), 'stage records are given as a list of paths')
    found = []
    for path in paths:
        path = Path(path).resolve()
        raw = path.read_bytes()
        try:
            record = json.loads(raw)
        except ValueError:
            record = None
        peak = _stage_peak(record, key)
        require(peak is not None, 'not a completed PASS record of stage %r interval %r: %s' % (
            key['stage'], key['interval'], path))
        found.append(('%s sha256=%s' % (path, sha256(raw).hexdigest()), peak))
    return found


def stage_decision(key, *, records=(), booking_bytes=None, booking_basis=None):
    """decide() for one route (1) stage from its named records and a declared booking (both parts or neither)."""
    require((booking_bytes is None) == (booking_basis is None),
            'a declared booking needs both --booking-bytes and --booking-basis')
    booking = None if booking_bytes is None else (booking_bytes, booking_basis)
    return decide(key, measured=stage_peaks(records, key), booking=booking)


def add_arguments(parser):
    """The by-need gate's launch options; a booking is used only when no record is given."""
    parser.add_argument('--peak-record', type=Path, action='append', default=[], dest='peak_records',
                        help='a completed PASS stage-<stage>.json of the same stage and interval (repeatable)')
    parser.add_argument('--booking-bytes', type=int, help='declared stage peak in bytes, used only without a record')
    parser.add_argument('--booking-basis', help='where that booking comes from (recorded with it)')


def encode(decision):
    """The decision as the one compact JSON value that follows ARGUMENT in a guarded child's command."""
    return json.dumps(decision, sort_keys=True, separators=(',', ':'), allow_nan=False)


def child_admit(text, available_bytes, flags=None):
    """A guarded child's start: its launcher's decision, admitted again against this process's free memory."""
    require(type(text) is str, 'this run has no start gate decision: launch it with --peak-record or a booking')
    try:
        decision = json.loads(text)
    except ValueError:
        decision = None
    return admit(decision, available_bytes, flags)


def guard_limits(admitted):
    """The receipts' guard_limits: the unchanged in-run guards, and start_available_bytes = this start's gate."""
    return {'rss_bytes': RSS_BYTES, 'free_floor_bytes': FREE_BYTES, 'start_available_bytes': admitted['gate_bytes'],
            'logical_budget_bytes': LOGICAL_BYTES}
