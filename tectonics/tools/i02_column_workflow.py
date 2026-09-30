"""I02.6 backend workflow of the first I02 route: create, advance, inspect, cancel, save, load and continue.

SPDX-License-Identifier: AGPL-3.0-only
WORKING NON-CANON. Trusted local paths only; no HTTP server, detached process or scheduler. A project holds one
ledger of the supported layered finite-strain column (cases/i02_column_workflow_v1.json) in its own native
ArrayStore. ``advance`` runs attached to its caller under the project's worker lock and commits whole steps of the
fixed global schedule through the package's accepted clock; ``cancel`` writes a request that the running worker
polls between steps, and every accepted step is kept. ``status`` and ``inspect`` read a consistent read-only
snapshot of the ledger and never run physics or write the project. ``save`` is a consistent online backup of the
ledger store; ``load`` checks that every commit of a saved project restores consistently (ranges, step relations and
identities; a saved project is trusted input, so this is not a check of who wrote it) and restores it into a new
project, which ``advance`` continues only under the same source and runtime identity. The managed-job seams of
tectonics_job.py (process lock, atomic JSON files, error codes) are reused. Operational timings stay in status files
and are never recorded in a state; but where a deadline or a separate request ends a process, the next request
re-solves its starting stage cold, so the continued history agrees with an unsplit one within the retained parity,
not bitwise.
Every command prints one JSON line. It exits 0 with status "ok" when the command did its work, including an advance
that stopped early, was cancelled or was refused by a retained check (its run state says which); otherwise it exits 2
with status "error": an advance whose run failed (including one whose ledger another writer advanced outside the
worker lock) still answers with its project, and an interrupted command still prints its line. Not a generated world
and not the I10 project/UI route.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid

from threadpoolctl import threadpool_limits

import read_tectonics as reader
import tectonics_job as jobs

ROOT = Path(__file__).resolve().parents[1]
CASE = 'cases/i02_column_workflow_v1.json'
SCHEMA = 'atlas.i02-column-workflow.v1'
CASE_SCHEMA = 'atlas.i02-column-workflow-case.v1'
PROJECT_SCHEMA = 'atlas.i02-column-project.v1'
STATUS_SCHEMA = 'atlas.i02-column-project-status.v1'
PROJECT_ID = re.compile(r'[0-9a-f]{32}\Z')
INPUTS = ('weakening_case', 'column_heat_case', 'motion_case', 'finite_strain_case')
# Files whose bytes define what this workflow runs besides the package; the package itself and its runtime are bound
# by the execution identity (atlas_tectonics.reuse.ExecutionContext).
SOURCES = ('tools/i02_column_workflow.py', 'tools/tectonics_job.py', 'tools/read_tectonics.py', CASE,
           'cases/i01_weakening_v1.json', 'cases/i01_column_heat_v1.json', 'cases/i01_motion_coupling_v1.json',
           'cases/i01_finite_strain_v1.json')
RUN_STATES = ('running', 'completed', 'partial', 'cancelled', 'refused', 'failed', 'interrupted')
MAX_JSON = 64 << 10
JobError = jobs.JobError


# ----------------------------------------------------------------------------- identities, case and store

def identities():
    """(source_id, runtime_id): this workflow's declared files, and the package's execution identity."""
    digest = hashlib.sha256(b'atlas.i02-column-workflow-sources.v1')
    for name in SOURCES:
        data = reader._path(ROOT/name, maximum=4 << 20).read_bytes()
        digest.update(b'\0'+name.encode()+b'\0'+hashlib.sha256(data).digest())
    from atlas_tectonics.reuse import ExecutionContext
    with ExecutionContext('scipy') as context:
        runtime_id = context.identity
    return digest.hexdigest(), runtime_id


def case():
    spec = reader._read_json(reader._path(ROOT/CASE, maximum=MAX_JSON), MAX_JSON)
    if (type(spec) is not dict or spec.get('schema') != CASE_SCHEMA or set(spec.get('inputs', ())) != set(INPUTS)
            or type(spec.get('schedule')) is not dict or set(spec['schedule']) != {'duration_s', 'steps'}):
        raise JobError('INVALID_CASE', 'The workflow case is not a supported I02 column case.')
    inputs = {name: reader._read_json(reader._path(ROOT/spec['inputs'][name], maximum=1 << 20), 1 << 20)
              for name in INPUTS}
    return spec, inputs


def build_root(spec, inputs, source_id, runtime_id):
    """The declared initial common state of the case, prepared by the package alone; nothing is hand-assembled."""
    import numpy as np
    from atlas_tectonics import (_integration_heat as H, _integration_motion as M, _integration_weakening as W,
                                 integration_state as I)
    from atlas_tectonics.materials import MaterialCohort, MaterialState
    from atlas_tectonics.mesh import ColumnGrid1D
    weak, heat, motion, finite = (inputs[name] for name in INPUTS)
    rep, order = weak['representation'], spec['column']['order']
    layers = copy.deepcopy(weak['layers'])
    for layer in layers:                     # the retained fixture's zero temperature offset, which yields floats
        layer['temperature_k'] = [t+0. for t in layer['temperature_k']]
    key = (layers, order, W.LITHOSTATIC, rep['gravity_m_s2'])
    thermal_inputs = dict(thicknesses=[layer['thickness_m'] for layer in layers], props=heat['thermal_layers'],
                          densities=[layer['density_kg_m3'] for layer in layers], boundaries=heat['boundaries'],
                          reference_temperature=None)
    base = W.prepare(layers, order, closure=rep['pressure_closure'], gravity=rep['gravity_m_s2'])
    thermal = H.prepare_thermal(base.layer, base.depth_m, base.weight, thermal_inputs['thicknesses'],
                                thermal_inputs['props'], thermal_inputs['densities'], thermal_inputs['boundaries'],
                                mechanical_fingerprint=base.fingerprint)
    reference = I.ColumnReference(
        mechanical=dict(key=key, fingerprint=base.fingerprint, layer=base.layer, depth_m=base.depth_m,
                        weight=base.weight, reference_pa=base.reference_pa, density=base.density,
                        thickness_m=base.thickness_m),
        thermal=dict(provider=I.COLUMN_THERMAL_BASIS, inputs=thermal_inputs, fingerprint=thermal.fingerprint,
                     mechanical_fingerprint=thermal.mechanical_fingerprint, layer=thermal.layer,
                     depth_m=thermal.depth_m, volume_m=thermal.volume_m,
                     reference_density_kg_m3=thermal.reference_density_kg_m3, capacity=thermal.capacity,
                     radiogenic=thermal.radiogenic, steady_k=thermal.steady_k,
                     boundary_temperature=thermal.boundary_temperature, thickness_m=thermal.thickness_m))
    law = W.WeakeningLaw.from_spec(weak['weakening'])
    drive = M.Drive(motion['drive_n_m'], motion['drag_pa_s'], motion['width_m'])
    settings = I.ColumnSettings(
        representation=finite['representation'],
        law=dict(start=law.start, end=law.end, cohesion_factor=law.cohesion_factor,
                 friction_factor=law.friction_factor),
        drive=dict(force_n_m=drive.force_n_m, drag_pa_s=drive.drag_pa_s, width_m=drive.width_m),
        heat_fractions=tuple(spec['column']['heat_fractions']), policy=finite['policy'], schedule=spec['schedule'])
    labels = spec['identity']
    ids = tuple('layer-%d-%s' % (k, layer['name']) for k, layer in enumerate(layers))
    cohorts = {cohort: (MaterialCohort(cohort, layer['name'], '%s#layers/%d' % (spec['inputs']['weakening_case'], k),
                                       None), float(layer['thickness_m']))
               for k, (cohort, layer) in enumerate(zip(ids, layers))}
    ordered = sorted(cohorts)
    materials = MaterialState(ColumnGrid1D([0., drive.width_m], frame_id=labels['frame_id']),
                              tuple(cohorts[c][0] for c in ordered), [[cohorts[c][1]] for c in ordered],
                              time_s=labels['start_time_s'], epoch_id=labels['epoch_id'])
    identity = I.StateIdentity(world_id=labels['world_id'], scenario_id=labels['scenario_id'],
                               epoch_id=labels['epoch_id'], source_id=source_id, runtime_id=runtime_id,
                               unit_system=I.UNIT_SYSTEM)
    theta0 = spec['initial_departure']['amplitude_k']*np.sin(2.*math.pi*np.asarray(base.depth_m)/base.thickness_m)
    kappa0 = np.asarray(weak['campaign']['initial_history_by_layer'], dtype=float)[base.layer]
    return I.initial_state(identity=identity, start_time_s=labels['start_time_s'], frame_id=labels['frame_id'],
                           reference=reference, settings=settings, theta0_k=theta0, kappa0=kappa0,
                           materials=materials, layer_cohorts=ids, reservoirs=None, reservoir_basis=None)


def store(path):
    """The project's native store: the balanced profile, lossless, bounded; the file sits in its own directory."""
    from atlas_tectonics.storage import ArrayStore, StoreLimits, storage_profile
    profile = storage_profile('balanced')
    return ArrayStore(path, StoreLimits(chunk_bytes=profile.chunk_bytes, max_array_bytes=64 << 20,
                                        max_store_bytes=512 << 20, decoded_cache_bytes=4 << 20),
                      profile.compression)


# ----------------------------------------------------------------------------- project files

PROJECT_KEYS = frozenset(('schema', 'project_id', 'case', 'case_id', 'ledger_id', 'root_key', 'source_id',
                          'runtime_id', 'status', 'scope'))
SCOPE = 'bounded supported I02 column case; not a generated world'
MAX_ATTEMPTS = 100000
MAX_LEDGER = 512 << 20
MAX_REQUEST = 4096
# Windows' classic 260-character limit applies to every whole path this workflow writes. Inside a project the longest
# are the temporary files of atomic JSON replacement (a cancellation request at the largest attempt number) and the
# store's rollback journal; a save is staged beside its destination.
LONGEST_IN_PROJECT = max(len('/ledger/ledger.sqlite-journal'), len('/.cancel-%04d.json-' % MAX_ATTEMPTS)+32,
                         len('/.project.json-')+32, len('/.status.json-')+32)
LONGEST_IN_SAVE = len('/.i02-')+12+max(len('/ledger.sqlite-journal'), len('/.project.json-')+32)
LONGEST_IN_SAVED = len('/ledger.sqlite-journal')   # a saved project, once published under its own name


def _fits(base, longest, what):
    if os.name == 'nt' and len(str(base))+longest >= 260:
        raise JobError('INVALID_PATH', 'The %s path is too long for the files this workflow writes there on Windows; '
                                       'choose a shorter one.' % what)


def _directory(root, project_id, *, existing=True):
    root = reader._path(root, directory=True)
    if type(project_id) is not str or not PROJECT_ID.fullmatch(project_id):
        raise JobError('INVALID_REQUEST', 'A lowercase 32-character hexadecimal project ID is required.')
    directory = root/project_id
    _fits(directory, LONGEST_IN_PROJECT, 'projects')
    if existing:
        reader._path(directory, directory=True)
    elif directory.exists() or directory.is_symlink():
        raise JobError('REQUEST_CONFLICT', 'That project ID is already in use.')
    return root, directory


def _record(value, *, extra):
    """A project record exactly as this tool writes it: the fixed keys (plus ``extra``), the supported case and the
    root key of its ledger. Anything else is refused rather than copied along."""
    from atlas_tectonics import integration_ledger as L
    if type(value) is not dict or set(value) != PROJECT_KEYS | set(extra):
        raise JobError('INVALID_STATE', 'The project record is not one this workflow writes.')
    for key in ('ledger_id', 'source_id', 'runtime_id', 'root_key', *extra):
        if not re.fullmatch('[0-9a-f]{64}', str(value[key])):
            raise JobError('INVALID_STATE', 'The project record is invalid.')
    spec = reader._read_json(reader._path(ROOT/CASE, maximum=MAX_JSON), MAX_JSON)
    if (value['schema'] != PROJECT_SCHEMA or value['case'] != CASE or type(spec) is not dict
            or value['case_id'] != spec.get('case_id')
            or value['root_key'] != L.root_key(value['ledger_id']) or value['status'] != 'WORKING NON-CANON'
            or value['scope'] != SCOPE):
        raise JobError('INVALID_STATE', 'The project record does not describe this supported case and ledger.')
    return value


def _json_file(path):
    """A project, status or saved record file: JSON of bounded size, or INVALID_STATE."""
    try:
        return reader._read_json(reader._path(path, maximum=MAX_JSON), MAX_JSON)
    except reader.ReadError:
        raise
    except (ValueError, RecursionError) as exc:         # malformed text, bad encoding, deep nesting, huge integers
        raise JobError('INVALID_STATE', 'A project record file is not JSON this workflow writes.') from exc


def _project(directory):
    value = _json_file(directory/'project.json')
    extra = ('loaded_head',) if type(value) is dict and 'loaded_head' in value else ()
    value = _record(value, extra=extra)
    if value['project_id'] != directory.name:
        raise JobError('INVALID_STATE', 'The project record belongs to another project.')
    return value


def _status(directory):
    value = _json_file(directory/'status.json')
    if (type(value) is not dict or value.get('schema') != STATUS_SCHEMA or value.get('project_id') != directory.name
            or type(value.get('attempt')) is not int or not 0 <= value['attempt'] <= MAX_ATTEMPTS
            or not all(re.fullmatch('[0-9a-f]{64}', str(value.get(key))) for key in ('head', 'head_state'))
            or value.get('run') is not None and (type(value['run']) is not dict
                                                 or value['run'].get('state') not in RUN_STATES)):
        raise JobError('INVALID_STATE', 'The saved project status is invalid.')
    return value


def _recorded(state, chain):
    """The status file's recorded head is on the ledger's chain with the state it recorded: the key alone names only a
    position, which every ledger of the same case shares."""
    return any(commit.key == state['head'] and commit.state_id == state['head_state'] for commit in chain)


def _mark(state, commit):
    state.update(head=commit.key, head_state=commit.state_id)


def _ledger_path(directory):
    return directory/'ledger'/'ledger.sqlite'


@contextmanager
def _lock_patiently(path, seconds=2.):
    """The project's one-byte worker lock, retried for up to ``seconds``: a status or cancel probe holds it for
    microseconds and a save for its backup. An advance holds it for its whole run, so another advance or save that
    cannot take it within ``seconds`` refuses with RUN_BUSY, while one arriving shortly before the run ends waits and
    then runs after it."""
    deadline = time.perf_counter()+seconds
    while True:
        held = jobs._lock(path)
        try:
            held.__enter__()
            break
        except JobError as exc:
            if exc.code != 'RUN_BUSY' or time.perf_counter() >= deadline:
                raise
            time.sleep(.02)
    try:
        yield
    finally:
        held.__exit__(None, None, None)


def _held(lock):
    """Whether a process holds the one-byte lock, probed through a read-only handle: a probe never writes."""
    reader._path(lock, maximum=1)
    with lock.open('rb') as stream:
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        if os.name == 'nt':
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    return False


def _busy(directory):
    """Whether an advance holds the worker lock: held on two probes 50 ms apart, so another poller's own momentary
    probe is not mistaken for a running worker. A project without a lock file has never run."""
    lock = directory/'worker.lock'
    if not lock.exists():
        return False
    for probe in range(2):
        if not _held(lock):
            return False
        if not probe:
            time.sleep(.05)
    return True


def _free(path):
    """Nothing, or only a regular file (a removable leftover request), is at ``path``."""
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return True


def _write_patiently(path, value, tries=10):
    """The job seam's atomic JSON replacement, retried while a reader holds the file on Windows (up to about ten
    seconds): a run's start and outcome are worth waiting for; its progress is not (_replace_now)."""
    for attempt in range(tries):
        try:
            return jobs._atomic(path, value)
        except PermissionError:
            if attempt == tries-1:
                raise


def _replace_now(path, value):
    """Replace a small JSON file atomically without waiting: False when it cannot be done now (for example a reader
    holds it on Windows), so best-effort progress never stalls the physics."""
    try:
        reader._path(path.parent, directory=True)
        reader._path(path, maximum=MAX_JSON)
    except (OSError, reader.ReadError):
        return False
    temporary = path.with_name('.'+path.name+'-'+uuid.uuid4().hex)
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, allow_nan=False, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return True
    except OSError:
        return False
    finally:
        temporary.unlink(missing_ok=True)


def _publish(root, project_id, build):
    """Build a project in a private staging directory, then publish it under its ID with one rename.

    Only the final check and rename hold the root's active lock, briefly, so creating different projects at once never
    refuses either. A poll during creation finds no project rather than half of one, and a failed or interrupted build
    leaves no project ID wedged: only this call's own hidden staging directory is removed.
    """
    staging = root/('.i02-'+uuid.uuid4().hex[:12])
    staging.mkdir()
    try:
        build(staging)
        with _lock_patiently(root/'active.lock'):
            _directory(root, project_id, existing=False)
            os.rename(staging, root/project_id)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _live(directory, project, current):
    """The project's own ledger store, for work that commits or backs it up; a missing store is never created."""
    from atlas_tectonics import integration_ledger as L
    reader._path(_ledger_path(directory), maximum=MAX_LEDGER)
    s = store(_ledger_path(directory))
    try:
        return s, L.Ledger.open(s, project['ledger_id'], source_id=current[0], runtime_id=current[1])
    except BaseException:
        s.close()
        raise


def _backup(source, destination, *, recover):
    """Copy one ledger database consistently through a read-only connection; the source is never written.

    A hot journal left by an interrupted commit needs recovery, which a read-only connection cannot perform: it refuses
    with SQLITE_READONLY_ROLLBACK. Only then, and only with ``recover``, is the native store opened once to roll it back
    (restoring the previous complete head) before the copy is taken; any other error propagates.
    """
    for attempt in range(2):
        try:
            with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True, timeout=5)) as original, \
                    closing(sqlite3.connect(destination)) as copy_:
                original.execute('PRAGMA query_only=ON')
                original.execute('PRAGMA trusted_schema=OFF')
                original.backup(copy_)
            return
        except sqlite3.Error as exc:
            destination.unlink(missing_ok=True)
            if attempt or not recover or getattr(exc, 'sqlite_errorcode', None) != sqlite3.SQLITE_READONLY_ROLLBACK:
                raise
            store(source).close()


@contextmanager
def _reading(source, project, *, current=None, recover=True):
    """A ledger opened on a consistent read-only snapshot of ``source``: inspection never writes the project."""
    from atlas_tectonics import integration_ledger as L
    source = reader._path(source, maximum=MAX_LEDGER)
    if source.stat().st_nlink != 1:                 # the same refusal as the native store's
        raise JobError('INVALID_PATH', 'A hard-linked ledger store is not supported.')
    folder = Path(tempfile.mkdtemp(prefix='atlas-i02-read-'))
    s = None
    try:
        snapshot = folder/'ledger.sqlite'
        _backup(source, snapshot, recover=recover)
        s = store(snapshot)
        source_id, runtime_id = (project['source_id'], project['runtime_id']) if current is None else current
        yield s, L.Ledger.open(s, project['ledger_id'], source_id=source_id, runtime_id=runtime_id)
    finally:
        if s is not None:
            s.close()
        shutil.rmtree(folder, ignore_errors=True)


def _find(ledger, key):
    """A commit of the accepted chain by key (``head``/None, ``root`` or a commit key); reads metadata only."""
    if key in (None, 'head'):
        return ledger.head()
    if key == 'root':
        return ledger.root
    for commit in ledger.chain():
        if commit.key == key:
            return commit
    raise JobError('NO_RESULT', 'That commit is not on the accepted chain of this project.')


# ----------------------------------------------------------------------------- lifecycle

def create(root, project_id):
    """Create the supported case's project: its declared initial state as the root commit of a new ledger."""
    from atlas_tectonics import integration_ledger as L
    root, directory = _directory(root, project_id, existing=False)
    source_id, runtime_id = identities()
    spec, inputs = case()
    with threadpool_limits(limits=1, user_api='blas'):   # one reproducible preparation
        state = build_root(spec, inputs, source_id, runtime_id)

    def build(staging):
        (staging/'ledger').mkdir()
        s = store(_ledger_path(staging))
        try:
            ledger, commit = L.Ledger.create(s, state)
        finally:
            s.close()
        jobs._atomic(staging/'project.json', dict(
            schema=PROJECT_SCHEMA, project_id=project_id, case=CASE, case_id=spec['case_id'],
            ledger_id=ledger.ledger_id, root_key=commit.key, source_id=source_id, runtime_id=runtime_id,
            status='WORKING NON-CANON', scope=SCOPE))
        jobs._atomic(staging/'status.json', dict(schema=STATUS_SCHEMA, project_id=project_id, attempt=0,
                                                 run=None, head=commit.key, head_state=commit.state_id))
    _publish(root, project_id, build)
    return status(root, project_id)


def _run_state(outcome):
    from atlas_tectonics import integration_clock as K
    if outcome in (K.COMPLETED, K.HISTORY_COMPLETE):
        return 'completed'
    if outcome == 'REFUSED_DEADLINE':
        return 'partial'
    if outcome == K.CANCELLED:
        return 'cancelled'
    if outcome == K.REFUSED_STALE_PARENT:       # another writer bypassed the worker lock: not a retained check
        return 'failed'
    return 'refused'


def _cancel_path(directory, attempt):
    return directory/('cancel-%04d.json' % attempt)


def advance(root, project_id, *, steps=None, until_s=None, savepoint_steps=None, max_seconds=None):
    """Advance the accepted history by whole steps under the project's worker lock; every accepted step is kept.

    The request is validated completely before an attempt is claimed, so an invalid request changes nothing. A
    cancellation request left over from an earlier moment never applies to a new attempt, and an unreadable or foreign
    request file is ignored rather than stopping the physics. The answer is built before the lock is released, so it
    describes this attempt even when another advance starts at once; a run that failed answers with status "error".
    """
    from atlas_tectonics import integration_clock as K
    root, directory = _directory(root, project_id)
    project = _project(directory)
    current = identities()
    if current != (project['source_id'], project['runtime_id']):
        raise JobError('SOURCE_MISMATCH', 'The project was produced under another source or runtime identity; it is '
                                          'not silently rebound or continued.')
    if max_seconds is not None and (type(max_seconds) not in (int, float) or not 0 < max_seconds <= 3600):
        raise JobError('INVALID_REQUEST', 'The time budget is a positive number of seconds up to 3600.')
    with _lock_patiently(directory/'worker.lock'):
        state = _status(directory)
        if state['attempt'] >= MAX_ATTEMPTS:
            raise JobError('ATTEMPT_LIMIT', 'This project has reached its advance-attempt limit.')
        attempt = state['attempt']+1
        cancel = _cancel_path(directory, attempt)
        s, ledger = _live(directory, project, current)
        lease = threadpool_limits(limits=1, user_api='blas')   # reproducible single-thread preparation and physics
        started, running = time.perf_counter(), False
        try:
            clock = K.Clock(ledger)
            if not _recorded(state, ledger.chain()):
                raise JobError('INVALID_STATE', 'The project ledger does not hold the head its status records: it was '
                                                'replaced or restored from an older copy, and is not continued.')
            budget = clock.state.settings.maximum_seconds if max_seconds is None else float(max_seconds)
            try:
                clock.check(steps=steps, until_s=until_s, savepoint_steps=savepoint_steps)
            except K.ClockError as exc:          # an invalid request: nothing ran and nothing was recorded
                raise JobError('INVALID_REQUEST', str(exc)) from exc
            try:
                leftover = stat.S_ISREG(cancel.lstat().st_mode)
            except FileNotFoundError:
                leftover = None
            if leftover is not None:
                # No request can target an attempt that has not started, so this one is left over: remove it.
                if not leftover:
                    raise JobError('INVALID_STATE', 'A leftover cancellation request is not a regular file; it is not '
                                                    'removed.')
                cancel.unlink()
            state.update(attempt=attempt, run=dict(state='running', attempt=attempt, accepted_steps=0,
                                                   start_step=clock.head.accepted_steps, head=clock.head.key))
            _write_patiently(directory/'status.json', state)
            running = True

            def requested():
                if not cancel.exists() and not cancel.is_symlink():
                    return False
                try:
                    value = reader._read_json(reader._path(cancel, maximum=MAX_REQUEST), MAX_REQUEST)
                except Exception:                    # unreadable, oversized or malformed: not a request, never fatal
                    return False
                return value == dict(project_id=project_id, attempt=attempt)

            def progressed(commit):
                # Progress is operational and best-effort: the committed ledger head is authoritative, so a status
                # file a reader keeps open is skipped at once rather than waited for.
                state['run'].update(accepted_steps=commit.accepted_steps-state['run']['start_step'], head=commit.key)
                _mark(state, commit)
                _replace_now(directory/'status.json', state)

            outcome = clock.advance(steps=steps, until_s=until_s, savepoint_steps=savepoint_steps,
                                    cancel=_Watch(requested, clock, progressed), deadline=started+budget)
            state['run'] = dict(state=_run_state(outcome.status), attempt=attempt, outcome=outcome.status,
                                reason=outcome.reason, requested_steps=outcome.requested_steps,
                                start_step=state['run']['start_step'], accepted_steps=outcome.accepted_steps,
                                head=outcome.head.key, step=outcome.step, time_s=outcome.time_s,
                                commits=[c.key for c in outcome.commits],
                                event=None if outcome.event is None else outcome.event.label,
                                seconds=time.perf_counter()-started)
            if outcome.status == K.REFUSED_STALE_PARENT:
                state['run']['error'] = dict(code='INVALID_STATE', message='Another writer advanced the project ledger '
                                             'outside its worker lock; the steps this run computed after its last '
                                             'commit were not kept.')
            _mark(state, outcome.head)
        except BaseException as exc:
            if not running:
                raise
            interrupted = isinstance(exc, (KeyboardInterrupt, SystemExit))
            run = state['run']
            state['run'] = dict(state='interrupted' if interrupted else 'failed', attempt=attempt,
                                start_step=run['start_step'], accepted_steps=run['accepted_steps'], head=run['head'],
                                error=_safe_error(exc), seconds=time.perf_counter()-started)
            try:                                     # the committed head is authoritative when it can be read
                head = ledger.head()
                state['run'].update(accepted_steps=head.accepted_steps-run['start_step'], head=head.key,
                                    step=head.accepted_steps, time_s=head.time_s)
                _mark(state, head)
            except Exception:
                pass
            if interrupted:
                try:
                    jobs._atomic(directory/'status.json', state)
                except OSError:
                    pass
                raise
        finally:
            lease.restore_original_limits()
            s.close()
        try:
            _write_patiently(directory/'status.json', state)
        except OSError as exc:
            raise JobError('STATUS_UNWRITTEN', 'The run ended and every accepted step is committed, but its status '
                                               'file could not be updated; status reports the committed head.') from exc
        answer = _answer(project_id, directory, own=state)
    if state['run']['state'] == 'failed':
        return dict(answer, status='error', error=state['run']['error'])
    return answer


class _Watch:
    """The cancel poll handed to the clock: it also records each new commit as progress in the status file."""

    def __init__(self, requested, clock, progressed):
        self._requested, self._clock, self._progressed, self._seen = requested, clock, progressed, clock.head.key

    def __call__(self):
        head = self._clock.head
        if head.key != self._seen:
            self._seen = head.key
            self._progressed(head)
        return self._requested()


def cancel(root, project_id):
    """Request cooperative cancellation of the running advance; it stops between whole steps and keeps them.

    The answer says whether a request was written, and for which attempt; the status that follows may already show
    the run stopped.
    """
    root, directory = _directory(root, project_id)
    state = _status(directory)
    requested = state['run'] is not None and state['run']['state'] == 'running' and _busy(directory)
    if requested:
        path = _cancel_path(directory, state['attempt'])
        if not _free(path):
            raise JobError('INVALID_STATE', 'Something other than a request file occupies the cancellation path; '
                                            'remove it to cancel.')
        if path.exists() and path.stat().st_size > MAX_REQUEST:
            path.unlink()                           # not a request the worker would read: replace it
        jobs._atomic(path, dict(project_id=project_id, attempt=state['attempt']))
    return dict(status(root, project_id), cancel=dict(requested=requested,
                                                      attempt=state['attempt'] if requested else None))


def status(root, project_id):
    """The project, its last recorded run and its accepted head, read from a consistent snapshot; nothing is run.

    The head, read from the ledger itself, is authoritative: a running or interrupted run reports its progress from it.
    The status file's recorded head must be on the ledger's chain; otherwise the ledger was replaced, and the project
    is not offered for continuation.
    """
    root, directory = _directory(root, project_id)
    return _answer(project_id, directory)


def _answer(project_id, directory, own=None):
    """The status answer. ``own`` is the status an advance has just recorded while it still holds the worker lock:
    that answer describes its own finished attempt, never one that starts once the lock is released, and its
    capabilities are those at the release (an advance waiting for the lock may take it at once). If this answer cannot
    be built, the command reports that error; the recorded outcome stays in the status file."""
    current = identities()
    project = _project(directory)
    if own is not None:
        state, busy = own, False
    else:
        state, busy = _status(directory), _busy(directory)
        if state['run'] is not None and state['run']['state'] == 'running' and not busy:
            state, busy = _status(directory), _busy(directory)     # it may have just recorded its outcome, or started
    continuable = current == (project['source_id'], project['runtime_id'])
    with _reading(_ledger_path(directory), project) as (_, ledger):
        chain = ledger.chain()
        head = ledger.describe(chain[-1])
        recorded = _recorded(state, chain)
    run = state['run']
    if run is not None and run['state'] == 'running':
        # Progress comes from the committed head; a worker that exited without recording an outcome is interrupted.
        start = run.get('start_step')
        run = dict(run, head=head['key'], step=head['accepted_steps'])
        if type(start) is int and 0 <= start <= head['accepted_steps']:
            run['accepted_steps'] = head['accepted_steps']-start
        if not busy:
            run['state'] = 'interrupted'
    ready = (not busy and continuable and recorded and head['remaining_steps'] > 0 and state['attempt'] < MAX_ATTEMPTS
             and _free(_cancel_path(directory, state['attempt']+1)))
    return dict(schema=SCHEMA, status='ok', project=dict(
        id=project_id, case=project['case'], case_id=project['case_id'], ledger_id=project['ledger_id'],
        source_id=project['source_id'], runtime_id=project['runtime_id'], run=run, attempt=state['attempt'],
        worker_active=busy, head=head, history=head['history'], recorded_head_on_ledger=recorded,
        capabilities=dict(advance=ready, cancel=busy and run is not None and run['state'] == 'running', inspect=True,
                          save=not busy),
        identity_matches_current=continuable,
        continuation='Whole steps of the fixed global schedule; the same source and runtime identity is required.',
        source_status='WORKING NON-CANON'))


def inspect(root, project_id, *, commit=None, field=None):
    """One commit's accepted time, accounts and identities, or one of its physical fields with units and support."""
    root, directory = _directory(root, project_id)
    project = _project(directory)
    with _reading(_ledger_path(directory), project) as (_, ledger):
        chosen = _find(ledger, commit)
        if field is None:
            return dict(schema=SCHEMA, status='ok', commit=ledger.describe(chosen))
        value = ledger.field(chosen, field)
        return dict(schema=SCHEMA, status='ok', field=dict(value, values=value['values'].tolist()))


def save(root, project_id, destination):
    """A consistent online backup of the project's ledger and its project record, published as a new directory."""
    root, directory = _directory(root, project_id)
    project = _project(directory)
    target = Path(destination).absolute()
    parent = reader._path(target.parent, directory=True)
    _fits(parent, LONGEST_IN_SAVE, 'save destination')
    _fits(target, LONGEST_IN_SAVED, 'save destination')
    if target.exists() or target.is_symlink():
        raise JobError('REQUEST_CONFLICT', 'The save destination already exists; nothing is overwritten.')
    with _lock_patiently(directory/'worker.lock'):
        s, ledger = _live(directory, project, (project['source_id'], project['runtime_id']))
        staging = parent/('.i02-'+uuid.uuid4().hex[:12])    # published with one rename, never half-written
        try:
            head = ledger.head()
            staging.mkdir()
            s.backup_to(staging/'ledger.sqlite')
            saved = {key: value for key, value in project.items() if key != 'loaded_head'}
            jobs._atomic(staging/'project.json', dict(saved, saved_head=head.key))
            os.rename(staging, target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            s.close()
    return dict(schema=SCHEMA, status='ok', saved=dict(path=str(target), head=head.key, sequence=head.sequence,
                                                         accepted_steps=head.accepted_steps))


def load(root, project_id, source):
    """Verify a saved project completely and restore it as a new project; continuing it needs the same identity.

    The saved directory is only read. Its record must be exactly what save() writes, its identities must be the ones
    now in force, and every commit of its ledger must restore and reproduce its identity before anything is created.
    A saved project is trusted input: these checks establish that it is consistent, not who wrote it.
    """
    _fits(Path(source).absolute(), LONGEST_IN_SAVED, 'saved project')
    saved = reader._path(source, directory=True)
    record = _record(_json_file(saved/'project.json'), extra=('saved_head',))
    current = identities()
    if current != (record['source_id'], record['runtime_id']):
        raise JobError('SOURCE_MISMATCH', 'The saved project was produced under another source or runtime '
                                          'identity; it is not silently rebound or continued.')
    root, directory = _directory(root, project_id, existing=False)
    with _reading(saved/'ledger.sqlite', record, current=current, recover=False) as (s, ledger):
        head = ledger.head()
        if head.key != record['saved_head']:
            raise JobError('INVALID_STATE', 'The saved ledger head differs from its project record.')
        if s.statistics()['snapshots'] != len(ledger.chain()):
            raise JobError('INVALID_STATE', 'The saved store holds records that are not commits of this ledger.')
        ledger.verify_chain()                       # every state and stock restores and reproduces its identity

        def build(staging):
            (staging/'ledger').mkdir()
            s.backup_to(_ledger_path(staging))
            fresh = {key: value for key, value in record.items() if key != 'saved_head'}
            jobs._atomic(staging/'project.json', dict(fresh, project_id=project_id, loaded_head=head.key))
            jobs._atomic(staging/'status.json', dict(schema=STATUS_SCHEMA, project_id=project_id, attempt=0,
                                                     run=None, head=head.key, head_state=head.state_id))
        _publish(root, project_id, build)
    return status(root, project_id)


def _safe_error(exc):
    from atlas_tectonics._validation import TectonicsError
    from atlas_tectonics.storage import StoreError
    if isinstance(exc, JobError):
        return dict(code=exc.code, message=str(exc))
    if isinstance(exc, TectonicsError):
        return dict(code='REFUSED', message=str(exc)[:500])
    if isinstance(exc, StoreError):
        return dict(code='STORE_REFUSED', message='The ledger store refused the operation: '+str(exc)[:300])
    if isinstance(exc, reader.ReadError):
        return dict(code=exc.code, message='A project path or saved file failed validation.')
    if isinstance(exc, FileNotFoundError):
        return dict(code='MISSING_INPUT', message='A required project file or directory is missing.')
    if isinstance(exc, (OSError, sqlite3.Error)):
        return dict(code='IO_ERROR', message='A project file could not be read or written; nothing was invented.')
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return dict(code='INTERRUPTED', message='The run was interrupted; every step committed before it is kept.')
    if isinstance(exc, ImportError):
        return dict(code='DEPENDENCY_UNAVAILABLE', message='A required dependency is unavailable.')
    return dict(code='WORKER_FAILED', message='The operation failed; every committed step is kept and no result was '
                                              'invented.')


class _Parser(argparse.ArgumentParser):
    """Argument errors answer with the same JSON line as every other error."""

    def error(self, message):
        print(json.dumps(dict(schema=SCHEMA, status='error', error=dict(code='INVALID_REQUEST',
                                                                          message=message[:300])),
                         separators=(',', ':')))
        raise SystemExit(2)


def main():
    parser = _Parser(description=__doc__)
    parser.add_argument('action', choices=('create', 'advance', 'status', 'inspect', 'cancel', 'save', 'load'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--steps', type=int)
    parser.add_argument('--until-s', type=float)
    parser.add_argument('--savepoint-steps', type=int)
    parser.add_argument('--max-seconds', type=float)
    parser.add_argument('--commit')
    parser.add_argument('--field')
    parser.add_argument('--to', type=Path)
    parser.add_argument('--from', dest='source', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'create':
            answer = create(args.root, args.project)
        elif args.action == 'advance':
            answer = advance(args.root, args.project, steps=args.steps, until_s=args.until_s,
                             savepoint_steps=args.savepoint_steps, max_seconds=args.max_seconds)
        elif args.action == 'inspect':
            answer = inspect(args.root, args.project, commit=args.commit, field=args.field)
        elif args.action == 'save':
            if args.to is None:
                raise JobError('INVALID_REQUEST', 'save needs --to, a new directory.')
            answer = save(args.root, args.project, args.to)
        elif args.action == 'load':
            if args.source is None:
                raise JobError('INVALID_REQUEST', 'load needs --from, a saved project directory.')
            answer = load(args.root, args.project, args.source)
        else:
            answer = globals()[args.action](args.root, args.project)
    except Exception as exc:
        answer = dict(schema=SCHEMA, status='error', error=_safe_error(exc))
    except BaseException as exc:                 # interrupted: the caller still receives its one JSON line
        answer = dict(schema=SCHEMA, status='error', error=_safe_error(exc))
    print(json.dumps(answer, allow_nan=False, separators=(',', ':')))
    return 0 if answer['status'] == 'ok' else 2


if __name__ == '__main__':
    raise SystemExit(main())
