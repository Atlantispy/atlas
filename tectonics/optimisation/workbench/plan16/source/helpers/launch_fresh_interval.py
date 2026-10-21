"""External tracked launcher for one route (1) stage: guarded run, independent reader, adoption.

Stage ``root`` (run A) or ``interval`` (run B). In order, each step only after
the previous one passed:

1. preflight, store-free: the pinned profile and the runner and reader bytes it
   names, the by-need start gate (start_gate.py), disk headroom, no
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

``--reuse-initial-measurements`` (interval stage only, off by default; item 7): run B starts
from run A's closed initial measurement store. The launcher passes the receipt SHA-256 the
root stage record holds and the store SHA-256 run A recorded in that receipt; it never hashes
the store itself. The runner checks the whole chain and copies the store before its admission.

``--interval N`` (interval stage, N >= 2; item 21): stage ``interval-NNNN`` starts from adopted
interval N-1 exactly as its own stage record names it (ADOPTED, width gate passed); the
launcher passes that adoption record's SHA-256 to the runner, which re-checks the whole
sealed lineage before the catalog opens. N = 1 is the interval stage unchanged. A failed
width gate at any N still adopts and reports GATE_STOP.

N9 lf-r1 (isolated successor of a4d335fd; CONTRACT-REVIEW-r2 section 4; WORKING NON-CANON): each guarded
runner/reader step writes ``<step>-<stage>.launch.json`` exclusively before Popen (explicit arm, stage,
interval, step, attempt and output binding; argv; environment names only; this launcher's and its LM helper's
pins; the guard and step entry-point pins; the profile pin) and keeps the digest of that write in memory. After
wait() and before the unchanged postcheck it writes ``<step>-<stage>.capture.json`` exclusively, once, with that
digest, the lifecycle and every step file's {present, sha256, bytes, mtime_ns}. A record collision or other
failure before Popen refuses with no child and no capture; a KeyboardInterrupt before wait() returns writes no
capture; a capture failure after wait() is recorded on the step and the postcheck still runs. The pre-step
stage record digest is diagnostic only. Guard, postcheck, verdict and stage-record semantics are unchanged.

``--sequential-reader-fallback`` is a separate explicit recovery route. It needs a pinned
coordinating-chat approval and the exact failed stage pin, preserves those raw stage bytes,
claims one fixed fresh sibling reader, and never starts a producer. An abruptly lost
launcher may leave an in-progress stage: only authenticated launcher loss with its producer
success and immutable capture already recorded permits that bounded recovery. Recovered
stages never supply successful overlap memory measurements.
"""
import argparse
import json
import os
import secrets
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
import start_gate as SG
import reader_overlap_gate as OG
import overlap_cohort as OC
import overlap_reader as OR
import overlap_metrics as OM

HERE = Path(__file__).resolve().parent
_SELF_SHA = sha256(Path(__file__).read_bytes()).hexdigest()
STAGE_SCHEMA = 'atlas.private.fresh-interval-stage.r1'
STAGES = F.MODES
ADOPTED = 'ADOPTED'
GATE_STOP = 'ADOPTED_WIDTH_GATE_STOP_BEFORE_INTERVAL_2'
# The orchestration this launcher itself loads; the children pin everything else.
PINNED = ('run_fresh_interval.py', 'run_prepared_restart.py', 'reopen_fresh_restart.py', 'reopen_prepared_restart.py',
          'start_gate.py', 'reader_overlap_gate.py', 'overlap_cohort.py', 'overlap_reader.py', 'overlap_metrics.py')
ROOT_STEPS = ['runner', 'reader', 'finalise', 'adopt']
REUSE_FIELDS = ('status', 'hits', 'misses', 'full_reuse', 'counts_agree_with_bytes', 'copy_seconds')
STEP_LAUNCH_SCHEMA = 'atlas.private.fresh-interval-step-launch.r1'
STEP_CAPTURE_SCHEMA = 'atlas.private.fresh-interval-step-capture.r1'
CAPTURE_FILES = ('launch', 'tracking', 'receipt', 'guard', 'control', 'abort', 'cancel', 'log')
CAPTURE_JSON_BYTES = 1 << 26     # r2: incremental read cap; retain only the guard JSON during capture
FALLBACK_APPROVAL_SCHEMA = 'atlas.private.fresh-interval-sequential-fallback-approval.r1'
FALLBACK_COORDINATOR = '01a13d3a-b0c9-7fd1-b89d-d03df51a1b73'


class StageRefused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise StageRefused(message)


def paths(row, stage, interval=None, *, fallback=False):
    attempt = Path(row['output_directory'])
    number = F.interval_number(stage, interval)
    name = stage if number <= 1 else f'{stage}-{number:04d}'
    require(type(fallback) is bool, 'explicit fallback path selection required')
    reader_name = name+('-fallback' if fallback else '')
    run, reader = F.mode_output(row, stage, interval), RF.reader_output(row, stage, interval, fallback=fallback)
    return {'attempt': attempt, 'record': attempt/f'stage-{name}.json',
            'run': {'out': run, 'receipt': run/'run.json', 'guard': run/'run.guard.json',
                    'control': run/'run.guard-control.json', 'abort': run/'run.guard-abort.json',
                    'cancel': run/'run.cancel', 'tracking': attempt/f'run-{name}.tracking.json',
                    'log': attempt/f'run-{name}.log', 'launch': attempt/f'run-{name}.launch.json',
                    'capture': attempt/f'run-{name}.capture.json'},
            'reader': {'out': reader, 'receipt': reader/'reopen.json', 'guard': reader/'reopen.guard.json',
                       'control': reader/'reopen.guard-control.json', 'abort': reader/'reopen.guard-abort.json',
                       'cancel': reader/'reopen.cancel', 'tracking': attempt/f'reader-{reader_name}.tracking.json',
                       'log': attempt/f'reader-{reader_name}.log', 'launch': attempt/f'reader-{reader_name}.launch.json',
                       'capture': attempt/f'reader-{reader_name}.capture.json'}}


def _save(path, value):
    """Atomic, fsynced replace of the stage record (created exclusively by preflight)."""
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()
    partial = path.with_name(path.name+'.partial')
    with open(partial, 'xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    OG._retry_sharing(lambda: os.replace(partial, path), 'mutable stage record replacement')


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
    loaded = {Path(str(module.__file__)).resolve() for module in (F, RF, RUN, RF.RO, SG, OG, OC, OR, OM)}
    require(loaded == {(HERE/name).resolve() for name in PINNED}, 'route (1) modules were loaded from elsewhere')
    return found


def _same_path(a, b):
    return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))


def _composition_root(row, manifest):
    """A published composition launches only from its permanent root (coordinator rule, 16 Oct 2026).

    Heat result IDs bind the absolute paths of their helper sources, so a moved or copied
    composition would give other IDs for the same numbers. Inside a composition (this launcher
    in <root>/helpers), composition.json's root and the reviewed inputs' target_root must both be
    that root (normcase of the resolved path) and the reviewed inputs must match their pin. A
    helpers folder without its composition.json refuses. A launch from anywhere else is the
    development route: it refuses a profile whose manifest names a frozen or published composition.
    """
    root = HERE.parent
    record_path = root/'composition.json'
    if record_path.is_file():
        record = json.loads(record_path.read_text(encoding='utf8'))
        inputs_path = Path(row['workspace'])/record['reviewed_inputs']
        require(LM.file_hash(inputs_path) == record['reviewed_inputs_sha256'], 'reviewed inputs differ from their pin')
        inputs = json.loads(inputs_path.read_text(encoding='utf8'))
        require(_same_path(root, record['root']) and _same_path(root, inputs['target_root']),
                'composition root rule: this composition runs only from '+str(record['root']))
        return {'root': str(root), 'composition_sha256': LM.file_hash(record_path),
                'reviewed_inputs_sha256': record['reviewed_inputs_sha256']}
    require(HERE.name != 'helpers', "a composition's helpers folder requires its composition.json")
    named = manifest.get('composition') or {}
    require(not ({'frozen', 'published'} & set(named)),
            'a frozen composition profile launches only from its published composition root')
    return {'root': None, 'development_launch': str(HERE)}


def initial_measurement_seed(row):
    """Item 7: run A's receipt SHA-256 and the store SHA-256 it recorded, from the adopted root stage only.

    The pin is the value run A recorded after its admission closed (review condition 1), read
    from the receipt its reader passed; the root stage record names that receipt and the
    adoption record by SHA-256. The store is never hashed here. The runner re-checks the chain.
    """
    p = paths(row, 'root')
    stage = LM._read(p['record'])
    steps = stage.get('steps') if type(stage) is dict else None
    require(type(stage) is dict and stage.get('schema') == STAGE_SCHEMA and stage.get('stage') == 'root' and
            stage.get('status') == ADOPTED and type(steps) is list and all(type(step) is dict for step in steps) and
            [step.get('name') for step in steps] == ROOT_STEPS and all(step.get('ok') is True for step in steps),
            'measurement reuse requires the root stage adopted after its runner, reader, finalise and adopt steps')
    receipt_sha256 = LM._sha(steps[0].get('receipt_sha256'))
    require(LM.file_hash(p['run']['receipt']) == receipt_sha256, 'run A receipt differs from the root stage record')
    require(LM.file_hash(RF.adopted_path(Path(row['store_directory']), 0)) == steps[3].get('adopted_sha256'),
            'run A adoption record differs from the root stage record')
    receipt = RUN.pinned_json(p['run']['receipt'], receipt_sha256, RF.RO.MAX_RECEIPT)
    stored = receipt.get('initial_measurement_store') if type(receipt) is dict else None
    require(type(stored) is dict and stored.get('filename') == F.MEASUREMENT_STORE,
            'run A receipt names no closed initial measurement store')
    return {'receipt_sha256': receipt_sha256, 'store_sha256': LM._sha(stored.get('sha256'))}


def parent_adoption(row, number, parent_adopted_sha256=None):
    """Item 21: adopted interval N-1 as its own stage recorded it; the adoption record's pin for the runner.

    Ordinarily the parent stage must be ADOPTED after its runner, reader, finalise and adopt
    steps, its finalise step must record the width gate passed, and adopted(N-1) must be adopted
    from that step's verdict; no explicit pin is taken. A width-gate stop needs the coordinator
    and Michael, so it is no parent here. A review-adopted N-1 is the separate branch
    reviewed_parent, which needs ``parent_adopted_sha256``. The runner checks the durable
    verdicts' gates again.
    """
    parent = paths(row, 'interval', None if number == 2 else number-1)
    stage = LM._read(parent['record'])
    if type(stage) is dict and stage.get('status') == F.REVIEW_STATUS:
        return reviewed_parent(row, number, parent['record'], stage, parent_adopted_sha256)
    require(parent_adopted_sha256 is None, 'an explicit parent adoption pin is for a review-adopted parent only')
    steps = stage.get('steps') if type(stage) is dict else None
    require(type(stage) is dict and stage.get('schema') == STAGE_SCHEMA and stage.get('stage') == 'interval' and
            stage.get('interval') == number-1 and stage.get('status') == ADOPTED and type(steps) is list and
            all(type(step) is dict for step in steps) and [step.get('name') for step in steps] == ROOT_STEPS and
            all(step.get('ok') is True for step in steps) and steps[2].get('width_gate_passed') is True,
            'interval N requires interval N-1 adopted by its own stage with its width gate passed')
    pin = LM._sha(steps[3].get('adopted_sha256'))
    path = RF.adopted_path(Path(row['store_directory']), number-1)
    require(LM.file_hash(path) == pin, 'adopted interval N-1 differs from its stage record')
    adopted = F.read_record(path, schema=RF.ADOPTED_SCHEMA, expected_sha256=pin)
    require(adopted.get('interval') == number-1 and adopted.get('status') == RF.ADOPTED_STATUS and
            adopted.get('verdict_sha256') == steps[2].get('verdict_sha256'),
            'adopted interval N-1 differs from its stage record')
    return {'stage_record': str(parent['record']), 'adopted_sha256': pin}


def reviewed_parent(row, number, record_path, stage, pin):
    """Interval N-1 sealed for review by its own stage, then adopted by the recorded approval route.

    The old stage stays as it is (REVIEW_STATUS, failed at preseal). Its clean review evidence
    (no postcheck failure, guard wrapper exit 2) must name the adoption at the explicit pin:
    the stage's producer receipt is that verdict's, and its sealed file is the adopted entry's.
    The adoption carries its approval; the verdict is review-only with its width gate passed.
    The runner re-checks the approval, review flags, gate, lineage and catalog.
    """
    pin = LM._sha(pin) if pin is not None else None
    require(pin is not None, 'a review-adopted parent needs its explicit adoption pin')
    steps, review = stage.get('steps'), stage.get('review')
    require(stage.get('schema') == STAGE_SCHEMA and stage.get('stage') == 'interval' and
            stage.get('interval') == number-1 and stage.get('failed_step') == 'preseal' and
            type(steps) is list and len(steps) == 1 and type(steps[0]) is dict and steps[0].get('name') == 'runner' and
            type(steps[0].get('exit')) is int and steps[0]['exit'] == 2 and
            type(review) is dict and review.get('guard_failures') == [],
            'interval N-1 stage has no clean review evidence')
    store = Path(row['store_directory'])
    path = RF.adopted_path(store, number-1)
    require(LM.file_hash(path) == pin, 'adopted interval N-1 differs from the explicit pin')
    adopted = F.read_record(path, schema=RF.ADOPTED_SCHEMA, expected_sha256=pin)
    entry = adopted.get('entry')
    require(adopted.get('interval') == number-1 and adopted.get('status') == RF.ADOPTED_STATUS and
            type(adopted.get('review_approval_sha256')) is str and type(entry) is dict,
            'the explicit pin is no review-approved adoption of interval N-1')
    # read_record treats a None pin as unpinned: the adoption's verdict pin must be a full SHA-256.
    verdict = F.read_record(F.verdict_path(store, number-1), schema=F.VERDICT_SCHEMA,
                            expected_sha256=LM._sha(adopted.get('verdict_sha256')))
    require(verdict.get('review_only') is True and F.width_gate_passed(verdict.get('width_gate'), number-1),
            'interval N requires review-adopted interval N-1 read with its width gate passed')
    require(review.get('receipt_sha256') == verdict.get('producer_receipt_sha256') and
            review.get('sealed_file') == {k: entry.get(k) for k in ('filename', 'file_sha256', 'logical_seal')},
            'adopted interval N-1 differs from its review stage record')
    return {'stage_record': str(record_path), 'adopted_sha256': pin, 'route': 'review-adopted',
            'review_approval_sha256': adopted['review_approval_sha256']}


def overlap_decisions(profile, stage, number, config, records, booking_bytes, booking_basis):
    """Three by-need predictions, from successful exact matching overlap records only."""
    fields = {'producer_booking_bytes', 'producer_booking_basis', 'reader_booking_bytes',
              'reader_booking_basis', 'wait_seconds', 'wait_basis'}
    require(type(config) is dict and set(config) == fields, 'closed explicit phase2 configuration required')
    require(type(config['wait_seconds']) in (int, float) and 0 < config['wait_seconds'] < float('inf') and
            type(config['wait_basis']) is str and config['wait_basis'].strip(),
            'finite advance-sized wait and basis required')
    key = {'route': 'fresh-reader-overlap-phase2', 'stage': stage, 'interval': number,
           'profile_sha256': profile.sha256, 'source_manifest_sha256': profile.record()['source_manifest']['sha256'],
           'reader_initial_workers': 0, 'ale_policy': {'mode': 'serial', 'workers': 2}}
    found = {'cohort': [], 'producer': [], 'reader': []}
    for source in records:
        path = RUN.ordinary(Path(source))
        observed, raw = OG._retry_sharing(lambda: _file_row(path), 'prediction record read')
        require(observed['present'] and raw is not None and
                OG._retry_sharing(lambda: LM.file_hash(path), 'prediction record digest') == observed['sha256'],
                'prediction record changed or is absent')
        row = LM._json(raw)
        steps, overlap = row.get('steps') if type(row) is dict else None, row.get('overlap') if type(row) is dict else None
        require(type(steps) is list and all(type(step) is dict for step in steps) and
                [step.get('name') for step in steps] == ROOT_STEPS and
                all(step.get('ok') is True for step in steps) and row.get('status') in (ADOPTED, GATE_STOP) and
                type(overlap) is dict and overlap.get('completed_overlap') is True and
                overlap.get('command_key') == key,
                'overlap prediction needs a successful matching source/profile/input/worker record')
        peak = overlap.get('observations', {}).get('sampled_tree_peak_bytes')
        peaks = {'cohort': peak, 'producer': steps[0].get('resources', {}).get('sampled_peak_bytes', {}).get('process_tree_rss'),
                 'reader': steps[1].get('resources', {}).get('sampled_peak_bytes', {}).get('process_tree_rss')}
        require(all(type(value) is int and value > 0 for value in peaks.values()),
                'complete measured cohort and guarded-tree peaks required')
        pin = observed['sha256']
        for part, value in peaks.items():
            found[part].append((str(path)+'@'+pin, value))
    bookings = {'cohort': (booking_bytes, booking_basis),
                'producer': (config['producer_booking_bytes'], config['producer_booking_basis']),
                'reader': (config['reader_booking_bytes'], config['reader_booking_basis'])}
    decisions = {part: SG.decide(dict(key, part=part), measured=found[part],
                                 booking=None if value[0] is None and value[1] is None else value)
                 for part, value in bookings.items()}
    return key, decisions


def preflight(profile_path, profile_sha256, *, stage, python=None, environ=None, dev_timing=False,
              stop_before_advance=False, reuse_initial_measurements=False, peak_records=(), booking_bytes=None,
              booking_basis=None, interval=None, parent_adopted_sha256=None, overlap=None):
    """Store-free checks; writes and launches nothing. The start gate (start_gate.py) is decided from the
    named stage records, or the declared booking when there is none, and admitted against this machine."""
    require(os.name == 'nt', 'Windows job-object launch required')
    require(stage in STAGES and type(dev_timing) is bool, 'explicit route (1) stage required')
    require(type(stop_before_advance) is bool and (stage == 'interval' or not stop_before_advance),
            'stop-before-advance applies to the interval stage only')
    require(type(reuse_initial_measurements) is bool and (stage == 'interval' or not reuse_initial_measurements),
            'measurement reuse applies to the interval stage only')
    number = F.interval_number(stage, interval)
    require(overlap is None or (not stop_before_advance and not dev_timing),
            'phase2 needs an ordinary complete producer; no smoke or instrumented producer')
    require(number < 2 or not stop_before_advance, 'interval N >= 2 runs no smoke: the smoke is interval 1 only')
    require(number >= 2 or parent_adopted_sha256 is None, 'an explicit parent adoption pin is for interval N >= 2')
    environ = dict(os.environ if environ is None else environ)
    dev_timing = LM._dev_timing_enabled(dev_timing, environ)
    require(overlap is None or not dev_timing, 'phase2 refuses instrumentation resolved from the environment')
    profile = F.FreshProfile.read(Path(profile_path), LM._sha(profile_sha256))
    row = profile.record()
    pins = _pinned_sources(profile)
    composition = _composition_root(row, LM._pinned_manifest(row)[1])
    python = LM._ordinary(sys.executable if python is None else python)
    p = paths(row, stage, interval)
    RUN.ordinary(p['attempt'], directory=True)
    for item in (p['record'], p['run']['out'], p['reader']['out'], p['run']['tracking'], p['run']['log'],
                 p['reader']['tracking'], p['reader']['log'], p['run']['launch'], p['run']['capture'],
                 p['reader']['launch'], p['reader']['capture']):
        require(not item.exists(), 'fresh stage outputs required: '+str(item))
    store = Path(row['store_directory'])
    parent = None
    if stage == 'root':
        require(not store.exists(), 'run A requires a new store directory')
    elif number == 1:
        adopted = F.read_record(RF.adopted_path(store, 0), schema=RF.ADOPTED_SCHEMA)
        require(adopted['status'] == RF.ADOPTED_STATUS and not F.runner_record_path(store, number).exists(),
                'interval 1 requires run A adopted and no earlier interval-1 record')
    else:
        parent = parent_adoption(row, number, parent_adopted_sha256)
        require(not F.runner_record_path(store, number).exists(), 'interval N requires no earlier interval-N record')
    seed = initial_measurement_seed(row) if reuse_initial_measurements else None
    decisions = key = None
    if overlap is None:
        gate = SG.stage_decision(SG.stage_key(stage, number), records=peak_records, booking_bytes=booking_bytes,
                                 booking_basis=booking_basis)
    else:
        sources = F.FreshSources(profile)
        with sources.selected():
            driver = sources.module(F.DRIVER)
            require(driver.ALE_PARALLEL == {'mode': 'serial', 'workers': 2} and
                    driver.PARALLEL == {'mode': 'auto', 'workers': 2} and
                    driver.SUCCESSOR_ALE_POLICY == 'authenticated-parent-four-or-six',
                    'initial phase2 requires fixed serial interval-one ALE and the declared successor policy')
        key, decisions = overlap_decisions(profile, stage, number, overlap, peak_records, booking_bytes, booking_basis)
        gate = decisions['cohort']
        require(not OR.gate_path(p['attempt'], stage, number).parent.exists(), 'fresh stage gate directory required')
    available = LM._available_bytes()
    admitted = SG.admit(gate, available)
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
    argv = F.command(profile, python, mode=stage, dev_timing=dev_timing, stop_before_advance=stop_before_advance,
                     seed=seed, start_gate=gate if decisions is None else decisions['producer'], interval=interval,
                     parent_adopted_sha256=None if parent is None else parent['adopted_sha256'])
    require(argv[:2] == [str(python), '-B'] and argv[3:7] == ['--launch', '--output', str(p['run']['receipt']), '--'],
            'runner command differs from the guarded launch shape')
    env = F.pressure_launch_environment(environ)
    record = {'schema': STAGE_SCHEMA, 'stage': stage, 'interval': number, 'status': 'PREFLIGHT_PASSED',
              'utc': datetime.now(timezone.utc).isoformat(), 'production_acceptance': False,
              'launcher': {'pid': os.getpid(), 'path': str(Path(__file__).resolve()), 'sha256': _SELF_SHA,
                           'monitored_helpers_sha256': LM._SELF_SHA},
              'profile': {'path': str(profile.path), 'sha256': profile.sha256}, 'pinned_sources': pins,
              'composition_root': composition,
              'python': str(python), 'env': {name: env[name] for name in LM.LAUNCH_ENV}, 'dev_timing': dev_timing,
              'stop_before_advance': stop_before_advance, 'initial_measurement_seed': seed,
              'memory': {'available_bytes': available, 'hard_gate_bytes': admitted['gate_bytes'],
                         'warning_bytes': LM.WARN_BYTES, 'warning': available < LM.WARN_BYTES},
              'start_gate': admitted,
              'disk': {'free_bytes': free, 'required_bytes': required}, 'completed_queries': queries,
              'pending_reboot': reboot, 'process_matches': matches, 'steps': [],
              **({} if decisions is None else {'overlap': {'command_key': key, 'decisions': decisions,
                                                          'configuration': dict(overlap), 'completed_overlap': False}}),
              **({} if parent is None else {'parent': parent})}
    return {'profile': profile, 'row': row, 'paths': p, 'argv': argv, 'env': env, 'python': python, 'record': record,
            'seed': seed, 'gate': gate, 'interval': interval, 'overlap': overlap, 'decisions': decisions}


def step_launch(argv, env, p, *, binding, profile, stage_record):
    """The immutable step launch record (N9 lf-r1): explicit binding, argv, environment names, source pins."""
    require(type(argv) is list and len(argv) > 9 and all(type(item) is str for item in argv) and
            argv[1] == '-B' and argv[3:7] == ['--launch', '--output', str(p['receipt']), '--'] and
            argv[8] == '-B', 'guarded step command differs from the launch shape')
    require(type(binding) is dict and set(binding) == {'arm', 'stage', 'interval', 'step', 'attempt'} and
            type(binding['arm']) is str and binding['arm'] and binding['step'] in ('runner', 'reader'),
            'explicit arm/stage/interval/step/attempt binding required')
    guard, entry = Path(argv[2]), F.pressure_entry_point(argv, binding['step'], profile)
    return {'schema': STEP_LAUNCH_SCHEMA, 'utc': datetime.now(timezone.utc).isoformat(),
            'writer': {'pid': os.getpid(), 'launcher': {'path': str(Path(__file__).resolve()), 'sha256': _SELF_SHA},
                       'helper': {'path': str(Path(LM.__file__).resolve()), 'sha256': LM._SELF_SHA}},
            'binding': dict(binding, output=str(p['out'])), 'argv': list(argv), 'env_names': sorted(env),
            'guard': {'path': str(guard), 'sha256': LM.file_hash(guard)},
            'entry_point': {'path': str(entry), 'sha256': LM.file_hash(entry)},
            'profile': {'path': str(profile.path), 'sha256': profile.sha256},
            'stage_record_before_step': {'sha256': LM.file_hash(stage_record), 'diagnostic_only': True}}


def _file_row(path, *, retain=True):
    """One stable snapshot: JSON reads have both an initial and incremental cap; logs are streamed."""
    path = Path(path)
    try:
        before = path.stat()
    except FileNotFoundError:
        return {'present': False, 'sha256': None, 'bytes': None, 'mtime_ns': None}, None
    is_json = path.suffix == '.json'
    limit = CAPTURE_JSON_BYTES if is_json else before.st_size
    require(before.st_size <= limit, 'oversized step JSON record: '+str(path))
    digest, raw, total = sha256(), bytearray(), 0
    with path.open('rb') as stream:
        while True:
            block = stream.read(min(1 << 20, limit-total+1))
            if not block:
                break
            total += len(block)
            require(total <= limit, 'step file grew beyond capture byte cap: '+str(path))
            digest.update(block)
            if is_json and retain:
                raw.extend(block)
        after = os.fstat(stream.fileno())
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and total == after.st_size,
            'step file changed while captured: '+str(path))
    return {'present': True, 'sha256': digest.hexdigest(), 'bytes': total,
            'mtime_ns': after.st_mtime_ns}, bytes(raw) if is_json and retain else None


def _capture(p, launch, launch_sha256, *, outcome, code, observed):
    """The launching parent's one terminal capture, after wait(); written exclusively."""
    files, guard_raw = {}, None
    for name in CAPTURE_FILES:
        files[name], raw = _file_row(p[name], retain=name == 'guard')
        if name == 'guard':
            guard_raw = raw
    require(files['launch']['sha256'] == launch_sha256, 'step launch record changed before its capture')
    guard = json.loads(guard_raw) if guard_raw else {}
    guard = guard if type(guard) is dict else {}
    value = {'schema': STEP_CAPTURE_SCHEMA, 'utc': datetime.now(timezone.utc).isoformat(),
             'capture_mode': 'launching-parent', 'writer': launch['writer'], 'binding': launch['binding'],
             'launch_record_sha256': launch_sha256,
             'lifecycle': {'launcher_outcome': outcome, 'process_exit_code': code,
                           'guard_status': guard.get('status'), 'guard_reason': guard.get('reason'),
                           'workload_exit_confirmed': guard.get('workload_exit_confirmed'),
                           'workload_exit_code': guard.get('workload_exit_code'),
                           'terminal_observed_utc': observed},
             'files': files, 'nonce': guard.get('nonce')}
    return LM._write_exclusive(p['capture'], value)


def _guarded(argv, env, p, emit, launch):
    """Write the step launch record, launch one guarded process, wait for RUNNING (at most 60 s), track it,
    wait for its exit and capture it. Returns (exit, seconds, step evidence)."""
    started = time.monotonic()
    try:
        launch_sha256 = LM._write_exclusive(p['launch'], launch)
        p['out'].mkdir(exist_ok=False)
        log = open(p['log'], 'xb')
    except OSError as error:   # a collision or failure before Popen: no child, no capture
        raise StageRefused('guarded step refused before Popen: %r' % (error,)) from None
    with log:
        process = subprocess.Popen(argv, env=env, cwd=p['out'], stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    receipt, tracking, outcome = LM._await_running(process, p), None, 'NOT_RUNNING'
    if receipt is None:
        emit(json.dumps({'status': 'NOT_RUNNING', 'output': str(p['out']), 'exit': process.poll()}))
    else:
        try:
            tracking = LM._track(process, receipt, p)
            outcome = 'RUNNING'
            emit(json.dumps({'status': 'RUNNING', 'guardian': tracking['guardian']['pid'],
                             'parent': tracking['parent'], 'output': str(p['out'])}))
        except Exception as error:  # noqa: BLE001 - the guarded run is live; never abandon it
            outcome = 'RUNNING_UNTRACKED'
            emit(json.dumps({'status': 'RUNNING_UNTRACKED', 'reason': repr(error), 'output': str(p['out'])}))
    code = process.wait()
    observed, seconds = datetime.now(timezone.utc).isoformat(), time.monotonic()-started
    evidence = {'launch_sha256': launch_sha256}
    try:
        evidence['capture'] = {'ok': True, 'sha256': _capture(p, launch, launch_sha256, outcome=outcome,
                                                             code=code, observed=observed)}
    except Exception as error:  # noqa: BLE001 - an explicit capture failure; the postcheck still runs
        evidence['capture'] = {'ok': False, 'error': repr(error)}
        emit(json.dumps({'status': 'CAPTURE_FAILED', 'output': str(p['out']), 'reason': repr(error)}))
    return code, seconds, evidence


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
    # A review producer exits 1 with its one review error (the receipt check below); nothing else does.
    check('guard_exit', lambda: guard['workload_exit_confirmed'] is True and (
        type(guard['workload_exit_code']) is int and guard['workload_exit_code'] == 1 if review
        else guard['workload_exit_code'] == 0))
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
    """The runner sealed its interval for review: report it plainly; no reader, no adoption.

    Clean review evidence is guard wrapper exit 2 (its workload exited 1) with no postcheck
    failure; anything else is recorded as it is and is no parent (reviewed_parent).
    """
    failures, checks, resources = guard_postcheck(p['run'], receipt_status=F.REVIEW_STATUS, review=True)
    if code != 2:
        failures = [*failures, 'guard_wrapper_exit']
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


def reuse_milestone(receipt, seed):
    """Item 7: matching pins and consistent counts/bytes before any seeded runner succeeds."""
    reused = receipt.get('reused_initial_cache') if type(receipt) is dict else None
    if type(reused) is not dict:
        return None
    origin = reused.get('receipt')
    if reused.get('pinned_sha256') != seed['store_sha256'] or type(origin) is not dict or \
            origin.get('sha256') != seed['receipt_sha256']:
        return None
    counts = tuple(reused.get(name) for name in ('hits', 'misses', 'initial_component_queries'))
    if any(type(value) is not int or value < 0 for value in counts):
        return None
    hits, misses, queries = counts
    after = reused.get('after_sha256')
    if hits + misses != queries or type(after) is not str or len(after) != 64 or \
            any(character not in '0123456789abcdef' for character in after):
        return None
    full = after == seed['store_sha256']
    if reused.get('counts_agree_with_bytes') is not True or type(reused.get('full_reuse')) is not bool or \
            reused['full_reuse'] != full or (misses == 0) != full or \
            reused.get('status') != ('FULL_REUSE' if full else 'MISSES_MEASURED'):
        return None
    return {name: reused.get(name) for name in REUSE_FIELDS}


def cancellation_proved(p, tracking):
    """Exact exited identities plus the final guardian's complete job-cleanup proof."""
    guard = OG._retry_sharing(lambda: LM._read(p['guard']), 'cancelled guard read') or {}
    control = OG._retry_sharing(lambda: LM._read(p['control']), 'cancelled control read') or {}
    return (guard.get('schema') == LM.GUARD_SCHEMA and
            guard.get('status') in ('STOPPED', 'PARENT_EXITED', 'HARD_STOPPED', 'GUARDIAN_FAILED') and
            guard.get('workload_exit_confirmed') is True and guard.get('cleanup') == LM.CLEAN and
            'cleanup_error' not in guard and guard.get('parent') == tracking.get('parent') and
            guard.get('guardian', {}).get('pid') == tracking.get('guardian', {}).get('pid') and
            guard.get('nonce') == control.get('nonce') and control.get('parent') == guard.get('parent') and
            not any(OG.process_alive(identity) for identity in guard.get('launch_cohort', [])) and
            not LM._matching_processes([str(p['out'])+os.sep]))


def fallback_approval(path, pin, *, failed_pin, profile, stage, number, original, directory):
    """A pinned closed decision from the named coordinating chat, for exactly one failure."""
    approval, approval_pin = OR.read_json(RUN.ordinary(Path(path)), limit=65536, pin=LM._sha(pin))
    fields = {'schema', 'coordinator_thread_id', 'approved', 'failed_stage_sha256', 'profile_sha256',
              'stage', 'interval', 'reason', 'failed_attempt', 'fresh_directory', 'coordinator_approval'}
    require(set(approval) == fields and approval['schema'] == FALLBACK_APPROVAL_SCHEMA and
            approval['coordinator_thread_id'] == FALLBACK_COORDINATOR and approval['approved'] is True and
            approval['failed_stage_sha256'] == failed_pin and approval['profile_sha256'] == profile.sha256 and
            approval['stage'] == stage and type(approval['interval']) is int and approval['interval'] == number and
            approval['failed_attempt'] == str(original) and approval['fresh_directory'] == str(directory) and
            type(approval['reason']) is str and approval['reason'] in OC.ELIGIBLE_FALLBACK and
            type(approval['coordinator_approval']) is str and approval['coordinator_approval'].strip(),
            'specific coordinating-chat approval for this exact failed stage/profile/reason/sibling required')
    return approval, approval_pin


def _producer_capture(p, *, profile, stage, number, arm):
    """A reconstructed producer success still needs its immutable zero-exit parent capture."""
    launch, launch_pin = OR.read_json(p['run']['launch'], limit=CAPTURE_JSON_BYTES)
    capture, capture_pin = OR.read_json(p['run']['capture'], limit=CAPTURE_JSON_BYTES)
    binding = {'arm': arm, 'stage': stage, 'interval': number, 'step': 'runner',
               'attempt': str(p['attempt']), 'output': str(p['run']['out'])}
    lifecycle = capture.get('lifecycle', {})
    require(launch.get('schema') == STEP_LAUNCH_SCHEMA and capture.get('schema') == STEP_CAPTURE_SCHEMA and
            capture.get('capture_mode') == 'launching-parent' and
            launch.get('binding') == capture.get('binding') == binding and
            launch.get('profile') == {'path': str(profile.path), 'sha256': profile.sha256} and
            capture.get('launch_record_sha256') == launch_pin and
            lifecycle.get('launcher_outcome') == 'RUNNING' and
            type(lifecycle.get('process_exit_code')) is int and lifecycle['process_exit_code'] == 0 and
            lifecycle.get('guard_status') == 'STOPPED' and lifecycle.get('guard_reason') is None and
            lifecycle.get('workload_exit_confirmed') is True and
            type(lifecycle.get('workload_exit_code')) is int and lifecycle['workload_exit_code'] == 0 and
            type(capture.get('files')) is dict and set(capture['files']) == set(CAPTURE_FILES),
            'fallback requires the original producer zero-exit immutable launch/capture binding')
    for name in CAPTURE_FILES:
        observed, _ = OG._retry_sharing(lambda: _file_row(p['run'][name], retain=False),
                                        'original producer capture evidence')
        require(observed == capture['files'][name], 'producer evidence changed after its capture: '+name)
    return {'launch_sha256': launch_pin, 'capture': {'ok': True, 'sha256': capture_pin}}


def fallback_preflight(profile_path, profile_sha256, *, stage, failed_stage_sha256, fallback_approval_path,
                       fallback_approval_sha256, arm, python=None, environ=None, interval=None,
                       booking_bytes=None, booking_basis=None):
    """Read-only recovery of one failed overlap; no producer command or claim is created."""
    require(os.name == 'nt', 'Windows job-object launch required')
    require(stage in STAGES and type(arm) is str and arm, 'explicit stage and original arm required')
    number = F.interval_number(stage, interval)
    failed_pin = LM._sha(failed_stage_sha256)
    profile = F.FreshProfile.read(Path(profile_path), LM._sha(profile_sha256))
    row = profile.record()
    original_paths, p = paths(row, stage, interval), paths(row, stage, interval, fallback=True)
    RUN.ordinary(p['attempt'], directory=True)
    original, directory = original_paths['reader']['out'], p['reader']['out']
    failed, _ = OR.read_json(p['record'], limit=CAPTURE_JSON_BYTES, pin=failed_pin)
    observed, failed_raw = OG._retry_sharing(lambda: _file_row(p['record']), 'failed stage byte snapshot')
    require(observed['sha256'] == failed_pin and failed_raw is not None, 'failed stage changed before snapshot')
    approval, approval_pin = fallback_approval(fallback_approval_path, fallback_approval_sha256,
        failed_pin=failed_pin, profile=profile, stage=stage, number=number, original=original, directory=directory)
    ordinary_failure = (failed.get('status') == 'FAILED' and failed.get('failed_step') == 'overlap' and
                        type(failed.get('overlap_failure')) is dict)
    launcher_loss_recovery = (approval['reason'] == 'launcher_lost' and
        failed.get('status') in {'PREFLIGHT_PASSED', 'STARTED', 'RUNNING'} and
        'failed_step' not in failed and 'overlap_failure' not in failed)
    overlap = failed.get('overlap')
    require(failed.get('schema') == STAGE_SCHEMA and (ordinary_failure or launcher_loss_recovery) and
            failed.get('stage') == stage and
            type(failed.get('interval')) is int and failed.get('interval') == number and failed.get('profile') ==
            {'path': str(profile.path), 'sha256': profile.sha256} and type(overlap) is dict and
            overlap.get('completed_overlap') is False and failed.get('dev_timing') is False and
            failed.get('stop_before_advance') is False and 'sequential_fallback' not in failed and
            type(failed.get('launcher')) is dict,
            'fallback requires this pinned ordinary failed overlap stage, never a prior fallback')
    spec = OR.validate_spec(overlap.get('wait_spec'))
    require(spec['attempt'] == str(p['attempt'].resolve()) and spec['stage'] == stage and
            spec['interval'] == number and spec['profile_sha256'] == profile.sha256 and
            failed.get('launcher', {}).get('pid') == spec['launcher']['pid'] and
            failed['launcher'].get('sha256') == _SELF_SHA and
            failed['launcher'].get('monitored_helpers_sha256') == LM._SELF_SHA and
            OG.process_alive(spec['launcher']) is False,
            'the exact original overlap launcher must be gone with unchanged launcher sources')
    pins = _pinned_sources(profile)
    require(failed.get('pinned_sources') == pins, 'fallback source pins differ from the failed stage')
    composition = _composition_root(row, LM._pinned_manifest(row)[1])
    require(failed.get('composition_root') == composition, 'fallback composition differs from the failed stage')
    failed_evidence = OR.validate_failed_overlap(original, reason=approval['reason'], directory=directory,
                                                  receipt_limit=RF.RO.MAX_RECEIPT)
    require((failed_evidence['profile_sha256'], failed_evidence['stage'], failed_evidence['interval']) ==
            (profile.sha256, stage, number), 'failed reader evidence differs from the approved stage')
    failed_receipt, _ = OR.read_json(original/'reopen.json', limit=RF.RO.MAX_RECEIPT,
                                     pin=failed_evidence['failed_receipt_sha256'])
    require(failed_receipt.get('overlap_wait_spec') == spec, 'failed stage and reader wait specifications differ')
    snapshot = p['record'].with_name(p['record'].stem+'.overlap-failed.json')
    claim = original/'sequential-fallback.claim.json'
    for item in (snapshot, claim, directory, p['reader']['tracking'], p['reader']['log'],
                 p['reader']['launch'], p['reader']['capture']):
        require(not item.exists(), 'one fresh fallback and immutable evidence paths required: '+str(item))
    environ = dict(os.environ if environ is None else environ)
    require(LM._dev_timing_enabled(False, environ) is False, 'fallback refuses instrumentation resolved from the environment')
    require(not any(name in environ for name in LM.HOOK_ENV), 'instrumentation/import-path environment refused')
    require(environ.get('PYTHONHASHSEED') in (None, '0'), 'PYTHONHASHSEED must be unset or 0')
    python = LM._ordinary(sys.executable if python is None else python)
    env = F.pressure_launch_environment(environ)
    require(str(python) == failed.get('python') and failed.get('env') == {name: env[name] for name in LM.LAUNCH_ENV},
            'fallback interpreter/environment differs from the failed stage')
    require(not LM._pending_reboot(), 'pending Windows restart')
    require(not LM._matching_processes([str(p['attempt'])+os.sep, str(profile.path)]),
            'a live process still names this attempt or profile')
    sources = F.FreshSources(profile)
    sources.verify()
    sources.check_imported()
    with sources.selected():
        driver = sources.module(F.DRIVER)
        require(driver.ALE_PARALLEL == {'mode': 'serial', 'workers': 2} and
                driver.PARALLEL == {'mode': 'auto', 'workers': 2} and
                driver.SUCCESSOR_ALE_POLICY == 'authenticated-parent-four-or-six',
                'fallback must retain interval-one serial ALE, pressure and authenticated successor policy')
    failures, checks, resources = guard_postcheck(p['run'], receipt_status=F.SEALED_STATUS[stage])
    require(not failures, 'fallback producer postcheck failed: '+str(failures))
    capture = _producer_capture(p, profile=profile, stage=stage, number=number, arm=arm)
    run_sha = OG._retry_sharing(lambda: LM.file_hash(p['run']['receipt']), 'fallback producer receipt pin')
    steps = failed.get('steps')
    require(type(steps) is list and all(type(step) is dict for step in steps), 'failed stage steps required')
    runner_steps = [step for step in steps if step.get('name') == 'runner']
    require(len(runner_steps) <= 1 and all(step.get('ok') is True and step.get('exit') == 0 and
            step.get('receipt_sha256') == run_sha for step in runner_steps),
            'an originally failed or changed producer cannot be reconstructed as passed')
    require(not launcher_loss_recovery or len(runner_steps) == 1,
            'launcher-loss recovery requires the producer success already recorded by its original launcher')
    capture_reference = (runner_steps[0] if runner_steps else
                         failed.get('overlap_failure', {}).get('captured_steps', {}).get('runner', {}))
    require({name: capture_reference.get(name) for name in ('launch_sha256', 'capture')} == capture,
            'producer launch and capture pins differ from the original pinned stage evidence')
    recorded_run_sha = failed.get('overlap_failure', {}).get('producer_receipt_sha256')
    require(recorded_run_sha is None or recorded_run_sha == run_sha, 'failed-stage producer pin changed')
    producer = OG._retry_sharing(lambda: RF.producer_inputs(profile, sources=sources, mode=stage,
        receipt_sha256=run_sha, consumer_pid=os.getpid(), interval=interval), 'fallback producer native preflight')
    require(producer.get('review') is False and producer.get('mode') == stage and producer.get('interval') == number,
            'fallback requires the same ordinary sealed producer')
    producer_pins = RF.producer_gate_pins(profile, producer, mode=stage, interval=interval)
    reuse = {}
    seed = failed.get('initial_measurement_seed')
    if seed is not None:
        require(stage == 'interval' and seed == initial_measurement_seed(row), 'original measurement seed changed')
        milestone = reuse_milestone(LM._read(p['run']['receipt']), seed)
        require(milestone is not None, 'fallback producer has no valid original measurement-reuse milestone')
        reuse['reused_initial_cache'] = milestone
    if number >= 2:
        parent = failed.get('parent') or {}
        parent_pin = parent.get('adopted_sha256') if parent.get('route') == 'review-adopted' else None
        require(parent_adoption(row, number, parent_pin) == parent, 'fallback parent adoption changed')
    gate = SG.decide({'route': 'fresh-reader-sequential-fallback', 'stage': stage, 'interval': number,
                      'profile_sha256': profile.sha256, 'source_manifest_sha256': row['source_manifest']['sha256'],
                      'reader_initial_workers': 0}, measured=(), booking=(booking_bytes, booking_basis))
    available = LM._available_bytes()
    admitted = SG.admit(gate, available)
    required = (RUN.COMPACT_STORE_LIMITS['max_store_bytes'] + RUN.COMPACT_STORE_LIMITS['max_staging_bytes'] +
                row['completed_query_limits']['max_store_bytes'])
    require(LM._disk_free(Path(row['store_directory']).parent) >= required, 'insufficient fallback disk headroom')
    runner = {'name': 'runner', 'ok': True, 'exit': 0, 'receipt_sha256': run_sha, 'checks': checks,
              'resources': resources, **capture, **reuse, 'reconstructed_postcheck': True,
              'originally_recorded_pass': bool(runner_steps),
              'wall_seconds': runner_steps[0].get('wall_seconds') if runner_steps else None}
    return {'profile': profile, 'row': row, 'paths': p, 'original_paths': original_paths, 'env': env,
            'python': python, 'interval': interval, 'sources': sources, 'gate': gate, 'admitted': admitted,
            'record': failed, 'failed_raw': failed_raw, 'failed_pin': failed_pin, 'snapshot': snapshot,
            'recovered_after_launcher_loss': launcher_loss_recovery,
            'approval': approval, 'approval_path': str(Path(fallback_approval_path).resolve()),
            'approval_pin': approval_pin, 'failed_evidence': failed_evidence, 'producer_pins': producer_pins,
            'claim_path': claim, 'runner': runner, 'seed': seed}


def run_fallback_plan(plan, *, stage, emit, arm):
    """Consume the exclusive fallback claim, run only the fresh reader, then normal finalise/adopt."""
    profile, row, p, env = (plan[name] for name in ('profile', 'row', 'paths', 'env'))
    original = plan['original_paths']['reader']['out']
    sources = plan['sources']
    next_source = 0.
    def checkpoint(force=False):
        nonlocal next_source
        now = time.monotonic()
        if force or now >= next_source:
            sources.verify()
            sources.check_imported()
            _pinned_sources(profile)
            next_source = now+10
    checkpoint(force=True)
    require(LM.file_hash(p['record']) == plan['failed_pin'], 'failed stage changed before exclusive fallback claim')
    OR.read_json(plan['approval_path'], limit=65536, pin=plan['approval_pin'])
    require(OR.validate_failed_overlap(original, reason=plan['approval']['reason'], directory=p['reader']['out'],
        receipt_limit=RF.RO.MAX_RECEIPT) == plan['failed_evidence'], 'failed evidence changed before fallback claim')
    producer = RF.producer_inputs(profile, sources=sources, mode=stage,
        receipt_sha256=plan['runner']['receipt_sha256'], consumer_pid=os.getpid(), interval=plan['interval'])
    require(RF.producer_gate_pins(profile, producer, mode=stage, interval=plan['interval']) == plan['producer_pins'],
            'producer changed before fallback claim')
    with plan['snapshot'].open('xb') as stream:
        stream.write(plan['failed_raw'])
        stream.flush()
        os.fsync(stream.fileno())
    claim = {'failed_attempt': str(original), 'reason': plan['approval']['reason'],
             'fresh_directory': str(p['reader']['out']),
             'coordinator_approval': plan['approval_path']+'@'+plan['approval_pin']}
    OC.fallback_decision(failed_attempt=str(original), failure_reason=claim['reason'], producer_valid=True,
        approval=claim, directory=p['reader']['out'], claim_path=plan['claim_path'])
    claim_pin = LM.file_hash(plan['claim_path'])
    binding = OR.validate_fallback_claim(plan['claim_path'], pin=claim_pin, original=original,
        directory=p['reader']['out'], receipt_limit=RF.RO.MAX_RECEIPT)
    record = plan['record']
    record['steps'] = [plan['runner']]
    record['overlap']['completed_overlap'] = False
    record['sequential_fallback'] = {'failed_stage': {'path': str(plan['snapshot']), 'sha256': plan['failed_pin']},
        'approval': {'path': plan['approval_path'], 'sha256': plan['approval_pin']}, 'binding': binding,
        'start_gate': plan['admitted'], 'producer_pins': plan['producer_pins']}
    record['sequential_fallback']['original_status'] = record['status']
    record['sequential_fallback']['recovered_after_launcher_loss'] = plan.get('recovered_after_launcher_loss', False)
    record.update(status='SEQUENTIAL_FALLBACK_STARTED', launcher={'pid': os.getpid(),
        'path': str(Path(__file__).resolve()), 'sha256': _SELF_SHA, 'monitored_helpers_sha256': LM._SELF_SHA})
    record.pop('failed_step', None)
    record.pop('reason', None)
    _save(p['record'], record)
    common = ['--profile', str(profile.path), '--profile-sha256', profile.sha256, '--mode', stage,
              *(['--interval', str(plan['interval'])] if plan['interval'] is not None else [])]
    def step(name, **values):
        record['steps'].append({'name': name, 'utc': datetime.now(timezone.utc).isoformat(), **values})
        _save(p['record'], record)
    name, task, evidence, captured = 'reader', None, {}, False
    def capture(code):
        nonlocal captured
        if captured:
            return
        try:
            evidence['capture'] = {'ok': True, 'sha256': _capture(p['reader'], launch, evidence['launch_sha256'],
                outcome='RUNNING', code=code, observed=datetime.now(timezone.utc).isoformat())}
        except Exception as error:
            evidence['capture'] = {'ok': False, 'error': repr(error)}
        captured = True
    try:
        checkpoint(force=True)
        argv = RF.command(profile, plan['python'], mode=stage, producer_receipt_sha256=plan['runner']['receipt_sha256'],
            start_gate=plan['gate'], interval=plan['interval'], fallback=True, fallback_claim_sha256=claim_pin)
        launch_binding = {'arm': arm, 'stage': stage, 'interval': record['interval'], 'step': 'reader',
                          'attempt': str(p['attempt'])}
        launch = step_launch(argv, env, p['reader'], binding=launch_binding, profile=profile, stage_record=p['record'])
        evidence['launch_sha256'] = LM._write_exclusive(p['reader']['launch'], launch)
        task = OC.start(argv, env, p['reader'], await_running=LM._await_running, track=LM._track,
                        confirm_exit=cancellation_proved, emit=emit)
        code, seconds = OC.wait(task, check_sources=checkpoint)
        capture(code)
        checkpoint(force=True)
        failures, checks, resources = guard_postcheck(p['reader'], receipt_status=RF.WORKLOAD_STATUS[stage])
        require(code == 0 and not failures, 'sequential fallback reader did not pass cleanly: '+str(failures))
        reopen_sha = LM.file_hash(p['reader']['receipt'])
        step('reader', ok=True, exit=code, wall_seconds=seconds, receipt_sha256=reopen_sha,
             checks=checks, resources=resources, **evidence)
        name = 'finalise'
        code, result, seconds, errors = _tool(plan['python'], env, '--finalise', *common,
            '--producer-receipt-sha256', plan['runner']['receipt_sha256'], '--reopen-receipt-sha256', reopen_sha,
            '--reader-fallback', '--fallback-claim-sha256', claim_pin)
        require(code == 0 and result and result.get('status') == F.READER_PASS[stage],
                'fallback finalise refused: '+str({'exit': code, 'result': result, 'stderr': errors}))
        step('finalise', ok=True, wall_seconds=seconds, verdict_sha256=result['verdict_sha256'],
             width_gate_passed=result.get('width_gate_passed'))
        checkpoint(force=True)
        name = 'adopt'
        code, adopted, seconds, errors = _tool(plan['python'], env, '--adopt', *common,
                                              '--verdict-sha256', result['verdict_sha256'])
        require(code == 0 and adopted and adopted.get('status') == RF.ADOPTED_STATUS,
                'fallback adoption refused or uncertain; never retry blindly: '+str(
                    {'exit': code, 'result': adopted, 'stderr': errors}))
        step('adopt', ok=True, wall_seconds=seconds, adopted_sha256=adopted['sha256'])
        checkpoint(force=True)
        width = result.get('width_gate_passed')
        record.update(status=GATE_STOP if stage == 'interval' and width is False else ADOPTED,
                      store_directory=RUN._tree(Path(row['store_directory'])), width_gate_passed=width)
        _save(p['record'], record)
        emit(json.dumps({'status': record['status'], 'stage': stage, 'record': str(p['record']),
                         'sequential_fallback': True, 'completed_overlap': False}))
        return 0
    except BaseException as error:
        cleanup = []
        if task is not None:
            try:
                cleanup.append(OC.cancel_and_confirm(task, timeout_seconds=30))
                capture(task.process.returncode)
            except BaseException as failure:
                cleanup.append({'output': str(task.paths['out']), 'unconfirmed': repr(failure)})
                error.add_note('fallback cancellation confirmation failed: '+repr(failure))
        record['sequential_fallback']['failure'] = {'error': F._error(error),
            'notes': list(getattr(error, '__notes__', ())), 'cleanup': cleanup, 'step_evidence': evidence}
        record.update(status='FAILED', failed_step=name, reason=repr(error))
        step(name, ok=False, reason=repr(error), **(evidence if name == 'reader' else {}))
        emit(json.dumps({'status': 'FAILED', 'stage': stage, 'step': name, 'reason': repr(error)}))
        return 130 if isinstance(error, KeyboardInterrupt) else 1


def run_overlap_plan(plan, *, stage, emit, arm):
    """Phase2 only: current producer and independent SERIAL reader; no next producer."""
    require(type(arm) is str and arm, 'explicit capture arm required')
    profile, row, p, env, record = (plan[name] for name in ('profile', 'row', 'paths', 'env', 'record'))
    config, decisions, interval = plan['overlap'], plan['decisions'], plan['interval']
    sources = F.FreshSources(profile)
    sources.verify()
    _pinned_sources(profile)
    gate_path = OR.gate_path(p['attempt'], stage, record['interval'])
    launcher = OG.process_identity(os.getpid())
    spec = {'schema': OR.SPEC_SCHEMA, 'gate_path': str(gate_path), 'attempt': str(p['attempt'].resolve()),
            'stage': stage, 'interval': record['interval'], 'profile_sha256': profile.sha256,
            'launcher': launcher, 'launcher_nonce': secrets.token_hex(32),
            'timeout_seconds': config['wait_seconds'], 'wait_basis': config['wait_basis']}
    OR.validate_spec(spec)
    record['overlap']['wait_spec'] = spec
    LM._write_exclusive(p['record'], record)
    gate_path.parent.mkdir(exist_ok=False)
    observer = OM.CohortObserver(os.getpid(), output_roots=(p['attempt'], Path(row['store_directory']),
                                  Path(row['workspace'])/row['completed_query_directory']))
    tasks, captures = [], {}
    next_source = 0.

    def checkpoint(force=False):
        nonlocal next_source
        observer.sample(force=force)
        now = time.monotonic()
        if force or now >= next_source:
            sources.verify()
            sources.check_imported()
            _pinned_sources(profile)
            next_source = now+10

    def save():
        record['overlap']['observations'] = observer.record()
        _save(p['record'], record)

    def step(name, **values):
        record['steps'].append({'name': name, 'utc': datetime.now(timezone.utc).isoformat(),
                                **captures.pop(name, {}), **values})
        save()

    def start(name, argv, q):
        checkpoint(force=True)
        binding = {'arm': arm, 'stage': stage, 'interval': record['interval'], 'step': name,
                   'attempt': str(p['attempt'])}
        launch = step_launch(argv, env, q, binding=binding, profile=profile, stage_record=p['record'])
        pin = LM._write_exclusive(q['launch'], launch)
        task = OC.start(argv, env, q, await_running=LM._await_running, track=LM._track,
                        confirm_exit=cancellation_proved, emit=emit)
        task.launch, task.launch_sha256, task.step_name, task.captured = launch, pin, name, False
        tasks.append(task)
        return task

    def capture(task, code):
        if task.captured:
            return
        evidence = {'launch_sha256': task.launch_sha256}
        try:
            evidence['capture'] = {'ok': True, 'sha256': _capture(task.paths, task.launch, task.launch_sha256,
                outcome='RUNNING', code=code, observed=datetime.now(timezone.utc).isoformat())}
        except Exception as error:  # preserve original N9 capture-failure semantics
            evidence['capture'] = {'ok': False, 'error': repr(error)}
        captures[task.step_name] = evidence
        task.captured = True

    def wait(task):
        result = OC.wait(task, check_sources=checkpoint)
        capture(task, result[0])
        return result

    run_sha = None
    try:
        producer_task = start('runner', plan['argv'], p['run'])
        reader_argv = RF.command(profile, plan['python'], mode=stage, producer_receipt_sha256=None,
                                 start_gate=decisions['reader'], interval=interval, overlap_spec=spec)
        reader_task = start('reader', reader_argv, p['reader'])
        code, seconds = wait(producer_task)
        status = (LM._read(p['run']['receipt']) or {}).get('status')
        failures, checks, resources = guard_postcheck(p['run'], receipt_status=F.SEALED_STATUS[stage])
        if code != 0 or failures or status == F.REVIEW_STATUS:
            step('runner', ok=False, exit=code, wall_seconds=seconds, failures=failures,
                 checks=checks, resources=resources)
            raise StageRefused('overlap producer did not seal cleanly; no gate published')
        run_sha = OG._retry_sharing(lambda: LM.file_hash(p['run']['receipt']), 'producer receipt hash')
        reuse = {}
        if plan['seed'] is not None:
            milestone = reuse_milestone(LM._read(p['run']['receipt']), plan['seed'])
            require(milestone is not None, 'seeded runner recorded no consistent reuse for selected pins')
            reuse['reused_initial_cache'] = milestone
        step('runner', ok=True, exit=code, wall_seconds=seconds, receipt_sha256=run_sha, resources=resources, **reuse)
        # RF.command-equivalent store-free preflight remains before publication.
        producer = OG._retry_sharing(lambda: RF.producer_inputs(profile, sources=sources, mode=stage,
            receipt_sha256=run_sha, consumer_pid=os.getpid(), interval=interval), 'publication producer preflight')
        pins = RF.producer_gate_pins(profile, producer, mode=stage, interval=interval)
        require(reader_task.process.poll() is None, 'overlap reader exited before gate publication')
        checkpoint(force=True)
        gate = dict(OR.expected_gate(spec, reader_task.tracking['parent']), schema=OG.SCHEMA, **pins)
        OG.validate_gate(gate, OR.expected_gate(spec, reader_task.tracking['parent']))
        OG.atomic_publish(gate_path, gate)
        record['overlap']['gate_sha256'] = gate_sha = OG.gate_sha256(gate)
        save()
        code, seconds = wait(reader_task)
        failures, checks, resources = guard_postcheck(p['reader'], receipt_status=RF.WORKLOAD_STATUS[stage])
        if code != 0 or failures:
            step('reader', ok=False, exit=code, wall_seconds=seconds, failures=failures,
                 checks=checks, resources=resources)
            raise StageRefused('independent overlap reader did not pass cleanly')
        reopen_sha = OG._retry_sharing(lambda: LM.file_hash(p['reader']['receipt']), 'reader receipt hash')
        step('reader', ok=True, exit=code, wall_seconds=seconds, receipt_sha256=reopen_sha, resources=resources)
        common = ['--profile', str(profile.path), '--profile-sha256', profile.sha256, '--mode', stage,
                  *(['--interval', str(interval)] if interval is not None else [])]
        checkpoint(force=True)
        code, result, seconds, errors = _tool(plan['python'], env, '--finalise', *common,
            '--producer-receipt-sha256', run_sha, '--reopen-receipt-sha256', reopen_sha,
            '--overlap-gate-sha256', gate_sha)
        require(code == 0 and result and result.get('status') == F.READER_PASS[stage],
                'overlap finalise refused: '+str({'exit': code, 'result': result, 'stderr': errors}))
        step('finalise', ok=True, wall_seconds=seconds, verdict_sha256=result['verdict_sha256'],
             width_gate_passed=result.get('width_gate_passed'))
        checkpoint(force=True)
        code, adopted, seconds, errors = _tool(plan['python'], env, '--adopt', *common,
                                               '--verdict-sha256', result['verdict_sha256'])
        require(code == 0 and adopted and adopted.get('status') == RF.ADOPTED_STATUS,
                'adoption refused or uncertain; never retry blindly: '+str({'exit': code, 'result': adopted, 'stderr': errors}))
        step('adopt', ok=True, wall_seconds=seconds, adopted_sha256=adopted['sha256'])
        checkpoint(force=True)
        width = result.get('width_gate_passed')
        record['overlap']['completed_overlap'] = True
        record.update(status=GATE_STOP if stage == 'interval' and width is False else ADOPTED,
                      store_directory=RUN._tree(Path(row['store_directory'])), width_gate_passed=width)
        save()
        emit(json.dumps({'status': record['status'], 'stage': stage, 'record': str(p['record'])}))
        return 0
    except BaseException as error:
        cleanup = []
        for task in reversed(tasks):
            try:
                cleanup.append(OC.cancel_and_confirm(task, timeout_seconds=30))
                capture(task, task.process.returncode)
            except BaseException as failure:
                cleanup.append({'output': str(task.paths['out']), 'unconfirmed': repr(failure)})
                error.add_note('overlap cancellation confirmation failed: '+repr(failure))
        record.update(status='FAILED', reason=repr(error), failed_step='overlap',
                      overlap_failure={'error': F._error(error), 'cleanup': cleanup,
                                       'notes': list(getattr(error, '__notes__', ())),
                                       'captured_steps': captures, 'producer_receipt_sha256': run_sha,
                                       'fallback': 'coordinator decision only; fresh directory; at most one'})
        record['overlap']['completed_overlap'] = False
        save()
        emit(json.dumps({'status': 'FAILED', 'stage': stage, 'reason': repr(error), 'cleanup': cleanup}))
        return 130 if isinstance(error, KeyboardInterrupt) else 1


def run_stage(profile_path, profile_sha256, *, stage, python=None, environ=None, dev_timing=False,
              stop_before_advance=False, reuse_initial_measurements=False, emit=print, peak_records=(),
              booking_bytes=None, booking_basis=None, interval=None, parent_adopted_sha256=None, arm=None, overlap=None,
              sequential_reader_fallback=False, failed_stage_sha256=None, fallback_approval_path=None,
              fallback_approval_sha256=None):
    require(type(arm) is str and bool(arm), 'an explicit arm label is required for the step launch records')
    fallback_pins = (failed_stage_sha256, fallback_approval_path, fallback_approval_sha256)
    require(type(sequential_reader_fallback) is bool and
            all(value is not None for value in fallback_pins) == sequential_reader_fallback and
            (sequential_reader_fallback or all(value is None for value in fallback_pins)),
            'explicit sequential fallback flag, failed-stage pin and pinned approval must occur together')
    if sequential_reader_fallback:
        require(overlap is None and not dev_timing and not stop_before_advance and not reuse_initial_measurements and
                parent_adopted_sha256 is None and not peak_records,
                'fallback cannot start a producer, overlap, smoke, changed reuse route or use unmatched peak records')
        plan = fallback_preflight(profile_path, profile_sha256, stage=stage, failed_stage_sha256=failed_stage_sha256,
            fallback_approval_path=fallback_approval_path, fallback_approval_sha256=fallback_approval_sha256,
            arm=arm, python=python, environ=environ, interval=interval,
            booking_bytes=booking_bytes, booking_basis=booking_basis)
        return run_fallback_plan(plan, stage=stage, emit=emit, arm=arm)
    plan = preflight(profile_path, profile_sha256, stage=stage, python=python, environ=environ,
                     dev_timing=dev_timing, stop_before_advance=stop_before_advance,
                     reuse_initial_measurements=reuse_initial_measurements, peak_records=peak_records,
                     booking_bytes=booking_bytes, booking_basis=booking_basis, interval=interval,
                     parent_adopted_sha256=parent_adopted_sha256, overlap=overlap)
    if overlap is not None:
        return run_overlap_plan(plan, stage=stage, emit=emit, arm=arm)
    profile, row, p, env, record = plan['profile'], plan['row'], plan['paths'], plan['env'], plan['record']
    LM._write_exclusive(p['record'], record)
    emit(json.dumps({'status': 'PREFLIGHT_PASSED', 'stage': stage, 'record': str(p['record']),
                     'memory_warning': record['memory']['warning']}))
    store = Path(row['store_directory'])
    common = ['--profile', str(profile.path), '--profile-sha256', profile.sha256, '--mode', stage,
              *(['--interval', str(interval)] if interval is not None else [])]

    evidence = {}

    def step(name, **values):
        record['steps'].append({'name': name, 'utc': datetime.now(timezone.utc).isoformat(),
                                **evidence.pop(name, {}), **values})
        _save(p['record'], record)

    def guarded(name, argv, q):
        binding = {'arm': arm, 'stage': stage, 'interval': record['interval'], 'step': name,
                   'attempt': str(p['attempt'])}
        try:
            launch = step_launch(argv, env, q, binding=binding, profile=profile, stage_record=p['record'])
        except (ValueError, OSError) as error:
            return None, stop(name, 'step launch record refused before Popen: %s' % (error,))
        try:
            code, seconds, evidence[name] = _guarded(argv, env, q, emit, launch)
        except StageRefused as error:
            return None, stop(name, str(error))
        return (code, seconds), None

    def stop(name, reason, **values):
        record.update(status='FAILED', failed_step=name, reason=reason)
        step(name, ok=False, reason=reason, **values)
        emit(json.dumps({'status': 'FAILED', 'stage': stage, 'step': name, 'reason': reason}))
        return 1

    try:
        done, refused = guarded('runner', plan['argv'], p['run'])
        if done is None:
            return refused
        code, seconds = done
        status = (LM._read(p['run']['receipt']) or {}).get('status')
        if status == F.REVIEW_STATUS:
            return review_stop(record, p, step, emit, stage=stage, code=code, seconds=seconds)
        expected = F.STOPPED_STATUS if stop_before_advance else F.SEALED_STATUS[stage]
        failures, checks, resources = guard_postcheck(p['run'], receipt_status=expected)
        if code != 0 or failures:
            return stop('runner', 'guarded runner did not seal cleanly', exit=code, failures=failures,
                        checks=checks, wall_seconds=seconds, resources=resources)
        run_sha = LM.file_hash(p['run']['receipt'])
        reuse = {}
        if plan['seed'] is not None:
            milestone = reuse_milestone(LM._read(p['run']['receipt']), plan['seed'])
            if milestone is None:
                return stop('runner', 'seeded runner recorded no measurement reuse for these pins', exit=code,
                            wall_seconds=seconds, resources=resources)
            reuse = {'reused_initial_cache': milestone}
        step('runner', ok=True, exit=code, wall_seconds=seconds, receipt_sha256=run_sha, resources=resources, **reuse)
        if reuse:
            emit(json.dumps({'status': 'MILESTONE', 'stage': stage, **reuse}))
        if stop_before_advance:
            # The smoke ends here: the adopted root was reopened and compared; nothing is sealed.
            record.update(status=F.STOPPED_STATUS, store_directory=RUN._tree(store))
            _save(p['record'], record)
            emit(json.dumps({'status': F.STOPPED_STATUS, 'stage': stage, 'record': str(p['record'])}))
            return 0
        argv = RF.command(profile, plan['python'], mode=stage, producer_receipt_sha256=run_sha, start_gate=plan['gate'],
                          interval=interval)
        done, refused = guarded('reader', argv, p['reader'])
        if done is None:
            return refused
        code, seconds = done
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
    parser.add_argument('--interval', type=int, help='interval stage only (item 21): interval N >= 2')
    parser.add_argument('--parent-adopted-sha256',
                        help='interval N >= 2 after a review-adopted interval N-1: its adoption record SHA-256')
    parser.add_argument('--dev-timing', action='store_true')
    parser.add_argument('--preflight-only', action='store_true', help='checks only; writes and launches nothing')
    parser.add_argument('--stop-before-advance', action='store_true',
                        help='interval stage only: the smoke; reopen the adopted root and stop')
    parser.add_argument('--reuse-initial-measurements', action='store_true',
                        help="interval stage only: start from run A's closed initial measurement store")
    parser.add_argument('--arm', help='N9 lf-r1: the explicit arm label bound into each step launch record')
    routes = parser.add_mutually_exclusive_group()
    routes.add_argument('--reader-overlap', action='store_true', help='phase2: this producer and its serial reader only')
    routes.add_argument('--sequential-reader-fallback', action='store_true',
                        help='one pinned coordinator-approved sequential reader; never starts another producer')
    parser.add_argument('--failed-stage-sha256')
    parser.add_argument('--fallback-approval', type=Path)
    parser.add_argument('--fallback-approval-sha256')
    parser.add_argument('--producer-booking-bytes', type=int)
    parser.add_argument('--producer-booking-basis')
    parser.add_argument('--reader-booking-bytes', type=int)
    parser.add_argument('--reader-booking-basis')
    parser.add_argument('--reader-wait-seconds', type=float)
    parser.add_argument('--reader-wait-basis')
    SG.add_arguments(parser)
    args = parser.parse_args(argv)
    emit = lambda line: print(line, flush=True)
    try:
        values = {'producer_booking_bytes': args.producer_booking_bytes,
                  'producer_booking_basis': args.producer_booking_basis,
                  'reader_booking_bytes': args.reader_booking_bytes,
                  'reader_booking_basis': args.reader_booking_basis,
                  'wait_seconds': args.reader_wait_seconds, 'wait_basis': args.reader_wait_basis}
        require(args.reader_overlap or all(value is None for value in values.values()),
                'reader overlap bookings/wait arguments require --reader-overlap')
        overlap = values if args.reader_overlap else None
        fallback_pins = (args.failed_stage_sha256, args.fallback_approval, args.fallback_approval_sha256)
        require(all(value is not None for value in fallback_pins) == args.sequential_reader_fallback and
                (args.sequential_reader_fallback or all(value is None for value in fallback_pins)),
                'sequential fallback requires its failed-stage pin and pinned approval together')
        if args.sequential_reader_fallback:
            require(not args.dev_timing and not args.stop_before_advance and not args.reuse_initial_measurements and
                    args.parent_adopted_sha256 is None and not args.peak_records,
                    'fallback cannot mix smoke, instrumentation, changed producer route or unmatched peak records')
            plan = fallback_preflight(args.profile, args.profile_sha256, stage=args.stage,
                failed_stage_sha256=args.failed_stage_sha256, fallback_approval_path=args.fallback_approval,
                fallback_approval_sha256=args.fallback_approval_sha256, arm=args.arm, interval=args.interval,
                booking_bytes=args.booking_bytes, booking_basis=args.booking_basis)
            if args.preflight_only:
                emit(json.dumps({'status': 'SEQUENTIAL_FALLBACK_PREFLIGHT_PASSED',
                    'reader_directory': str(plan['paths']['reader']['out']), 'start_gate': plan['admitted'],
                    'failed_stage_sha256': plan['failed_pin'], 'approval_sha256': plan['approval_pin'],
                    'producer_pins': plan['producer_pins']}))
                return 0
            return run_fallback_plan(plan, stage=args.stage, emit=emit, arm=args.arm)
        if args.preflight_only:
            plan = preflight(args.profile, args.profile_sha256, stage=args.stage, dev_timing=args.dev_timing,
                             stop_before_advance=args.stop_before_advance,
                             reuse_initial_measurements=args.reuse_initial_measurements, peak_records=args.peak_records,
                             booking_bytes=args.booking_bytes, booking_basis=args.booking_basis, interval=args.interval,
                             parent_adopted_sha256=args.parent_adopted_sha256, overlap=overlap)
            emit(json.dumps({'status': 'PREFLIGHT_PASSED', 'argv': plan['argv'], 'memory': plan['record']['memory'],
                             'start_gate': plan['record']['start_gate'],
                             'disk': plan['record']['disk'], 'initial_measurement_seed': plan['seed'],
                             'overlap': plan['record'].get('overlap')}))
            return 0
        return run_stage(args.profile, args.profile_sha256, stage=args.stage, dev_timing=args.dev_timing,
                         stop_before_advance=args.stop_before_advance,
                         reuse_initial_measurements=args.reuse_initial_measurements, emit=emit,
                         peak_records=args.peak_records, booking_bytes=args.booking_bytes,
                         booking_basis=args.booking_basis, interval=args.interval,
                         parent_adopted_sha256=args.parent_adopted_sha256, arm=args.arm, overlap=overlap)
    except (ValueError, OSError) as error:
        emit(json.dumps({'status': 'REFUSED', 'type': type(error).__name__, 'reason': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
