"""Source-bound, prospective Route 2 peak evidence; no scientific acceptance.

Only completion records written with this contract qualify. Historical unbound
LM postchecks are not migrated. The launcher authenticates evidence; the child's
unchanged start_gate.admit boundary checks arithmetic, seed and current memory.
"""
from hashlib import sha256
import json
from pathlib import Path

from atlas_tectonics._private.integration import start_gate as SG

SCHEMA = 'atlas.private.route2-peak.r1'
MAX_RECORD = 64 << 20
ENVIRONMENT = {'PYTHONHASHSEED': '0', 'OPENBLAS_NUM_THREADS': '1',
               'OMP_NUM_THREADS': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
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
        part.lstat()
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
    def pairs(items):
        row = {}
        for key, value in items:
            row[key] = value
        return row
    row = json.loads(raw, object_pairs_hook=pairs,
                     parse_constant=lambda _: SG.require(False, 'nonfinite peak evidence JSON'))
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
        entry=file_binding(entry), python=file_binding(python),
        gate_sources=[file_binding(SG.__file__), file_binding(__file__)], environment=dict(ENVIRONMENT),
        environment_scope='executable bytes, declared launch environment and profile runtime policy; '
                          'not an inventory of installed dependencies',
        stop_before_advance=stop_before_advance, dev_timing=dev_timing,
        producer_receipt_sha256=producer_receipt_sha256, mode=mode, store_route=store_route)


def unchanged(bindings):
    for binding in bindings.values():
        SG.require(file_binding(binding['path']) == binding,
                   'validated evidence changed before completion publication')


def _positive(value):
    return type(value) is int and value > 0


def _validate(key, snapshots):
    step = key['step']
    rows = {name: pair[0] for name, pair in snapshots.items()}
    bindings = {name: pair[1] for name, pair in snapshots.items()}
    profile, run, guard, control = (rows[name] for name in ('profile', 'run', 'guard', 'control'))
    SG.require(_profile_digest(profile, step) == key['profile'], 'evidence profile/closure mismatch')
    admitted = run.get('start_gate')
    # Validate the historical admission using its recorded seed, never pretend to
    # authenticate its prediction from the child's measurement list.
    class Seed:
        hash_randomization = admitted.get('hash_randomization')
    SG.admit(admitted, admitted.get('available_bytes'), Seed())
    limits = SG.guardian_limits(admitted)
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
    output = Path(bindings['run']['path']).parent
    basename = 'run' if step == 'producer' else 'reopen'
    SG.require(not (output/(basename+'.cancel')).exists() and not (output/(basename+'.guard-abort.json')).exists(),
               'cancelled/aborted evidence refused')
    if step == 'producer':
        staged = key['stop_before_advance']
        launch, _ = rows['launch'], rows['tracking']
        SG.require(launch.get('schema') == 'atlas.private.monitored-interval-launch.r1' and
                   launch.get('status') == 'PREFLIGHT_PASSED' and launch.get('cwd') == str(output) and
                   launch.get('profile') == bindings['profile'] and launch.get('env') == key['environment'] and
                   launch.get('stop_before_advance') is staged and launch.get('dev_timing') is key['dev_timing'] and
                   launch.get('start_gate', {}).get('key') == key and launch.get('workload') == key['entry'] and
                   launch.get('python') == key['python']['path'],
                   'launch identity differs from measured command')
        argv = launch.get('argv')
        prefix = [key['python']['path'], '-B', launch['guard']['path'], '--launch', '--output',
                  str(output/'run.json'), '--', key['python']['path'], '-B', key['entry']['path'], '--workload']
        tail = ['--profile', bindings['profile']['path'], '--profile-sha256', bindings['profile']['sha256']]
        tail += ['--stop-before-advance'] if staged else []
        # The key's dev_timing field records whether the run profile held 'stages'.
        words = argv[len(prefix)+len(tail):-2] if type(argv) is list else None
        SG.require(words == [] and not key['dev_timing'] or
                   type(words) is list and len(words) == 2 and words[0] == '--run-profile' and
                   ('stages' in words[1].split(',')) is key['dev_timing'], 'measured run profile differs')
        tail += words
        tail += [SG.ARGUMENT, SG.encode({k: v for k, v in launch['start_gate'].items()
                                      if k not in ('available_bytes', 'hash_randomization')})]
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
            snapshots[role] = pair
        peak = _validate(key, snapshots)
        found.append(('%s sha256=%s' % (binding['path'], binding['sha256']), peak))
    return found


def measured(paths, key):
    try:
        return _measured(paths, key)
    except (KeyError, TypeError, AttributeError) as error:
        raise SG.StartGateRefused('malformed Route 2 completion evidence: '+str(error)) from error


def decide(key, *, records=(), booking_bytes=None, booking_basis=None):
    booking = None if booking_bytes is None else (booking_bytes, booking_basis)
    return SG.decide(key, measured=measured(records, key), booking=booking)
