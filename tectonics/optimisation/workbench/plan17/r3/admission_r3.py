"""Exact, source-bound Plan17 start admission. Importing this module dispatches nothing.

The shared start gate owns integer memory decisions/admission. Queue predictions
qualify only through one active job-tracked ancestor and this exact request-SHA
command key. A named malformed/mismatched prediction refuses; none is clipped.
"""
import ast
from decimal import Decimal, DecimalException, ROUND_CEILING, localcontext
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
R = T / 'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
SHARED = R / 'start_gate.py'
SHARED_SHA256 = '16e448d60556acabc337c4ff7b39649d7ab8110aa5585ec6a82262e1838f6345'
RUNQ = T / 'q/runq.py'
RUNQ_SHA256 = '151c6a6bdb4f794ce26f3f99fc87fbe14e3c35cac9ee3ce7ed54288575b01e52'
BOOKING_BASIS = 'booking (no earlier job-tracked run of this command)'
GIB = 1 << 30


def _require(condition, message):
    if not condition:
        raise ValueError('Plan17 admission refused: ' + message)


def _read(path, expected=None):
    raw = Path(path).read_bytes()
    digest = sha256(raw).hexdigest()
    _require(expected is None or digest == expected, 'changed admission source: ' + str(path))
    return raw, dict(path=str(Path(path).resolve()), sha256=digest)


def load_shared():
    raw, _ = _read(SHARED, SHARED_SHA256)
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader('plan17_start_gate_r2', loader=None))
    exec(compile(raw, str(SHARED), 'exec'), module.__dict__)
    return module


def decimal_value(value, name):
    _require(type(value) in (str, int, Decimal) and type(value) is not bool,
             name + ' must be an exact decimal value')
    try:
        number = Decimal(value)
    except (DecimalException, ValueError, OverflowError):
        raise ValueError('Plan17 admission refused: invalid ' + name) from None
    _require(number.is_finite() and number > 0, name + ' must be positive and finite')
    return number


def gib_bytes(value):
    """Conservative ceil(decimal GiB * 2**30), with enough precision for the exact product."""
    number = decimal_value(value, 'GiB prediction')
    try:
        with localcontext() as context:
            context.prec = max(28, len(number.as_tuple().digits) + 12)
            return int((number * GIB).to_integral_value(rounding=ROUND_CEILING))
    except (DecimalException, ValueError, OverflowError):
        raise ValueError('Plan17 admission refused: GiB prediction cannot be converted exactly') from None


def read_json(raw):
    def invalid(value):
        raise ValueError('Plan17 admission refused: non-finite JSON ' + value)
    def unique_members(pairs):
        found = {}
        for name, value in pairs:
            if name in found:
                raise ValueError('Plan17 admission refused: duplicate JSON member ' + repr(name))
            found[name] = value
        return found
    return json.loads(raw, parse_float=Decimal, parse_constant=invalid,
                      object_pairs_hook=unique_members)


def command_binding(manifest, phase, manifest_path, manifest_sha256, dispatcher, argv):
    """Bind runq's actual normaliser to the authorised eleven-token dispatcher command.

    Only the pinned cmd_key function is extracted; the queue module is not imported.
    The independently explicit full key must fit below its 400-character truncation.
    """
    manifest_path, dispatcher = Path(manifest_path).resolve(), Path(dispatcher).resolve()
    _require(re.fullmatch('[0-9a-f]{64}', manifest_sha256) is not None, 'request SHA-256 is invalid')
    raw, request = _read(manifest_path, manifest_sha256)
    _require(json.loads(raw) == manifest, 'loaded request differs from its source bytes')
    _require(phase['ticket'] in ('q23', 'q24') and manifest['phases'][phase['ticket']] == phase,
             'phase is not the request-bound long proof')
    expected = [str(T / '.r44-env/Scripts/python.exe'), '-B', '-s', '-P', str(dispatcher),
                '--manifest', str(manifest_path), '--sha256', manifest_sha256, '--phase', phase['ticket']]
    _require(type(argv) in (list, tuple) and len(argv) == len(expected), 'unexpected dispatcher argv')
    for index, (actual, wanted) in enumerate(zip(argv, expected, strict=True)):
        _require(type(actual) is str and (Path(actual).resolve() == Path(wanted).resolve()
                 if index in (0, 4, 6) else actual == wanted), 'dispatcher argv/source mismatch')
    for path in (Path(argv[0]), dispatcher, manifest_path):
        _require(path.is_absolute() and path.is_file(), 'dispatcher command path is not an existing absolute file')
    full_key = ' '.join([Path(argv[0]).name, '-B', '-s', '-P', dispatcher.name, '--manifest',
                         manifest_path.name, '--sha256', manifest_sha256, '--phase', phase['ticket']])
    _require(len(full_key) < 400 and manifest_sha256 in full_key.split(),
             'source-bound command key would be truncated or omit the request SHA')
    source, queue_source = _read(RUNQ, RUNQ_SHA256)
    functions = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
                 and node.name == 'cmd_key']
    _require(len(functions) == 1, 'queue command normaliser is ambiguous')
    scope = {'os': os}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(RUNQ), 'exec'), scope)
    _require(scope['cmd_key'](list(argv)) == full_key, 'queue command key differs from the complete dispatch key')
    commands = json.dumps(phase['commands'], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    _, dispatcher_source = _read(dispatcher)
    _require(manifest['pins'].get(str(dispatcher)) == dispatcher_source['sha256'],
             'dispatcher is not pinned by the request')
    return dict(request=request, dispatcher=dispatcher_source, commands_sha256=sha256(commands).hexdigest(),
                cmd_key=full_key, argv=list(argv), queue_source=queue_source)


def admit_snapshot(phase, binding, queue, queue_source, ancestors, environment, available_bytes,
                   *, peaks=None, peaks_source=None, flags=None, shared=None):
    """Pure boundary for synthetic controls: no queue writes, processes or memory query."""
    SG = load_shared() if shared is None else shared
    _require(type(queue) is dict and type(queue.get('tickets')) is list and not queue.get('hold'),
             'queue is held or malformed')
    _require(type(ancestors) in (set, frozenset) and all(type(pid) is int and pid > 0 for pid in ancestors),
             'invalid queue ancestry snapshot')
    _require(all(type(row) is dict for row in queue['tickets']), 'malformed queue ticket')
    rows = [row for row in queue['tickets'] if row.get('status') == 'running'
            and row.get('runner_pid') in ancestors and row.get('tracker') == 'job']
    _require(len(rows) == 1, 'need exactly one running job-tracked queue ancestor')
    row = rows[0]
    _require(sum(item.get('id') == phase['ticket'] for item in queue['tickets']) == 1,
             'ticket identity is missing or duplicated')
    _require(row.get('id') == phase['ticket'] and not row.get('ticket_hold')
             and type(row.get('cores')) is int and row['cores'] == 7,
             'ticket is not our released seven-core proof')
    _require(type(row.get('runner_pid')) is int and row['runner_pid'] > 0
             and row.get('job_name') == 'Local\\runq-run-%s-%d' % (phase['ticket'], row['runner_pid']),
             'active queue job identity differs')
    _require(row.get('cmd_key') == binding['cmd_key'], 'active ticket is for another source-bound command')
    prediction = decimal_value(row.get('pred_peak_gib'), 'queue prediction')
    _require(decimal_value(environment.get('RUNQ_PRED_PEAK_GIB'), 'queue prediction environment') == prediction,
             'queue row/environment prediction mismatch')
    booking_gib = decimal_value(row.get('gib'), 'ticket booking')
    _require(decimal_value(environment.get('RUNQ_TICKET_GIB'), 'ticket booking environment') == booking_gib,
             'queue row/environment booking mismatch')
    declared_bytes, declared_basis = phase.get('booking_bytes'), phase.get('booking_basis')
    _require(type(declared_bytes) is int and declared_bytes > 0 and type(declared_basis) is str
             and declared_basis.strip() and declared_bytes == gib_bytes(booking_gib),
             'explicit projected booking does not match the active ticket')
    _require(peaks is None or type(peaks) is dict, 'peak history snapshot is malformed')
    history = [] if peaks is None else peaks.get(binding['cmd_key'], [])
    _require(type(history) is list and all(type(item) is dict for item in history),
             'matching-command peak history is malformed')
    measured, history_provenance = [], []
    for index, item in enumerate(history):
        if item.get('tracker') != 'job':
            continue  # Preserved runq rule: parent-chain-only histories never qualify.
        peak = decimal_value(item.get('peak'), 'job-tracked history peak')
        _require(type(item.get('who')) is str and item['who'] and type(item.get('when')) is str
                 and item['when'] and type(peaks_source) is dict and peaks_source.get('sha256'),
                 'matching history lacks successful job-record provenance')
        source = '%s sha256=%s key=%s row=%d' % (peaks_source['path'], peaks_source['sha256'],
                                               binding['cmd_key'], index)
        measured.append((source, gib_bytes(peak)))
        history_provenance.append(dict(row=index, peak_gib=str(peak), who=item['who'], when=item['when']))
    expected_basis = ('max of %d earlier job-tracked run(s) of this command' % len(measured)
                      if measured else BOOKING_BASIS)
    _require(row.get('pred_basis') == expected_basis, 'queue prediction basis/history mismatch')
    if measured:
        _require(prediction == max(decimal_value(item['peak_gib'], 'history peak') for item in history_provenance),
                 'queue prediction is not the exact matching-command maximum')
    else:
        _require(prediction == booking_gib, 'queue fallback prediction differs from its declared booking')
    key = dict(route='plan17-geometry-parity', ticket=phase['ticket'], source_command=binding)
    decision = SG.decide(key, measured=measured, booking=(declared_bytes, declared_basis))
    _require(decision['predicted_peak_bytes'] == gib_bytes(prediction),
             'shared decision differs from the qualified queue prediction')
    admitted = SG.admit(decision, available_bytes, flags)
    return dict(admitted, cores=7, booking_minutes=row.get('min'), provenance=dict(
        queue=queue_source, peaks=peaks_source, runner_pid=row['runner_pid'], job_name=row['job_name'],
        tracker='job', pred_peak_gib=str(prediction), pred_basis=row['pred_basis'],
        ticket_booking_gib=str(booking_gib), environment_prediction=environment['RUNQ_PRED_PEAK_GIB'],
        environment_booking=environment['RUNQ_TICKET_GIB'], history=history_provenance,
        shared_start_gate_sha256=SHARED_SHA256, runq_sha256=RUNQ_SHA256,
        booking_is_projection=True, measured_scope='same complete request SHA, phase and dispatch command'))


def live_admission(manifest, phase, *, manifest_path, manifest_sha256, dispatcher, argv):
    import psutil
    for path, expected in ((SHARED, SHARED_SHA256), (RUNQ, RUNQ_SHA256)):
        _require(manifest['pins'].get(str(path.resolve())) == expected,
                 'request must freeze the exact admission dependency: ' + str(path))
    binding = command_binding(manifest, phase, manifest_path, manifest_sha256, dispatcher, argv)
    queue_raw, queue_source = _read(manifest['queue'])
    peaks_path = Path(manifest['queue']).with_name('peaks.json')
    peaks_raw, peaks_source = _read(peaks_path) if peaks_path.is_file() else (None, None)
    return admit_snapshot(phase, binding, read_json(queue_raw), queue_source,
        {process.pid for process in psutil.Process().parents()}, os.environ,
        psutil.virtual_memory().available, peaks=None if peaks_raw is None else read_json(peaks_raw),
        peaks_source=peaks_source)
