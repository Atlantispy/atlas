"""Source-bound, prospective Route 2 peak evidence; no scientific acceptance.

Only completion records written with this contract qualify. Historical unbound
LM postchecks are not migrated. The launcher authenticates evidence; the child's
unchanged start_gate.admit boundary checks arithmetic, seed and current memory.
"""
from hashlib import sha256
import json
from pathlib import Path
import stat

import start_gate as SG

SCHEMA = 'atlas.private.route2-peak.r1'
MAX_RECORD = 64 << 20
ENVIRONMENT = {'PYTHONHASHSEED': '0', 'OPENBLAS_NUM_THREADS': '1',
               'OMP_NUM_THREADS': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
PRODUCER_PASS = 'PASS_ONE_INTERVAL_PENDING_INDEPENDENT_REOPEN'
PRODUCER_STOP = 'STOPPED_BEFORE_ADVANCE_ROOT_PUBLISHED'
READER_PASS = {'successor': 'PASS_SUCCESSOR_REOPENED_PENDING_FINALISE',
               'root-only': 'PASS_ROOT_REOPENED_PENDING_FINALISE'}
FINAL_PASS = {'successor': 'PASS_SECOND_INTERVAL_INDEPENDENT_REOPEN',
              'root-only': 'PASS_MIGRATED_ROOT_INDEPENDENT_REOPEN_NOT_INTERVAL_ACCEPTANCE'}
POSTCHECK_NAMES = frozenset(('guard_schema', 'guard_stopped', 'guard_exit', 'guard_cleanup',
    'guard_limits', 'guard_parent', 'guard_control', 'guard_supervisor', 'guard_no_abort',
    'resource_summary', 'tracking', 'launch_record', 'launch_sources_unchanged', 'no_live_workers',
    'run_schema', 'run_status', 'run_errors', 'zero_reservations', 'not_production_acceptance',
    'original_unchanged_recorded', 'reopen_scope', 'run_guard_limits', 'run_start_gate', 'profile_pin',
    'interpreter_seed', 'checkpoint', 'original_database', 'sources', 'gate_evidence'))


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _ordinary(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        info = part.lstat()
        SG.require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                   'linked peak evidence/source refused')
    SG.require(path.is_file(), 'ordinary peak evidence/source file required')
    return path.resolve()


def file_binding(path):
    path = _ordinary(path)
    digest = sha256()
    with path.open('rb') as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest()}


def read_snapshot(path):
    """Parse and hash the same bounded bytes, never a second read after validation."""
    path = _ordinary(path)
    with path.open('rb') as stream:
        raw = stream.read(MAX_RECORD + 1)
    SG.require(len(raw) <= MAX_RECORD, 'peak evidence record exceeds its bound')
    def pairs(items):
        row = {}
        for key, value in items:
            SG.require(key not in row, 'duplicate peak evidence JSON key')
            row[key] = value
        return row
    row = json.loads(raw, object_pairs_hook=pairs,
                     parse_constant=lambda _: SG.require(False, 'nonfinite peak evidence JSON'))
    SG.require(type(row) is dict, 'peak evidence object required')
    return row, {'path': str(path), 'sha256': sha256(raw).hexdigest()}


def _profile_digest(row, step):
    row = dict(row)
    # Producer output is a fresh destination. For a reader this is its INPUT
    # producer attempt and must remain bound; reader output is a separate option.
    if step == 'producer':
        row.pop('output_directory')
    return sha256(_canonical(row)).hexdigest()


def command_key(profile, python, *, entry, step, stop_before_advance=False,
                dev_timing=False, producer_receipt_sha256=None, mode=None, store_route=None):
    SG.require(step in ('producer', 'reader'), 'explicit Route 2 step required')
    SG.require(type(stop_before_advance) is bool and type(dev_timing) is bool, 'boolean command modes required')
    if step == 'reader':
        SG.require(mode in READER_PASS and store_route in ('readonly', 'copy-token') and
                   type(producer_receipt_sha256) is str and len(producer_receipt_sha256) == 64 and
                   all(c in '0123456789abcdef' for c in producer_receipt_sha256), 'reader input/modes required')
        SG.require(not stop_before_advance and not dev_timing, 'producer flags on reader refused')
    else:
        SG.require(producer_receipt_sha256 is None and mode is None and store_route is None,
                   'reader options on producer refused')
    row = profile.record()
    return dict(route='prepared-restart', step=step, profile=_profile_digest(row, step),
        source_manifest=row['source_manifest'], entry=file_binding(entry), python=file_binding(python),
        gate_sources=[file_binding(SG.__file__), file_binding(__file__)], environment=dict(ENVIRONMENT),
        environment_scope='executable bytes, declared launch environment and profile source/runtime policy; '
                          'not an inventory of installed dependencies',
        stop_before_advance=stop_before_advance, dev_timing=dev_timing,
        producer_receipt_sha256=producer_receipt_sha256, mode=mode, store_route=store_route)


def add_arguments(parser):
    parser.add_argument('--peak-record', type=Path, action='append', default=[], dest='peak_records',
        help='matching Route 2 successor LM postcheck or reader final record (repeatable)')
    parser.add_argument('--booking-bytes', type=int, help='declared peak; used only without measured records')
    parser.add_argument('--booking-basis', help='explicit source/basis of that booking')


def unchanged(bindings):
    for binding in bindings.values():
        SG.require(file_binding(binding['path']) == binding,
                   'validated evidence changed before completion publication')


def _positive(value):
    return type(value) is int and value > 0


def _validate(key, snapshots):
    step = key['step']
    roles = {'profile', 'run', 'guard', 'control'} | ({'launch', 'tracking'} if step == 'producer' else set())
    SG.require(set(snapshots) == roles, 'complete Route 2 evidence snapshot set required')
    rows = {name: pair[0] for name, pair in snapshots.items()}
    bindings = {name: pair[1] for name, pair in snapshots.items()}
    profile, run, guard, control = (rows[name] for name in ('profile', 'run', 'guard', 'control'))
    SG.require(_profile_digest(profile, step) == key['profile'] and
               profile['source_manifest'] == key['source_manifest'], 'evidence profile/closure mismatch')
    SG.require(run.get('profile_sha256') == bindings['profile']['sha256'] and run.get('errors') == [] and
               run.get('production_acceptance') is False and type(run.get('final_reserved_bytes')) is int and
               run['final_reserved_bytes'] == 0, 'unsuccessful or unbound workload evidence')
    admitted = run.get('start_gate')
    SG.require(type(admitted) is dict and admitted.get('key') == key, 'workload command key mismatch')
    # Validate the historical admission using its recorded seed, never pretend to
    # authenticate its prediction from the child's measurement list.
    class Seed:
        hash_randomization = admitted.get('hash_randomization')
    SG.admit(admitted, admitted.get('available_bytes'), Seed())
    SG.require(run.get('guard_limits') == SG.guard_limits(admitted), 'workload guard/admission mismatch')
    limits = dict(rss_bytes=SG.RSS_BYTES, free_floor_bytes=SG.FREE_BYTES)
    SG.require(guard.get('schema') == 'atlas.private.continuation-guard.r3' and
               guard.get('status') == 'STOPPED' and not guard.get('reason') and
               guard.get('workload_exit_confirmed') is True and type(guard.get('workload_exit_code')) is int and
               guard['workload_exit_code'] == 0 and guard.get('cleanup') == {'remaining': [], 'action_errors': []}
               and 'cleanup_error' not in guard and guard.get('limits') == limits,
               'unclean terminal guard evidence')
    parent = guard.get('parent')
    SG.require(type(parent) is dict and _positive(parent.get('pid')) and _positive(parent.get('created_ticks')) and
               parent['pid'] == run.get('pid') and control.get('parent') == parent and
               type(guard.get('nonce')) is str and bool(guard['nonce']) and control.get('nonce') == guard['nonce'] and
               control.get('close_requested') is True and control.get('limits') == limits and
               run.get('supervisor', {}).get('pid') == guard.get('guardian', {}).get('pid') and
               _positive(guard.get('guardian', {}).get('pid')) and run['supervisor'].get('status') == 'STOPPED',
               'guard/workload/control identities differ')
    peak = guard.get('sampled_peak_bytes', {}).get(SG.TREE_PEAK)
    mirror = run.get('resources', {}).get('sampled_peak_bytes', {}).get(SG.TREE_PEAK)
    SG.require(_positive(peak) and _positive(mirror) and mirror <= peak, 'invalid final or mirrored tree peak')
    output = Path(bindings['run']['path']).parent
    basename = 'run' if step == 'producer' else 'reopen'
    SG.require(Path(bindings['run']['path']) == output/(basename+'.json') and
               Path(bindings['guard']['path']) == output/(basename+'.guard.json') and
               Path(bindings['control']['path']) == output/(basename+'.guard-control.json'),
               'attempt evidence paths differ')
    SG.require(not (output/(basename+'.cancel')).exists() and not (output/(basename+'.guard-abort.json')).exists(),
               'cancelled/aborted evidence refused')
    if step == 'producer':
        staged = key['stop_before_advance']
        SG.require(profile.get('output_directory') == str(output) and
                   Path(bindings['launch']['path']) == output.parent/(output.name+'.launch.json') and
                   Path(bindings['tracking']['path']) == output.parent/(output.name+'.tracking.json'),
                   'producer profile/launch/tracking attempt paths differ')
        SG.require(run.get('schema') == 'atlas.prepared-restart-result.v1' and
                   run.get('status') == (PRODUCER_STOP if staged else PRODUCER_PASS) and
                   run.get('stop_before_advance') is staged, 'producer mode/status mismatch')
        launch, tracking = rows['launch'], rows['tracking']
        SG.require(launch.get('schema') == 'atlas.private.monitored-interval-launch.r1' and
                   launch.get('status') == 'PREFLIGHT_PASSED' and launch.get('cwd') == str(output) and
                   launch.get('profile') == bindings['profile'] and launch.get('env') == key['environment'] and
                   launch.get('stop_before_advance') is staged and launch.get('dev_timing') is key['dev_timing'] and
                   launch.get('start_gate', {}).get('key') == key and launch.get('workload') == key['entry'] and
                   launch.get('python') == key['python']['path'] and launch.get('source_manifest') == key['source_manifest'],
                   'launch identity differs from measured command')
        decision = lambda value: {k: v for k, v in value.items()
                                  if k not in ('available_bytes', 'hash_randomization')}
        SG.require(decision(launch['start_gate']) == decision(admitted),
                   'parent and workload admission decisions differ')
        argv = launch.get('argv')
        tail = ['--profile', bindings['profile']['path'], '--profile-sha256', bindings['profile']['sha256']]
        tail += ['--stop-before-advance'] if staged else []
        tail += ['--dev-timing'] if key['dev_timing'] else []
        tail += [SG.ARGUMENT, SG.encode({k: v for k, v in launch['start_gate'].items()
                                      if k not in ('available_bytes', 'hash_randomization')})]
        prefix = [key['python']['path'], '-B', launch['guard']['path'], '--launch', '--output',
                  str(output/'run.json'), '--', key['python']['path'], '-B', key['entry']['path'], '--workload']
        SG.require(argv == prefix+tail, 'measured launch argv differs')
        SG.require(tracking.get('output') == str(output) and tracking.get('parent') == parent and
                   tracking.get('guardian', {}).get('pid') == guard['guardian']['pid'], 'tracking binding differs')
    else:
        SG.require(run.get('schema') == 'atlas.prepared-restart-reopen-result.v1' and
                   run.get('status') == READER_PASS[key['mode']] and run.get('mode') == key['mode'] and
                   run.get('store_route') == key['store_route'] and
                   run.get('producer_receipt_sha256') == key['producer_receipt_sha256'] and
                   run.get('independent_process_reopen') is True, 'reader mode/input/status mismatch')
    return peak


def evidence(key, snapshots):
    """Called only after normal completion validation; snapshots are its actual reads."""
    peak = _validate(key, snapshots)
    bindings = {name: pair[1] for name, pair in snapshots.items()}
    unchanged(bindings)
    return dict(schema=SCHEMA, key=key, peak_bytes=peak, records=bindings)


def _measured(paths, key):
    found = []
    for path in paths:
        record, binding = read_snapshot(path)
        value = record.get('gate_evidence')
        SG.require(type(value) is dict and set(value) == {'schema', 'key', 'peak_bytes', 'records'} and
                   value['schema'] == SCHEMA and value['key'] == key, 'no matching Route 2 successor evidence')
        SG.require(record.get('production_acceptance') is False and record.get('profile_sha256') ==
                   value['records']['profile']['sha256'], 'completion profile/status binding differs')
        if key['step'] == 'producer':
            checks = record.get('checks')
            expected = POSTCHECK_NAMES | ({'root_only'} if key['stop_before_advance'] else {'one_interval', 'completed_queries'})
            SG.require(record.get('schema') == 'atlas.private.monitored-interval-postcheck.r1' and
                       record.get('status') == 'PASS' and record.get('failures') == [] and type(checks) is list and
                       all(type(item) is dict and item.get('ok') is True for item in checks) and
                       len(checks) == len(expected) and {item.get('name') for item in checks} == expected and
                       record.get('stop_before_advance') is key['stop_before_advance'], 'incomplete LM postcheck')
        else:
            SG.require(record.get('schema') == 'atlas.prepared-restart-reopen-final.v1' and
                       record.get('status') == FINAL_PASS[key['mode']] and record.get('errors') == [] and
                       record.get('mode') == key['mode'] and record.get('store_route') == key['store_route'] and
                       record.get('producer_receipt_sha256') == key['producer_receipt_sha256'] and
                       record.get('reopen_receipt_sha256') == value['records']['run']['sha256'] and
                       record.get('independent_process_reopen') is True, 'incomplete reader finalisation')
        snapshots = {}
        for role, source in value['records'].items():
            pair = read_snapshot(source['path'])
            SG.require(pair[1] == source, 'completion evidence bytes changed')
            snapshots[role] = pair
        peak = _validate(key, snapshots)
        if key['step'] == 'producer':
            SG.require(record.get('output') == str(Path(value['records']['run']['path']).parent),
                       'postcheck output differs from measured attempt')
        SG.require(type(value['peak_bytes']) is int and peak == value['peak_bytes'], 'declared peak differs from guard')
        found.append(('%s sha256=%s' % (binding['path'], binding['sha256']), peak))
    return found


def measured(paths, key):
    SG.require(type(paths) in (list, tuple), 'peak records must be an explicit list')
    try:
        return _measured(paths, key)
    except (KeyError, TypeError, AttributeError) as error:
        raise SG.StartGateRefused('malformed Route 2 completion evidence: '+str(error)) from error


def decide(key, *, records=(), booking_bytes=None, booking_basis=None):
    SG.require((booking_bytes is None) == (booking_basis is None),
               'a declared booking needs both --booking-bytes and --booking-basis')
    booking = None if booking_bytes is None else (booking_bytes, booking_basis)
    return SG.decide(key, measured=measured(records, key), booking=booking)
