"""Bounded read-only report of parent-process developer timing checkpoints.

Exact means integer accounting of the emitted clock boundaries, not scientific
acceptance or whole-process-tree measurement. No run discovery or payload reads.
"""
import argparse
import json
import math
from pathlib import Path


EVENT_SCHEMA = 'atlas.dev-stage-timing.events.v1'
REPORT_SCHEMA = 'atlas.dev-stage-timing.report.v1'
GUARD_SCHEMA = 'atlas.private.continuation-guard.r3'
MAX_LINE_BYTES = 16 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_GUARD_BYTES = 2 * 1024 * 1024
MAX_SUMMARY_BYTES = 512 * 1024
MAX_AGGREGATES = 256
MAX_INTEGER = (1 << 63) - 1
MEMORY_FIELDS = frozenset(('parent_rss_bytes', 'parent_private_bytes',
    'parent_os_peak_working_set_bytes', 'parent_os_peak_pagefile_bytes',
    'logical_reserved_bytes'))
COMMON = frozenset(('event', 'seq', 'wall_ns', 'cpu_ns'))
FIELDS = {
    'session_start': frozenset(('schema', 'pid', 'phase', 'metadata')),
    'checkpoint': frozenset(('name',)),
    'session_end': frozenset(('phase', 'workload_status', 'closed')),
}


class InvalidEvidence(ValueError):
    """A bounded record cannot be reconciled under the known protocol."""


def _require(condition, reason):
    if not condition:
        raise InvalidEvidence(reason)


def _integer(value, label, minimum=0):
    _require(type(value) is int and minimum <= value <= MAX_INTEGER,
             label + ' must be a bounded nonnegative integer')


def _name(value, label):
    _require(isinstance(value, str) and 1 <= len(value) <= 256,
             label + ' must contain 1 to 256 characters')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate JSON object key')
        result[key] = value
    return result


def _constant(_value):
    raise InvalidEvidence('non-finite JSON number')


def _decode(raw):
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                          parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        if isinstance(error, InvalidEvidence):
            raise
        raise InvalidEvidence('invalid UTF-8 or JSON record') from error


def _metadata(value):
    _require(type(value) is dict and len(value) <= 32, 'metadata must be a bounded scalar object')
    for key, item in value.items():
        _name(key, 'metadata key')
        _require(item is None or type(item) in (str, bool, int, float), 'metadata must contain scalars only')
        if isinstance(item, str):
            _require(len(item) <= 1024, 'metadata string exceeds bound')
        elif type(item) is int:
            _require(abs(item) <= MAX_INTEGER, 'metadata integer exceeds bound')
        elif type(item) is float:
            _require(math.isfinite(item), 'metadata number must be finite')


def _validate_shape(event):
    _require(type(event) is dict, 'event must be an object')
    kind = event.get('event')
    _require(isinstance(kind, str) and kind in FIELDS, 'unknown event type')
    required = COMMON | FIELDS[kind]
    optional = {'memory'}
    _require(required <= event.keys() and event.keys() <= required | optional,
             'missing or foreign event fields')
    for key in ('seq', 'wall_ns', 'cpu_ns'):
        _integer(event[key], key)
    if 'memory' in event:
        memory = event['memory']
        _require(type(memory) is dict and memory.keys() <= MEMORY_FIELDS, 'foreign memory fields')
        for value in memory.values():
            if value is not None:
                _integer(value, 'memory observation')
    for key in ('name', 'phase'):
        if key in event:
            _name(event[key], key)
    if kind == 'session_start':
        _require(event['schema'] == EVENT_SCHEMA, 'foreign event schema')
        _integer(event['pid'], 'pid', 1)
        _metadata(event['metadata'])
        _require(event['seq'] == event['wall_ns'] == event['cpu_ns'] == 0
                 and event['phase'] == 'startup', 'invalid session start boundary')
    elif kind == 'session_end':
        _require(event['closed'] is True and event['workload_status'] in ('ok', 'error'),
                 'invalid session end marker')
        expected = 'timing-finalisation' if event['workload_status'] == 'ok' else 'incomplete-subsection'
        _require(event['phase'] == expected, 'session end subsection differs from workload status')


class _Accounting:
    def __init__(self):
        self.last = None
        self.session = None
        self.last_checkpoint = None
        self.phases = {}
        self.closed = False
        self.memory_count = 0
        self.memory_max = {}
        self.memory_latest = None

    def accept(self, event):
        """Validate the entire event before changing any valid-prefix accounting."""
        _validate_shape(event)
        kind = event['event']
        if self.last is None:
            _require(kind == 'session_start', 'first event must be session_start')
        else:
            _require(not self.closed, 'record follows session_end')
            _require(kind != 'session_start', 'duplicate session_start')
            _require(event['seq'] == self.last['seq'] + 1, 'non-contiguous sequence')
            _require(event['wall_ns'] >= self.last['wall_ns']
                     and event['cpu_ns'] >= self.last['cpu_ns'], 'clock regressed')
        interval_name = event['name'] if kind == 'checkpoint' else event['phase'] if kind == 'session_end' else None
        additions = int(interval_name is not None and interval_name not in self.phases)
        _require(len(self.phases) + additions <= MAX_AGGREGATES,
                 'phase aggregate bound exceeded')

        if interval_name is not None:
            phase = self.phases.setdefault(interval_name, dict(phase=interval_name, visits=0, wall_ns=0,
                process_cpu_ns=0, completed=True,
                memory_observations=dict(events_with_memory=0, observed_maxima={})))
            phase['wall_ns'] += event['wall_ns'] - self.last['wall_ns']
            phase['process_cpu_ns'] += event['cpu_ns'] - self.last['cpu_ns']
            phase['visits'] += 1
            phase['completed'] = phase['completed'] and (kind == 'checkpoint' or event['workload_status'] == 'ok')
        if kind == 'session_start':
            self.session = dict(pid=event['pid'], metadata=event['metadata'])
        elif kind == 'checkpoint':
            self.last_checkpoint = event['name']
        elif kind == 'session_end':
            self.closed = True
        if 'memory' in event:
            self.memory_count += 1
            self.memory_latest = dict(seq=event['seq'], wall_ns=event['wall_ns'], values=event['memory'])
            # Initial-session samples are global observations only. A closing
            # checkpoint's memory belongs to the interval that just finished.
            phase_memory = None if interval_name is None else self.phases[interval_name]['memory_observations']
            if phase_memory is not None:
                phase_memory['events_with_memory'] += 1
            for key, value in event['memory'].items():
                if value is not None:
                    self.memory_max[key] = max(value, self.memory_max.get(key, 0))
                    if phase_memory is not None:
                        maxima = phase_memory['observed_maxima']
                        maxima[key] = max(value, maxima.get(key, 0))
        self.last = event

    def report(self):
        wall = 0 if self.last is None else self.last['wall_ns']
        cpu = 0 if self.last is None else self.last['cpu_ns']
        stage_wall = sum(row['wall_ns'] for row in self.phases.values())
        stage_cpu = sum(row['process_cpu_ns'] for row in self.phases.values())
        assert stage_wall == wall and stage_cpu == cpu
        return dict(session=self.session, coverage=dict(
            valid_events=0 if self.last is None else self.last['seq'] + 1,
            through_seq=None if self.last is None else self.last['seq'],
            through_event=None if self.last is None else self.last['event'],
            wall_ns=wall, process_cpu_ns=cpu, session_end_observed=self.closed,
            workload_status=self.last['workload_status'] if self.closed else None),
            stages=dict(scope='Exact parent-process intervals ending at explicit subsection checkpoints; process CPU excludes children. Session end accounts for finalisation or the incomplete subsection. Uncheckpointed work after the last valid event has no measured duration; no running-subsection estimate is made.',
                memory_scope='Per-stage checkpoint observations only; sampled maxima are not actual phase or global peaks. Checkpoint samples belong to the subsection that just finished; initial-session samples are global only. Null or absent values are unknown, not zero. OS counters retain process-lifetime scope.',
                last_completed_subsection=self.last_checkpoint, rows=list(self.phases.values()),
                summed_wall_ns=stage_wall, summed_process_cpu_ns=stage_cpu, reconciled=True),
            memory_observations=dict(scope='Event-boundary parent observations only; maxima are not global peaks. OS peak counters are parent OS-lifetime observations, not phase-local or simultaneous tree peaks. Logical reserved bytes are accounting, not physical RAM.',
                events_with_memory=self.memory_count, observed_maxima=self.memory_max, latest=self.memory_latest))


def _bounded_tree(value, depth=0, budget=None):
    if budget is None:
        budget = [8192]
    budget[0] -= 1
    _require(depth <= 8 and budget[0] >= 0, 'guard summary nesting or item bound exceeded')
    if isinstance(value, dict):
        _require(len(value) <= 256, 'guard summary object bound exceeded')
        for key, item in value.items():
            _name(key, 'guard summary key')
            _bounded_tree(item, depth+1, budget)
    elif isinstance(value, list):
        _require(len(value) <= 256, 'guard summary list bound exceeded')
        for item in value:
            _bounded_tree(item, depth+1, budget)
    else:
        _require(value is None or type(value) in (str, bool, int, float), 'invalid guard summary value')
        if isinstance(value, str):
            _require(len(value) <= 2048, 'guard summary string bound exceeded')
        elif type(value) is int:
            _require(abs(value) <= MAX_INTEGER, 'invalid guard summary number')
        elif type(value) is float:
            _require(math.isfinite(value) and abs(value) <= MAX_INTEGER, 'invalid guard summary number')


def _guard_evidence(path, session):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_GUARD_BYTES+1)
    _require(len(raw) <= MAX_GUARD_BYTES, 'guard receipt exceeds byte bound')
    receipt = _decode(raw)
    _require(type(receipt) is dict and receipt.get('schema') == GUARD_SCHEMA, 'foreign guard receipt schema')
    _require(session is not None, 'guard cannot bind without valid session_start')
    parent = receipt.get('parent')
    binding = 'UNVERIFIED: receipt has no parent PID; explicit file selection only'
    if parent is not None:
        _require(type(parent) is dict, 'invalid guard parent identity')
        if 'pid' in parent:
            _integer(parent['pid'], 'guard parent pid', 1)
            _require(parent['pid'] == session['pid'], 'guard parent PID differs from timing session')
            binding = 'Parent PID matches; PID alone does not prove process-creation identity or session lifetime'
    summary = receipt.get('resource_summary')
    _require(type(summary) is dict and summary.get('schema') == 'atlas.private.resource-summary.r1',
             'missing or foreign guard resource summary')
    _require(set(summary) <= {'schema', 'samples', 'peak_scope', 'cpu_scope', 'child_scope',
        'phase_scope', 'overlapping_identity_cpu_seconds', 'latest', 'peaks', 'phase_limit',
        'phase_overflow_samples', 'phases'}, 'foreign guard summary fields')
    _bounded_tree(summary)
    _require(len(json.dumps(summary, allow_nan=False).encode('utf-8')) <= MAX_SUMMARY_BYTES,
             'guard resource summary exceeds byte bound')
    return dict(status='SAMPLED_EVIDENCE_ONLY', binding=binding,
        scope='Separate sampled process-tree evidence; never added to exact parent CPU or used as scientific acceptance. Consecutive-sample CPU misses first observations and exited-process tails; phase transitions and RAM peaks are sampled. OS peaks are per-process lifetime counters, not simultaneous tree or phase peaks.',
        resource_summary=summary)


def build_report(path, *, guard_path=None):
    """Stream one explicit event log; refuse foreign data and retain valid prefix."""
    accounting = _Accounting()
    status = 'INCOMPLETE'
    issues = []
    bytes_read = 0
    line_number = 0
    try:
        with Path(path).open('rb') as stream:
            while True:
                raw = stream.readline(MAX_LINE_BYTES+1)
                if not raw:
                    break
                line_number += 1
                bytes_read += len(raw)
                _require(bytes_read <= MAX_FILE_BYTES, 'event file exceeds byte bound')
                _require(len(raw) <= MAX_LINE_BYTES, 'event line exceeds byte bound')
                if not raw.endswith(b'\n'):
                    issues.append(dict(line=line_number, reason='final incomplete line excluded'))
                    break
                accounting.accept(_decode(raw))
        if not issues:
            if accounting.closed:
                status = 'COMPLETE'
            else:
                issues.append(dict(line=line_number, reason='session_end missing; coverage stops at last valid event'))
    except (OSError, InvalidEvidence) as error:
        status = 'REFUSED'
        issues.append(dict(line=line_number, reason=str(error)[:512]))
    result = dict(schema=REPORT_SCHEMA, status=status,
        acceptance='Developer diagnostic only; no scientific acceptance, guard-policy decision or full-run completion inferred from process exit or timestamps.',
        bounds=dict(line_bytes=MAX_LINE_BYTES, file_bytes=MAX_FILE_BYTES,
            phase_aggregates=MAX_AGGREGATES),
        bytes_read=bytes_read, issues=issues, **accounting.report())
    result['coverage']['status'] = 'COMPLETE' if status == 'COMPLETE' else 'INCOMPLETE'
    if guard_path is not None:
        try:
            result['guard_sampled_evidence'] = _guard_evidence(guard_path, accounting.session)
        except (OSError, InvalidEvidence) as error:
            result['guard_sampled_evidence'] = dict(status='REFUSED', reason=str(error)[:512])
            result['status'] = 'REFUSED'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', required=True, type=Path)
    parser.add_argument('--guard-receipt', type=Path)
    args = parser.parse_args(argv)
    report = build_report(args.events, guard_path=args.guard_receipt)
    print(json.dumps(report, allow_nan=False, sort_keys=True))
    return 0 if report['status'] == 'COMPLETE' else 2


if __name__ == '__main__':
    raise SystemExit(main())
