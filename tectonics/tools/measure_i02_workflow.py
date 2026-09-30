"""I02.7 bounded timing of the joined workflow on one declared workload; raw seconds, not a speed claim.

SPDX-License-Identifier: AGPL-3.0-only
WORKING NON-CANON. The workload is the supported I02 case (cases/i02_column_workflow_v1.json): the layered order-8
finite-strain column over its 16 whole steps, single-threaded BLAS. Every mode computes the same accepted history,
and the harness checks that before reporting any time:

- bare physics: the retained evolve, cold (preparation and eigensystem included) and warm (operators reused);
- the in-memory common-state continuation of the same steps (carrier and identity overhead, no storage);
- the full workflow: ledger creation, the accepted clock and its commits in a fresh store, with the time spent in
  commits, the database growth per commit and the reuse of unchanged content-addressed chunks;
- reopening in a fresh process from the half-way commit (root restore, head restore, operator rebuild), then the
  remaining steps, against the same remaining steps of the uninterrupted run.

Cold means the first measured repetition of a mode in its process; warm the median of the later ones. Timings are
operational records of the one machine and interpreter that ran the harness, whose platform the record names; they
never enter a physical identity. If any mode did not compute the same accepted history, the record says
FAILED_EQUALITY and withholds every timing. No parallelism is introduced: the steps are a sequential feedback chain.
An existing output file, a missing output folder or an invalid request is refused before anything runs or is
created; the record is created exclusively once the measurement has finished, and never overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

import numpy as np
import scipy
from threadpoolctl import threadpool_limits

import i02_column_workflow as workflow

SCHEMA = 'atlas.i02-workflow-timing.v1'
TOOL = Path(__file__).resolve()
CHILD = r"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
start = time.perf_counter()
from threadpoolctl import threadpool_limits
import i02_column_workflow as workflow
from atlas_tectonics import integration_clock as K, integration_ledger as L
from measure_i02_workflow import _state_payload
imported = time.perf_counter()
path, ledger_id, source_id, runtime_id, repeats = Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5], int(sys.argv[6])
samples = []
with threadpool_limits(limits=1, user_api='blas'):
    for _ in range(repeats):
        t0 = time.perf_counter()
        store = workflow.store(path)
        ledger = L.Ledger.open(store, ledger_id, source_id=source_id, runtime_id=runtime_id)
        t1 = time.perf_counter()
        head = ledger.head()
        state = ledger.state(head)
        t2 = time.perf_counter()
        clock = K.Clock(ledger)
        t3 = time.perf_counter()
        samples.append(dict(open_root_s=t1-t0, head_restore_s=t2-t1, operator_rebuild_s=t3-t2, step=head.accepted_steps))
        store.close()
    # Remaining work once, from a copy so the measured checkpoint stays at its step.
    store = workflow.store(path)
    ledger = L.Ledger.open(store, ledger_id, source_id=source_id, runtime_id=runtime_id)
    clock = K.Clock(ledger)
    t4 = time.perf_counter()
    outcome = clock.advance(steps=ledger.state(ledger.head()).settings.steps-clock.head.accepted_steps)
    t5 = time.perf_counter()
    final = ledger.state(ledger.head())
    store.close()
print(json.dumps(dict(import_s=imported-start, samples=samples, remaining_s=t5-t4, status=outcome.status,
                      state=_state_payload(final)), default=lambda value: value.tolist(), allow_nan=False))
"""


def _state_payload(state):
    """Physical restart comparison, excluding lineage and solver-work diagnostics that differ after a cold solve.

    Every carried physical scalar and account is included. Initial fields, booked stages and per-point yield counts
    remain exact; current fields and floating-point scalars use the retained restart parity in _matches.
    """
    column = state.column
    scalars = ('stretch', 'elapsed_s', 'accepted_steps', 'clock_s', 'displacement_m', 'log_path',
               'log_strain_quadrature', 'velocity_start_m_s', 'column_force_start_n_m')
    return dict(identity={name: getattr(state, name) for name in
                          ('world_id', 'scenario_id', 'epoch_id', 'source_id', 'runtime_id', 'unit_system',
                           'frame_id', 'root_state_id', 'start_time_s')}, time_s=state.time_s,
                scalars={name: getattr(column, name) for name in scalars}, accounts=column.accounts_j_m,
                theta=column.theta_k, kappa=column.kappa,
                initial_theta=column.initial_theta_k, initial_kappa=column.initial_kappa,
                yield_stage_counts=column.yield_stage_counts, stages=column.counters['stages'],
                restress_mismatches=column.counters['restress_mismatches'])


def _matches(value, reference, relative=0.):
    """Finite, shape-preserving equality; only floating-point leaves admit the declared relative parity.

    Missing/extra fields, nonnumeric arrays and broadcasting are refused. Integers (including counts) stay exact.
    A zero tolerance compares array bytes and scalar floats exactly, including their signs at zero.
    """
    if isinstance(reference, dict):
        return (isinstance(value, dict) and value.keys() == reference.keys()
                and all(_matches(value[key], item, relative) for key, item in reference.items()))
    if isinstance(reference, np.ndarray):
        try:
            actual = np.asarray(value)
            if (actual.shape != reference.shape or actual.dtype.kind not in 'biuf'
                    or not np.all(np.isfinite(actual)) or not np.all(np.isfinite(reference))):
                return False
            if reference.dtype.kind in 'biu':
                return actual.dtype.kind == reference.dtype.kind and bool(np.array_equal(actual, reference))
            if actual.dtype.kind != 'f':
                return False
            if relative == 0.:
                return actual.dtype == reference.dtype and actual.tobytes() == reference.tobytes()
            scale = max(float(np.abs(reference).max()), 1e-300)
            with np.errstate(over='ignore', invalid='ignore'):
                return bool(float(np.abs(actual-reference).max()) <= relative*scale)
        except (TypeError, ValueError, OverflowError):
            return False
    if isinstance(reference, (tuple, list)):
        return (isinstance(value, (tuple, list)) and len(value) == len(reference)
                and all(_matches(a, b, relative) for a, b in zip(value, reference)))
    if isinstance(reference, (bool, np.bool_)):
        return isinstance(value, (bool, np.bool_)) and bool(value) == bool(reference)
    if isinstance(reference, (int, np.integer)):
        return (isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_))
                and value == reference)
    if isinstance(reference, (float, np.floating)):
        if not isinstance(value, (float, np.floating)) or not np.isfinite(value) or not np.isfinite(reference):
            return False
        if relative == 0.:
            return float(value).hex() == float(reference).hex()
        return abs(value-reference) <= relative*max(abs(reference), 1e-300)
    return type(value) is type(reference) and value == reference


def _reopened_matches(child, reference, relative):
    if not isinstance(child, dict) or child.get('status') != 'HISTORY_COMPLETE':
        return False
    state = child.get('state')
    if not _matches(state, reference, relative):
        return False
    return all(_matches(state[name], reference[name]) for name in ('identity', 'initial_theta', 'initial_kappa'))


def _median(samples):
    return statistics.median(samples) if samples else None


def _mode(samples):
    """Raw samples; cold is the first repetition in this process, warm the median of the later ones."""
    return dict(samples_s=samples, cold_s=samples[0], warm_median_s=_median(samples[1:]), median_s=_median(samples),
                min_s=min(samples))


def _percent(value, reference):
    return None if value is None or not reference else 100.*(value-reference)/reference


def _bindings():
    """Bind the measured tool, declared inputs/adapters and source-bound package outside the timed regions."""
    names = set(workflow.SOURCES) | {'tools/measure_i02_workflow.py'}
    names.update(path.relative_to(workflow.ROOT).as_posix()
                 for path in (workflow.ROOT/'src'/'atlas_tectonics').rglob('*.py'))
    return {name: hashlib.sha256((workflow.ROOT/name).read_bytes()).hexdigest() for name in sorted(names)}


def measure(repetitions=5, savepoint_steps=4):
    from atlas_tectonics import (_integration_heat as H, _integration_motion as M, _integration_weakening as W,
                                 integration_clock as K, integration_evolution as E, integration_ledger as L,
                                 integration_state as I)
    if type(repetitions) is not int or not 2 <= repetitions <= 50:
        raise ValueError('repetitions must be an integer in 2..50 (one cold and at least one warm sample)')
    if type(savepoint_steps) is not int or savepoint_steps < 1:
        raise ValueError('savepoint_steps must be a positive integer')
    before = _bindings()
    source_id, runtime_id = workflow.identities()
    spec, inputs = workflow.case()
    results, checks, detail = {}, {}, []
    with threadpool_limits(limits=1, user_api='blas'), tempfile.TemporaryDirectory() as scratch:
        root = workflow.build_root(spec, inputs, source_id, runtime_id)
        settings, steps = root.settings, root.settings.steps
        half = steps//2
        reference = I.Continuation(root)
        whole = reference.advance(root, steps).state
        whole_report = dict(reference.report(whole), status='COMPLETE')
        whole_payload = _state_payload(whole)
        weak = inputs['weakening_case']
        law = W.WeakeningLaw.from_spec(weak['weakening'])
        drive = M.Drive(*settings.drive_parameters)
        key = root.reference.preparation_key()
        thermal_inputs = root.reference.thermal_inputs()
        kappa0, theta0 = root.column.initial_kappa, root.column.initial_theta_k
        common = dict(duration_s=settings.duration_s, steps=steps, window=settings.window_mapping(),
                      temperature_step_k=settings.temperature_step_k, fractions=settings.heat_fractions,
                      policy=settings.policy(), theta0=theta0, inputs=key)

        def prepared():
            base = W.prepare(key[0], key[1], closure=key[2], gravity=key[3])
            thermal = H.prepare_thermal(base.layer, base.depth_m, base.weight, thermal_inputs['thicknesses'],
                                        thermal_inputs['props'], thermal_inputs['densities'],
                                        thermal_inputs['boundaries'], mechanical_fingerprint=base.fingerprint)
            return base, thermal

        # Bare physics: the retained evolve of all steps.
        cold, warm, cold_same, warm_same = [], [], True, True
        base, thermal = prepared()
        modes = E.eigensystem(thermal)
        for _ in range(repetitions):
            t0 = time.perf_counter()
            b, t = prepared()
            out = E.evolve(b, t, law, kappa0, drive, **common)
            cold.append(time.perf_counter()-t0)
            cold_same = _matches(out, whole_report) and cold_same
            t0 = time.perf_counter()
            out = E.evolve(base, thermal, law, kappa0, drive, modes=modes, **common)
            warm.append(time.perf_counter()-t0)
            warm_same = _matches(out, whole_report) and warm_same
        results['bare_cold_prepare_and_evolve'] = _mode(cold)
        results['bare_warm_evolve'] = _mode(warm)
        checks['bare_cold_equals_continuation'] = cold_same
        checks['bare_warm_equals_continuation'] = warm_same
        checks['bare_equals_continuation'] = cold_same and warm_same

        # In-memory common-state continuation: carrier construction (operator rebuild) and the step loop.
        build, loop, same = [], [], True
        for _ in range(repetitions):
            t0 = time.perf_counter()
            run = I.Continuation(root)
            t1 = time.perf_counter()
            state = run.advance(root, steps).state
            loop.append(time.perf_counter()-t1)
            build.append(t1-t0)
            same = same and state.column.column_state_id == whole.column.column_state_id
        checks['continuation_equals_whole'] = same
        results['continuation_rebuild'] = _mode(build)
        results['continuation_steps'] = _mode(loop)

        # Full workflow: a fresh store, ledger, accepted clock and commits per repetition.
        commit_time, totals, growth, creates, same = [], [], [], [], True
        original = L.Ledger.commit
        spent = []

        def timed(self, *args, **kwargs):
            t0 = time.perf_counter()
            try:
                return original(self, *args, **kwargs)
            finally:
                spent.append(time.perf_counter()-t0)
        L.Ledger.commit = timed
        try:
            for index in range(repetitions):
                folder = Path(scratch)/('run-%02d' % index)
                folder.mkdir()
                path = folder/'ledger.sqlite'
                spent.clear()
                t0 = time.perf_counter()
                store = workflow.store(path)
                ledger, first = L.Ledger.create(store, root)
                t1 = time.perf_counter()
                clock = K.Clock(ledger)
                sizes = [path.stat().st_size]
                outcome = clock.advance(steps=half, savepoint_steps=savepoint_steps)
                sizes.append(path.stat().st_size)
                outcome2 = clock.advance(steps=steps-half, savepoint_steps=savepoint_steps)
                t2 = time.perf_counter()
                sizes.append(path.stat().st_size)
                final = ledger.state(ledger.head())
                stats = store.statistics()
                commits = (*outcome.commits, *outcome2.commits)
                root_bytes = sum(a.nbytes for a in store.get(first.key).values())
                successor_bytes = sum(a.nbytes for c in commits for a in store.get(c.key).values())
                store.close()
                same = same and final.column.column_state_id == whole.column.column_state_id
                creates.append(t1-t0)
                totals.append(t2-t0)
                commit_time.append(sum(spent))
                growth.append(dict(
                    database_bytes_after_root=sizes[0], database_bytes_after_half=sizes[1], database_bytes_final=sizes[2],
                    successor_commits=len(commits), snapshots=stats['snapshots'], unique_chunks=stats['unique_chunks'],
                    encoded_payload_bytes=stats['encoded_payload_bytes'], root_array_bytes=root_bytes,
                    successor_array_bytes=successor_bytes,
                    whole_state_per_commit_bytes=root_bytes*(len(commits)+1)))
            # A half-way checkpoint for the reopen measurement: its own store, committed up to ``half``.
            reopen_dir = Path(scratch)/'reopen'
            reopen_dir.mkdir()
            store = workflow.store(reopen_dir/'ledger.sqlite')
            ledger, _ = L.Ledger.create(store, root)
            K.Clock(ledger).advance(steps=half, savepoint_steps=savepoint_steps)
            ledger_id = ledger.ledger_id
            store.close()
        finally:
            L.Ledger.commit = original
        results['workflow_create'] = _mode(creates)
        results['workflow_total'] = _mode(totals)
        results['workflow_commits'] = _mode(commit_time)
        checks['workflow_equals_continuation'] = same

        # Fresh-process reopen at the half-way checkpoint, then the remaining steps.
        env = dict(os.environ)
        done = subprocess.run([sys.executable, '-B', '-c', CHILD, str(TOOL.parent), str(reopen_dir/'ledger.sqlite'),
                               ledger_id, source_id, runtime_id, str(repetitions)], capture_output=True, text=True,
                              env=env, timeout=600)
        child = None
        reopened = False
        if done.returncode:
            detail.append('the reopen child failed: '+done.stderr[-500:])
        else:
            try:
                child = json.loads(done.stdout.strip().splitlines()[-1])
                reopened = _reopened_matches(child, whole_payload, settings.policy()['parity_relative'])
                modes = {name: [sample[name] for sample in child['samples']]
                         for name in ('open_root_s', 'head_restore_s', 'operator_rebuild_s')}
                times = [child['remaining_s'], child['import_s'], *(v for mode in modes.values() for v in mode)]
                if (any(len(mode) != repetitions for mode in modes.values())
                        or any(type(v) not in (int, float) or not np.isfinite(v) or v < 0 for v in times)):
                    raise ValueError('invalid reopen timing samples')
                for name, samples in modes.items():
                    results['reopen_'+name[:-2]] = _mode(samples)
                results['reopen_remaining_steps'] = dict(samples_s=[child['remaining_s']], cold_s=child['remaining_s'])
                results['child_import'] = dict(samples_s=[child['import_s']], cold_s=child['import_s'])
            except (KeyError, TypeError, ValueError, IndexError, OverflowError):
                reopened = False
                detail.append('the reopen child returned an incomplete or invalid comparison record')
        # The same remaining steps of the uninterrupted in-memory run, warm, for comparison.
        remaining = []
        for _ in range(repetitions):
            run = I.Continuation(root)
            mid = run.advance(root, half).state
            t0 = time.perf_counter()
            run.advance(mid, steps-half)
            remaining.append(time.perf_counter()-t0)
        results['uninterrupted_remaining_steps'] = _mode(remaining)
        checks['reopened_within_parity'] = bool(reopened)
    workload = dict(case=workflow.CASE, case_id=spec['case_id'], steps=steps, step_s=settings.step_s,
                    points=root.reference.points, savepoint_steps=savepoint_steps, half=half, repetitions=repetitions)
    checks['sources_unchanged'] = before == _bindings()
    return dict(_record(checks, results, growth, workload, detail), source_sha256=before,
                execution_identity=runtime_id)


def _derived(results, growth):
    warm_bare = results['bare_warm_evolve']['warm_median_s']
    workflow_warm = results['workflow_total']['warm_median_s']
    return dict(
        continuation_steps_vs_bare_warm_percent=_percent(results['continuation_steps']['warm_median_s'], warm_bare),
        workflow_total_vs_bare_warm_percent=_percent(workflow_warm, warm_bare),
        workflow_total_vs_bare_cold_percent=_percent(workflow_warm,
                                                     results['bare_cold_prepare_and_evolve']['warm_median_s']),
        commits_share_of_workflow_percent=None if not workflow_warm else
        100.*results['workflow_commits']['warm_median_s']/workflow_warm,
        reopen_total_cold_s=sum(results['reopen_'+n]['cold_s'] for n in ('open_root', 'head_restore',
                                                                          'operator_rebuild')),
        reopen_plus_remaining_vs_uninterrupted_remaining_percent=_percent(
            sum(results['reopen_'+n]['cold_s'] for n in ('open_root', 'head_restore', 'operator_rebuild'))
            + results['reopen_remaining_steps']['cold_s'], results['uninterrupted_remaining_steps']['warm_median_s']),
        database_bytes_per_successor_commit=(growth[-1]['database_bytes_final']-growth[-1]['database_bytes_after_root'])
        / max(1, growth[-1]['successor_commits']))


def _record(checks, results, growth, workload, detail=()):
    """The record of one run: its timings only when every mode computed the same accepted history."""
    system = platform.system() or 'unidentified'
    record = dict(schema=SCHEMA, status='MEASURED' if checks and all(checks.values()) else 'FAILED_EQUALITY',
                  scope='one %s machine and interpreter; operational timing only, not a physical result or a '
                        'whole-generator speed claim; other platforms not covered' % system,
                  platform=dict(system=system, machine=platform.machine(), python=platform.python_version(),
                                numpy=np.__version__, scipy=scipy.__version__, blas_threads=1),
                  workload=workload, checks=checks)
    if record['status'] == 'MEASURED':
        return dict(record, results=results, growth=growth, derived=_derived(results, growth))
    return dict(record, results=None, growth=None, derived=None, detail=list(detail),
                withheld='every timing is withheld: a mode did not compute the same accepted history')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--repetitions', type=int, default=5)
    parser.add_argument('--savepoint-steps', type=int, default=4)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('the output file already exists; a result is never overwritten')
    if not args.output.parent.is_dir():
        parser.error('the output folder does not exist; create it first')
    if not 2 <= args.repetitions <= 50 or args.savepoint_steps < 1:
        parser.error('--repetitions must be 2..50 and --savepoint-steps positive')
    result = measure(args.repetitions, args.savepoint_steps)          # an invalid request refuses before any work
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:     # created only now, exclusively
        stream.write(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps(dict(status=result['status'], derived=result['derived'])))
    return 0 if result['status'] == 'MEASURED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
