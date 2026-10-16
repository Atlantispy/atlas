"""External tracked launcher for one route (1) stage: guarded run, independent reader, adoption.

Stage ``root`` (run A) or ``interval`` (run B). In order, each step only after
the previous one passed:

1. preflight, store-free: the pinned profile and the runner and reader bytes it
   names, 10 GiB available (warning below 14 GiB), disk headroom, no
   instrumentation or import-path environment, no pending Windows restart, no
   live process naming this attempt, fresh outputs, and for ``interval`` run A
   adopted after its own reader;
2. the guarded runner (run_fresh_interval.command) under the launch
   environment, tracked, then a postcheck of its guard, process tree and receipt;
3. the guarded independent reader (reopen_fresh_restart.command), tracked and
   postchecked the same way;
4. ``reopen_fresh_restart --finalise``: the reader verdict, store-free;
5. ``reopen_fresh_restart --adopt``: adopt_and_promote from the runner record,
   the sealed record and that verdict only.

A refusal stops the stage. Nothing is retried, adopted, quarantined or deleted
automatically: a sealed file whose reader failed stays unlisted until an
explicit decision. The stage record (``stage-<stage>.json`` in the attempt
directory, created exclusively, then replaced atomically after each step)
carries every receipt's SHA-256, each step's wall seconds and the guards'
sampled resource peaks next to the booked logical peaks. An interval whose
width gate fails is still adopted (it is exact) and the stage reports
ADOPTED_WIDTH_GATE_STOP_BEFORE_INTERVAL_2: interval 2 then needs the
coordinator and Michael. Real runs above 2 GiB go under run_with_heavy_lock.py.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import launch_monitored_interval as LM
import reopen_fresh_restart as RF
import run_fresh_interval as F
import run_prepared_restart as RUN

HERE = Path(__file__).resolve().parent
_SELF_SHA = sha256(Path(__file__).read_bytes()).hexdigest()
STAGE_SCHEMA = 'atlas.private.fresh-interval-stage.r1'
STAGES = F.MODES
ADOPTED = 'ADOPTED'
GATE_STOP = 'ADOPTED_WIDTH_GATE_STOP_BEFORE_INTERVAL_2'
# The orchestration this launcher itself loads; the children pin everything else.
PINNED = ('run_fresh_interval.py', 'run_prepared_restart.py', 'reopen_fresh_restart.py', 'reopen_prepared_restart.py')


class StageRefused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise StageRefused(message)


def paths(row, stage):
    attempt = Path(row['output_directory'])
    run, reader = F.mode_output(row, stage), RF.reader_output(row, stage)
    return {'attempt': attempt, 'record': attempt/f'stage-{stage}.json',
            'run': {'out': run, 'receipt': run/'run.json', 'guard': run/'run.guard.json',
                    'control': run/'run.guard-control.json', 'abort': run/'run.guard-abort.json',
                    'cancel': run/'run.cancel', 'tracking': attempt/f'run-{stage}.tracking.json',
                    'log': attempt/f'run-{stage}.log'},
            'reader': {'out': reader, 'receipt': reader/'reopen.json', 'guard': reader/'reopen.guard.json',
                       'control': reader/'reopen.guard-control.json', 'abort': reader/'reopen.guard-abort.json',
                       'cancel': reader/'reopen.cancel', 'tracking': attempt/f'reader-{stage}.tracking.json',
                       'log': attempt/f'reader-{stage}.log'}}


def _save(path, value):
    """Atomic, fsynced replace of the stage record (created exclusively by preflight)."""
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()
    partial = path.with_name(path.name+'.partial')
    with open(partial, 'xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(partial, path)


def _pinned_sources(profile):
    """Every route (1) orchestration file this launcher drives is the profile manifest's pin."""
    row = profile.record()
    workspace, manifest = LM._pinned_manifest(row)
    found = {}
    for name in PINNED:
        path = HERE/name
        pin = LM.file_hash(path)
        LM._bound_file(workspace, manifest, path, pin, name)
        found[name] = pin
    loaded = {Path(str(module.__file__)).resolve() for module in (F, RF, RUN, RF.RO)}
    require(loaded == {(HERE/name).resolve() for name in PINNED}, 'route (1) modules were loaded from elsewhere')
    return found


def preflight(profile_path, profile_sha256, *, stage, python=None, environ=None, dev_timing=False,
              stop_before_advance=False):
    """Store-free checks; writes and launches nothing."""
    require(os.name == 'nt', 'Windows job-object launch required')
    require(stage in STAGES and type(dev_timing) is bool, 'explicit route (1) stage required')
    require(type(stop_before_advance) is bool and (stage == 'interval' or not stop_before_advance),
            'stop-before-advance applies to the interval stage only')
    environ = dict(os.environ if environ is None else environ)
    dev_timing = LM._dev_timing_enabled(dev_timing, environ)
    profile = F.FreshProfile.read(Path(profile_path), LM._sha(profile_sha256))
    row = profile.record()
    pins = _pinned_sources(profile)
    python = LM._ordinary(sys.executable if python is None else python)
    p = paths(row, stage)
    RUN.ordinary(p['attempt'], directory=True)
    for item in (p['record'], p['run']['out'], p['reader']['out'], p['run']['tracking'], p['run']['log'],
                 p['reader']['tracking'], p['reader']['log']):
        require(not item.exists(), 'fresh stage outputs required: '+str(item))
    store = Path(row['store_directory'])
    interval = F.INTERVALS[stage]
    if stage == 'root':
        require(not store.exists(), 'run A requires a new store directory')
    else:
        adopted = F.read_record(RF.adopted_path(store, 0), schema=RF.ADOPTED_SCHEMA)
        require(adopted['status'] == RF.ADOPTED_STATUS and not F.runner_record_path(store, interval).exists(),
                'interval 1 requires run A adopted and no earlier interval-1 record')
    available = LM._available_bytes()
    require(type(available) is int and available >= RUN.START_BYTES,
            f'a route (1) stage requires 10 GiB available at launch (have {available} bytes)')
    limits = row['completed_query_limits']
    required = (RUN.COMPACT_STORE_LIMITS['max_store_bytes'] + RUN.COMPACT_STORE_LIMITS['max_staging_bytes'] +
                limits['max_store_bytes'])
    free = LM._disk_free(store.parent)
    require(free >= required, 'insufficient disk headroom for the interval file, its staging and the query quota')
    queries = None
    if stage == 'interval':
        queries = LM._query_state(Path(row['workspace'])/row['completed_query_directory'], probe_lock=True)
        require(not queries['lock_held'], 'completed-query owner lock is held by a live process')
    matches = LM._matching_processes([str(p['attempt'])+os.sep, str(profile.path)])
    require(not matches, 'a live process already names this attempt or profile')
    hooks = sorted(name for name in LM.HOOK_ENV if name in environ)
    require(not hooks, 'instrumentation/import-path environment refused: '+', '.join(hooks))
    require(environ.get('PYTHONHASHSEED') in (None, '0'), 'PYTHONHASHSEED must be unset or 0')
    reboot = LM._pending_reboot()
    require(not reboot, 'pending Windows restart: '+'; '.join(reboot))
    argv = F.command(profile, python, mode=stage, dev_timing=dev_timing, stop_before_advance=stop_before_advance)
    require(argv[:2] == [str(python), '-B'] and argv[3:7] == ['--launch', '--output', str(p['run']['receipt']), '--'],
            'runner command differs from the guarded launch shape')
    env = dict(environ, **LM.LAUNCH_ENV)
    record = {'schema': STAGE_SCHEMA, 'stage': stage, 'interval': interval, 'status': 'PREFLIGHT_PASSED',
              'utc': datetime.now(timezone.utc).isoformat(), 'production_acceptance': False,
              'launcher': {'pid': os.getpid(), 'path': str(Path(__file__).resolve()), 'sha256': _SELF_SHA,
                           'monitored_helpers_sha256': LM._SELF_SHA},
              'profile': {'path': str(profile.path), 'sha256': profile.sha256}, 'pinned_sources': pins,
              'python': str(python), 'env': {name: env[name] for name in LM.LAUNCH_ENV}, 'dev_timing': dev_timing,
              'stop_before_advance': stop_before_advance,
              'memory': {'available_bytes': available, 'hard_gate_bytes': RUN.START_BYTES,
                         'warning_bytes': LM.WARN_BYTES, 'warning': available < LM.WARN_BYTES},
              'disk': {'free_bytes': free, 'required_bytes': required}, 'completed_queries': queries,
              'pending_reboot': reboot, 'process_matches': matches, 'steps': []}
    return {'profile': profile, 'row': row, 'paths': p, 'argv': argv, 'env': env, 'python': python, 'record': record}


def _guarded(argv, env, p, emit):
    """Launch one guarded process, wait for RUNNING (at most 60 s), track it and wait for its exit."""
    p['out'].mkdir(exist_ok=False)
    started = time.monotonic()
    with open(p['log'], 'xb') as log:
        process = subprocess.Popen(argv, env=env, cwd=p['out'], stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    receipt, tracking = LM._await_running(process, p), None
    if receipt is None:
        emit(json.dumps({'status': 'NOT_RUNNING', 'output': str(p['out']), 'exit': process.poll()}))
    else:
        try:
            tracking = LM._track(process, receipt, p)
            emit(json.dumps({'status': 'RUNNING', 'guardian': tracking['guardian']['pid'],
                             'parent': tracking['parent'], 'output': str(p['out'])}))
        except Exception as error:  # noqa: BLE001 - the guarded run is live; never abandon it
            emit(json.dumps({'status': 'RUNNING_UNTRACKED', 'reason': repr(error), 'output': str(p['out'])}))
    code = process.wait()
    return code, time.monotonic()-started


def guard_postcheck(p, *, receipt_status, review=False):
    """Closed guard, process-tree and receipt checks after one guarded process exited.

    ``review``: the runner sealed its interval for review after a pre-seal refusal; its
    receipt then carries exactly that one error and the review state.
    """
    import psutil
    checks = []
    guard, control, receipt, tracking = (LM._read(p[name]) or {} for name in ('guard', 'control', 'receipt',
                                                                             'tracking'))

    def check(name, test):
        try:
            ok = test()
        except Exception as error:  # noqa: BLE001 - every check fails closed on any exception
            ok = repr(error)
        checks.append({'name': name, 'ok': ok is True, 'detail': None if ok is True or ok is False else ok})

    check('guard_stopped', lambda: guard['schema'] == LM.GUARD_SCHEMA and guard['status'] == 'STOPPED' and
          not guard.get('reason'))
    check('guard_exit', lambda: guard['workload_exit_confirmed'] is True and guard['workload_exit_code'] == 0)
    check('guard_cleanup', lambda: guard['cleanup'] == LM.CLEAN and 'cleanup_error' not in guard)
    check('guard_limits', lambda: guard['limits'] == {'rss_bytes': RUN.RSS_BYTES, 'free_floor_bytes': RUN.FREE_BYTES})
    check('guard_parent', lambda: guard['parent']['pid'] == receipt['pid'] and control['parent'] == guard['parent']
          and control['nonce'] == guard['nonce'] and control['close_requested'] is True)
    check('guard_supervisor', lambda: receipt['supervisor']['pid'] == guard['guardian']['pid'])
    check('no_abort_or_cancel', lambda: not p['abort'].exists() and not p['cancel'].exists())
    check('tracking', lambda: tracking['guardian']['pid'] == guard['guardian']['pid'] and
          tracking['parent'] == guard['parent'])

    def no_live_workers():
        live = [identity for identity in (guard['parent'], *guard.get('launch_cohort', [])) if LM._alive(identity)]
        try:
            guardian = psutil.Process(tracking['guardian']['pid'])
            if guardian.create_time() == tracking['guardian']['create_time']:
                live.append({'guardian': tracking['guardian']['pid']})
        except psutil.NoSuchProcess:
            pass
        return not live and not LM._matching_processes([str(p['out'])+os.sep])
    check('no_live_workers', no_live_workers)
    expected_errors = ['PresealSealedForReview'] if review else []
    check('receipt', lambda: receipt['status'] == receipt_status and
          [error['type'] for error in receipt['errors']] == expected_errors and
          receipt['final_reserved_bytes'] == 0 and receipt['production_acceptance'] is False and
          (not review or receipt['review_only']['state'] == F.REVIEW_STATUS))
    resources = {'sampled_peak_bytes': guard.get('sampled_peak_bytes'),
                 'sampled_peak_by_phase': guard.get('sampled_peak_by_phase'),
                 'booked_peak_reserved_bytes': (receipt.get('logical_budget_final') or {}).get('peak_reserved_bytes'),
                 'elapsed_seconds': guard.get('elapsed_seconds'),
                 'parent_cpu_seconds': receipt.get('parent_cpu_seconds')}
    return [item['name'] for item in checks if not item['ok']], checks, resources


def _tool(python, env, *arguments):
    """One store-free or adoption step of the reader module; the JSON line it prints, and its exit."""
    started = time.monotonic()
    completed = subprocess.run([str(python), '-B', str(HERE/'reopen_fresh_restart.py'), *arguments], env=env,
                               capture_output=True, text=True, check=False)
    lines = [line for line in completed.stdout.splitlines() if line.startswith('{')]
    try:
        result = json.loads(lines[-1]) if lines else None
    except ValueError:
        result = None
    return completed.returncode, result, time.monotonic()-started, completed.stderr[-4000:]


def review_stop(record, p, step, emit, *, stage, code, seconds):
    """The runner sealed its interval for review: report it plainly; no reader, no adoption."""
    failures, checks, resources = guard_postcheck(p['run'], receipt_status=F.REVIEW_STATUS, review=True)
    receipt = LM._read(p['run']['receipt']) or {}
    review = receipt.get('review_only') or {}
    record.update(status=F.REVIEW_STATUS, failed_step='preseal', review={
        'cause': review.get('cause'), 'sealed_file': review.get('sealed_file'), 'adoption': F.REVIEW_ADOPTION,
        'receipt_sha256': LM.file_hash(p['run']['receipt']), 'guard_failures': failures,
        'next': 'reopen_fresh_restart --launch --review on this file, a written diagnosis, then a recorded approval'})
    step('runner', ok=False, exit=code, wall_seconds=seconds, reason='bounded pre-seal refused; sealed for review only',
         failures=failures, checks=checks, resources=resources)
    emit(json.dumps({'status': F.REVIEW_STATUS, 'stage': stage, 'cause': review.get('cause'),
                     'sealed_file': review.get('sealed_file'), 'adoption': F.REVIEW_ADOPTION}))
    return 1


def run_stage(profile_path, profile_sha256, *, stage, python=None, environ=None, dev_timing=False,
              stop_before_advance=False, emit=print):
    plan = preflight(profile_path, profile_sha256, stage=stage, python=python, environ=environ,
                     dev_timing=dev_timing, stop_before_advance=stop_before_advance)
    profile, row, p, env, record = plan['profile'], plan['row'], plan['paths'], plan['env'], plan['record']
    LM._write_exclusive(p['record'], record)
    emit(json.dumps({'status': 'PREFLIGHT_PASSED', 'stage': stage, 'record': str(p['record']),
                     'memory_warning': record['memory']['warning']}))
    store = Path(row['store_directory'])
    common = ['--profile', str(profile.path), '--profile-sha256', profile.sha256, '--mode', stage]

    def step(name, **values):
        record['steps'].append({'name': name, 'utc': datetime.now(timezone.utc).isoformat(), **values})
        _save(p['record'], record)

    def stop(name, reason, **values):
        record.update(status='FAILED', failed_step=name, reason=reason)
        step(name, ok=False, reason=reason, **values)
        emit(json.dumps({'status': 'FAILED', 'stage': stage, 'step': name, 'reason': reason}))
        return 1

    try:
        code, seconds = _guarded(plan['argv'], env, p['run'], emit)
        status = (LM._read(p['run']['receipt']) or {}).get('status')
        if status == F.REVIEW_STATUS:
            return review_stop(record, p, step, emit, stage=stage, code=code, seconds=seconds)
        expected = F.STOPPED_STATUS if stop_before_advance else F.SEALED_STATUS[stage]
        failures, checks, resources = guard_postcheck(p['run'], receipt_status=expected)
        if code != 0 or failures:
            return stop('runner', 'guarded runner did not seal cleanly', exit=code, failures=failures,
                        checks=checks, wall_seconds=seconds, resources=resources)
        run_sha = LM.file_hash(p['run']['receipt'])
        step('runner', ok=True, exit=code, wall_seconds=seconds, receipt_sha256=run_sha, resources=resources)
        if stop_before_advance:
            # The smoke ends here: the adopted root was reopened and compared; nothing is sealed.
            record.update(status=F.STOPPED_STATUS, store_directory=RUN._tree(store))
            _save(p['record'], record)
            emit(json.dumps({'status': F.STOPPED_STATUS, 'stage': stage, 'record': str(p['record'])}))
            return 0
        argv = RF.command(profile, plan['python'], mode=stage, producer_receipt_sha256=run_sha)
        code, seconds = _guarded(argv, env, p['reader'], emit)
        failures, checks, resources = guard_postcheck(p['reader'], receipt_status=RF.WORKLOAD_STATUS[stage])
        if code != 0 or failures:
            return stop('reader', 'independent reader did not pass cleanly', exit=code, failures=failures,
                        checks=checks, wall_seconds=seconds, resources=resources)
        reopen_sha = LM.file_hash(p['reader']['receipt'])
        step('reader', ok=True, exit=code, wall_seconds=seconds, receipt_sha256=reopen_sha, resources=resources)
        code, result, seconds, errors = _tool(plan['python'], env, '--finalise', *common,
                                              '--producer-receipt-sha256', run_sha,
                                              '--reopen-receipt-sha256', reopen_sha)
        if code != 0 or not result or result.get('status') != F.READER_PASS[stage]:
            return stop('finalise', 'reader verdict was not written', exit=code, result=result, stderr=errors,
                        wall_seconds=seconds)
        step('finalise', ok=True, wall_seconds=seconds, verdict_sha256=result['verdict_sha256'],
             width_gate_passed=result.get('width_gate_passed'))
        code, adopted, seconds, errors = _tool(plan['python'], env, '--adopt', *common,
                                               '--verdict-sha256', result['verdict_sha256'])
        if code != 0 or not adopted or adopted.get('status') != RF.ADOPTED_STATUS:
            return stop('adopt', 'adoption refused or uncertain: reopen the catalog, never retry blindly',
                        exit=code, result=adopted, stderr=errors, wall_seconds=seconds)
        step('adopt', ok=True, wall_seconds=seconds, adopted_sha256=adopted['sha256'])
        gate = result.get('width_gate_passed')
        record.update(status=GATE_STOP if stage == 'interval' and gate is False else ADOPTED,
                      store_directory=RUN._tree(store), width_gate_passed=gate)
        _save(p['record'], record)
        emit(json.dumps({'status': record['status'], 'stage': stage, 'record': str(p['record'])}))
        return 0
    except KeyboardInterrupt:
        emit(json.dumps({'status': 'LAUNCHER_DETACHED', 'stage': stage,
                         'note': 'a guarded run may continue; inspect its guard receipt before anything else'}))
        return 130


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--stage', choices=STAGES, required=True)
    parser.add_argument('--dev-timing', action='store_true')
    parser.add_argument('--preflight-only', action='store_true', help='checks only; writes and launches nothing')
    parser.add_argument('--stop-before-advance', action='store_true',
                        help='interval stage only: the smoke; reopen the adopted root and stop')
    args = parser.parse_args(argv)
    emit = lambda line: print(line, flush=True)
    try:
        if args.preflight_only:
            plan = preflight(args.profile, args.profile_sha256, stage=args.stage, dev_timing=args.dev_timing,
                             stop_before_advance=args.stop_before_advance)
            emit(json.dumps({'status': 'PREFLIGHT_PASSED', 'argv': plan['argv'], 'memory': plan['record']['memory'],
                             'disk': plan['record']['disk']}))
            return 0
        return run_stage(args.profile, args.profile_sha256, stage=args.stage, dev_timing=args.dev_timing,
                         stop_before_advance=args.stop_before_advance, emit=emit)
    except (ValueError, OSError) as error:
        emit(json.dumps({'status': 'REFUSED', 'type': type(error).__name__, 'reason': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
