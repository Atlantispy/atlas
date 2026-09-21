#!/usr/bin/env python3
"""Bounded dev41 A/B: existing zero-rate versus previous-stage1, never a campaign.

SPDX-License-Identifier: AGPL-3.0-only
Run only in an isolated, detached checkout of BASE, on an exclusively available
numerical host. This source-only harness deliberately lives outside src/.
No numerical implementation, default, tolerance, checkpoint or source binding
is changed. Performance trials include state capture, plan preparation, two
consecutive advances (including seed capture) and close. JIT warm-ups, fixture
construction and evidence I/O are separately recorded, not charged to stepping.
All run records remain IN_PROGRESS / WORKING NON-CANON.
"""
from __future__ import annotations

import argparse
from concurrent.futures import CancelledError
from contextlib import contextmanager, redirect_stdout
import cProfile
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import pstats
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile

BASE = '49c6603fad2ed9a92f6f2a302037dd425f154c3c'
MODES = ('zero-rate', 'previous-stage1')
THREAD_VARIABLES = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
                    'BLIS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS',
                    'NUMBA_NUM_THREADS')
ROOT = Path(__file__).resolve().parents[1]
STATUS = {'R4_status': 'IN_PROGRESS', 'status': 'WORKING NON-CANON',
          'benchmark_accepted': False, 'full_campaign_claim': False}
FIXED = ['--case', 'tosi-2', '--max-picard', '400', '--linear-rtol', '1e-12',
         '--momentum-tolerance', '1e-9', '--viscosity-rtol', '1e-8',
         '--ilu-fill-factor', '17', '--velocity-preconditioner', 'gmg',
         '--nonlinear-solver', 'anderson', '--adaptive-inner',
         '--preconditioner-max-uses', '4', '--max-steps', '2',
         '--save-every', '1', '--sample-every', '1', '--budget-mib', '1024']


class Refused(RuntimeError):
    """A failed precondition; never converted to a numerical result."""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def write_json(path, value):
    """Exclusive evidence files: no overwrite of a previous observation."""
    with Path(path).open('xb') as stream:
        stream.write(encode(value))
        stream.flush()
        os.fsync(stream.fileno())


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def no_symlink(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)),
            f'Symlink path refused: {path}')
    return path


def git(root, *args, accepted=(0,)):
    p = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                       timeout=30, check=False)
    require(p.returncode in accepted, f'git {args!r}: {p.stderr.decode(errors="replace")}')
    return p


def source_audit(root, expected_base=BASE):
    """Verify bytes AND membership against Git objects, including ignored extras.

    expected_base is injectable only for the isolated unit-test fixture. The CLI
    has no base override. Added tools/tests/evidence do not alter src identity.
    """
    root = no_symlink(root)
    require((root / 'src').is_dir(), 'Complete tectonics/src is not available.')
    repo = root.parent
    head = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    require(head == expected_base, f'Expected exact base {expected_base}; found {head}.')
    require(git(repo, 'symbolic-ref', '-q', 'HEAD', accepted=(0, 1)).returncode == 1,
            'Use an isolated detached checkout, not a production branch.')
    extra = ['tectonics/tools/run_convection_r4_4.py',
             'tectonics/cases/convection_r4_4.json', 'tectonics/pyproject.toml',
             'tectonics/docs/OPTIMISATION_REFERENCE.md']
    listing = git(repo, 'ls-tree', '-r', '-z', head, '--', 'tectonics/src', *extra).stdout
    inventory = {}
    for item in listing.split(b'\0'):
        if not item:
            continue
        fields, raw_name = item.split(b'\t', 1)
        mode, kind, blob = fields.decode().split()
        name = raw_name.decode('utf-8')
        require(kind == 'blob' and mode in ('100644', '100755'),
                'Only regular source files are supported.')
        p = no_symlink(repo / name)
        require(p.is_file(), f'Missing tracked input: {name}')
        data = p.read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        require(actual == blob, f'Worktree source differs from exact base: {name}')
        inventory[name] = {'git_blob': blob, 'sha256': sha(data), 'bytes': len(data)}
    expected = {n for n in inventory if n.startswith('tectonics/src/')}
    actual = set()
    for p in (root / 'src').rglob('*'):
        no_symlink(p)
        if p.is_file():
            actual.add(p.relative_to(repo).as_posix())
    require(expected and actual == expected, 'Source membership differs (including ignored cache files).')
    require(set(extra) <= set(inventory), 'Runner/specification/project/reference missing from base.')
    return {'base': head, 'inventory': inventory, 'inventory_sha256': sha(encode(inventory))}


@contextmanager
def host_lock(path):
    """Cooperative machine-wide lock, never unlinked to avoid an inode race.

    This cannot detect unrelated benchmarks that ignore the same lock. The host
    must also be administratively exclusive, as acknowledged by the caller.
    """
    path = no_symlink(path)
    require(path.parent.is_dir(), 'Host-lock parent directory must exist.')
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b'\0'); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def order(repeat):
    return MODES if repeat % 2 == 0 else MODES[::-1]


def summary(pairs):
    """Never treat missing/failed runs or unmatched repeats as speed evidence."""
    require(bool(pairs), 'No completed pairs.')
    for pair in pairs:
        require(set(pair) == set(MODES), 'Incomplete comparison pair.')
        for m in MODES:
            require(math.isfinite(pair[m]) and pair[m] > 0, 'Invalid elapsed seconds.')
    b = statistics.median(p['zero-rate'] for p in pairs)
    c = statistics.median(p['previous-stage1'] for p in pairs)
    saved = b - c
    return {'pairs': len(pairs), 'baseline_median_s': b, 'candidate_median_s': c,
            'seconds_saved': saved, 'percentage_saved': 100 * saved / b,
            'paired_savings_s': [p['zero-rate'] - p['previous-stage1'] for p in pairs],
            'all_pairs_faster': all(p['previous-stage1'] < p['zero-rate'] for p in pairs),
            'not_a_confidence_interval': True}


def profile_argv(output, cells, mode, dt, seconds, *, resume=False, segment=2):
    require(mode in MODES, 'Unknown start mode.')
    common = ['--output', str(output), '--segment-steps', str(segment),
              '--seconds', str(seconds)]
    if resume:
        return common + ['--resume', '--budget-mib', '1024']
    return common + FIXED + ['--cells', str(cells), '--dt', repr(dt),
                             '--nonlinear-start', mode]


def load_runner(root):
    path = root / 'tools/run_convection_r4_4.py'
    spec = importlib.util.spec_from_file_location('atlas_dev41_combined_benchmark_runner', path)
    require(spec is not None and spec.loader is not None, 'Cannot load existing runner.')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def policies(runner, args):
    """Explicit profile, constructed from the existing runner's parsed switches."""
    at = runner.atlas
    require(args.nonlinear_solver == 'anderson' and args.adaptive_inner,
            'Combined profile requires Anderson and adaptive inner.')
    return dict(policy=at.ThermochemicalPolicy(max_steps=args.max_steps),
                nonlinear_policy=at.NonlinearStokesPolicy(
                    max_picard_iterations=args.max_picard, linear_rtol=args.linear_rtol,
                    momentum_tolerance=args.momentum_tolerance,
                    viscosity_rtol=args.viscosity_rtol, ilu_fill_factor=args.ilu_fill_factor,
                    velocity_preconditioner=args.velocity_preconditioner),
                nonlinear_start=args.nonlinear_start, anderson_policy=at.AndersonPolicy(),
                adaptive_inner_policy=at.AdaptiveInnerPolicy(),
                preconditioner_reuse_policy=at.PreconditionerReusePolicy(
                    max_uses=args.preconditioner_max_uses))


def policy_record(kw):
    return {k: asdict(v) if k != 'nonlinear_start' else v for k, v in kw.items()}


def array_record(array):
    import numpy as np
    a = np.ascontiguousarray(array)
    return {'shape': list(a.shape), 'dtype': a.dtype.str, 'sha256': sha(a.tobytes()),
            'bytes': a.nbytes}


def fixture(runner, cells, args, out):
    import numpy as np
    started = time.perf_counter()
    provenance = {'kind': 'analytic-initial-not-developed',
                  'source': 'Tosi equation 11 exact cell-average initial state'}
    if cells == 128 and args.fixture is not None:
        path = no_symlink(args.fixture)
        require(path.stat().st_size <= 2 << 20, '128-grid fixture exceeds the bounded file envelope.')
        raw = path.read_bytes()
        manifest_path = no_symlink(args.fixture_manifest)
        require(manifest_path.stat().st_size <= 65536, 'Fixture manifest exceeds the metadata envelope.')
        manifest_raw = manifest_path.read_bytes()
        manifest = json.loads(manifest_raw)
        require(manifest.get('schema') == 'atlas.r44.raw-field-fixture.v1', 'Unknown fixture schema.')
        require(manifest.get('kind') == 'new-source-derived-developed-input', 'Explicit fixture kind required.')
        require(manifest.get('case') == 'tosi-2' and manifest.get('cells') == 128,
                'Fixture must be the declared case-2, 128-square input.')
        require(manifest.get('npz_sha256') == sha(raw), 'Fixture file hash mismatch.')
        for key in ('origin', 'transformation', 'original_source_identity'):
            require(isinstance(manifest.get(key), str) and bool(manifest[key].strip()),
                    f'Missing fixture provenance: {key}')
        # Validate NPY headers before allocation; small compressed files can declare
        # enormous arrays. No implicit dtype conversion or checkpoint deserialisation.
        with zipfile.ZipFile(path) as archive:
            require(sorted(archive.namelist()) == ['composition.npy', 'temperature_k.npy'],
                    'Only the two raw NPY fields, without duplicates, are accepted.')
            for item in archive.infolist():
                require(item.file_size <= cells * cells * 8 + 8192,
                        'Fixture member exceeds the expected 128-grid payload envelope.')
                with archive.open(item) as stream:
                    version = np.lib.format.read_magic(stream)
                    require(version in ((1, 0), (2, 0)), 'Unsupported NPY header version.')
                    reader = (np.lib.format.read_array_header_1_0 if version == (1, 0)
                              else np.lib.format.read_array_header_2_0)
                    shape, _fortran, dtype = reader(stream, max_header_size=4096)
                    require(shape == (cells, cells) and dtype == np.dtype('float64'),
                            'Fixture must contain actual 128-square native float64 fields.')
                    require(item.file_size - stream.tell() == cells * cells * 8,
                            'Fixture payload length does not match its validated header.')
        with np.load(path, allow_pickle=False, max_header_size=4096) as data:
            t = np.array(data['temperature_k'], copy=True)
            c = np.array(data['composition'], copy=True)
        provenance = dict(manifest, manifest_sha256=sha(manifest_raw),
                          provenance_status='caller-declared; hash verifies bytes, not scientific history',
                          historical_restart=False, fine_grid_evolved_evidence=False)
    else:
        t = runner.atlas.tosi_initial_temperature(cells)
        c = np.zeros((cells, cells), dtype=np.float64)
    require(t.shape == c.shape == (cells, cells), 'Fixture shape mismatch.')
    require(np.isfinite(t).all() and np.isfinite(c).all(), 'Nonfinite fixture fields.')
    t.setflags(write=False); c.setflags(write=False)
    meta = {'cells': cells, 'case': 'tosi-2', 'provenance': provenance,
            'temperature_k': array_record(t), 'composition': array_record(c)}
    meta['input_sha256'] = sha(encode(meta))
    meta['preparation_seconds'] = time.perf_counter() - started
    np.savez(out / f'input-{cells}.npz', temperature_k=t, composition=c)
    meta['saved_npz_sha256'] = sha((out / f'input-{cells}.npz').read_bytes())
    write_json(out / f'input-{cells}.json', meta)
    return t, c, meta


def validate_seed_chain(states, mode):
    """Check accepted-state links without inventing, retaining or replacing seeds."""
    previous = None
    for state in states:
        record = state.descriptor()['step_record']['nonlinear_mechanics']
        stages = record['stages']
        require(len(stages) == 2, 'Each accepted step requires two mechanical stages.')
        if mode == 'zero-rate':
            require(state.next_initial_guess is None, 'Zero-rate unexpectedly published a seed.')
            require('cross_step_start' not in record, 'Undeclared cross-step start.')
            continue
        cross = record['cross_step_start']
        seed = state.next_initial_guess
        require(seed is not None and cross['output_guess_id'] == seed.guess_id,
                'Accepted output seed identity mismatch.')
        require(seed.descriptor()['source_result_id'] == stages[1]['result_id'],
                'Output seed is not from the current second stage.')
        require(stages[1]['initial_guess_result_id'] == stages[0]['result_id'],
                'Second stage was not seeded by the current first stage.')
        if previous is None:
            require(cross['input_guess_id'] is None and cross['input_stage1_result_id'] is None
                    and stages[0]['initial_guess_id'] is None
                    and stages[0]['initial_guess_result_id'] is None,
                    'A new-source first step must not claim a predecessor seed.')
        else:
            old = previous.next_initial_guess
            expected = previous.descriptor()['step_record']['nonlinear_mechanics']['stages'][1]['result_id']
            require(cross['input_state_id'] == previous.state_id, 'Wrong accepted predecessor.')
            require(cross['input_guess_id'] == old.guess_id == stages[0]['initial_guess_id'],
                    'Second step did not consume the accepted seed.')
            require(cross['input_stage1_result_id'] == expected == stages[0]['initial_guess_result_id'],
                    'Second-step seed result provenance mismatch.')
        previous = state


def compare_arrays(left, right):
    """Raw differences, not new acceptance thresholds or a physics certificate."""
    import numpy as np
    with np.load(left, allow_pickle=False) as a, np.load(right, allow_pickle=False) as b:
        common = sorted(set(a.files) & set(b.files))
        result = {}
        for key in common:
            x, y = a[key], b[key]
            require(x.shape == y.shape, 'Comparison shape mismatch.')
            require(np.isfinite(x).all() and np.isfinite(y).all(), 'Nonfinite comparison output.')
            delta = y - x
            scale = float(np.max(np.abs(x)))
            linf = float(np.max(np.abs(delta)))
            result[key] = dict(bit_equal=np.array_equal(x, y), max_abs=linf,
                               rms=float(np.sqrt(np.mean(delta * delta))),
                               relative_linf=None if scale == 0 else linf / scale)
        require(bool(common), 'No comparable fields.')
        return {'fields': result, 'only_baseline': sorted(set(a.files) - set(b.files)),
                'only_candidate': sorted(set(b.files) - set(a.files)),
                'cross_mode_equivalence_accepted': False,
                'note': 'Differences require review; no tolerance was invented or relaxed.'}


def trial(runner, t, c, meta, mode, args, out, label, *, split=False):
    """Two coupled steps; inspection, array export and optional restart I/O excluded."""
    import numpy as np
    at = runner.atlas
    argv = profile_argv(out / label, meta['cells'], mode, args.dt, args.seconds)
    parsed = runner.parser().parse_args(argv)
    kw = policies(runner, parsed)
    budget = runner.WorkBudget(1024 << 20)
    cancel = runner.Cancellation(args.seconds)
    handlers = {sig: signal.signal(sig, cancel.signal) for sig in (signal.SIGINT, signal.SIGTERM)}
    steps = []
    plan = None
    record = dict(label=label, mode=mode, cells=meta['cells'], input_sha256=meta['input_sha256'],
                  profile_switches=argv, policies=policy_record(kw), restart_check=split,
                  prepared_scope='state capture + plan construction + two advances + close', **STATUS)
    clock = time.perf_counter()
    try:
        case = at.TosiCase(parsed.case, parsed.yield_stress)
        problem = case.problem(meta['cells'])
        state = at.ThermochemicalState(problem, t, c, time_s=0.,
                    source='R4.4 combined benchmark new input ' + meta['input_sha256'], budget=budget)
        record['initial_state_id'] = state.state_id
        plan = at.PreparedThermochemical2D(problem, budget=budget, cancel=cancel, **kw)
        record['preparation_seconds'] = time.perf_counter() - clock
        record['step_seconds'] = []
        record['restart_io_seconds'] = 0.0
        for i in range(2):
            before = time.perf_counter()
            step = plan.advance(state, args.dt, source=runner.STEP_SOURCE, cancel=cancel)
            record['step_seconds'].append(time.perf_counter() - before)
            steps.append(step)
            state = step.state
            if split and i == 0:
                io = time.perf_counter()
                plan.close(); plan = None
                with runner.ArrayStore(out / (label + '.sqlite'),
                        runner.StoreLimits(chunk_bytes=65536, max_store_bytes=2 << 30,
                                           max_array_bytes=32 << 20), budget=budget) as store:
                    at.save_thermochemical_state(state, store, budget=budget, cancel=cancel)
                with runner.ArrayStore(out / (label + '.sqlite'),
                        runner.StoreLimits(chunk_bytes=65536, max_store_bytes=2 << 30,
                                           max_array_bytes=32 << 20), budget=budget) as store:
                    restored = at.load_thermochemical_state(store, state.state_id,
                                                          budget=budget, cancel=cancel)
                require(restored.state_id == state.state_id, 'Restart state identity mismatch.')
                for name in state.array_names:
                    require(np.array_equal(restored.array(name), state.array(name)),
                            'Restart changed checkpoint arrays.')
                state = restored
                plan = at.PreparedThermochemical2D(problem, budget=budget, cancel=cancel, **kw)
                record['restart_io_seconds'] = time.perf_counter() - io
        before = time.perf_counter()
        plan.close(); plan = None
        record['close_seconds'] = time.perf_counter() - before
        record['elapsed_seconds'] = time.perf_counter() - clock
        record['outcome'] = 'COMPLETE_STRICT_GATED'
    except BaseException as exc:
        record.update(outcome='CANCELLED' if isinstance(exc, CancelledError) else 'FAILED',
                      elapsed_seconds=time.perf_counter() - clock,
                      error=type(exc).__name__ + ': ' + str(exc), traceback=traceback.format_exc())
        raise
    finally:
        try:
            if plan is not None:
                plan.close()
        finally:
            record['budget_after_close'] = budget.statistics()
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
            # Retain a partial record even if a solver or resource check refused.
            write_json(out / (label + '.timing.json'), record)
    require(record['budget_after_close']['reserved_bytes'] == 0, 'Leaked work reservations.')
    validation = time.perf_counter()
    validate_seed_chain([s.state for s in steps], mode)
    arrays, states = {}, []
    for index, step in enumerate(steps, 1):
        state = step.state
        states.append({'state_id': state.state_id, 'metadata': state.descriptor()})
        for name in state.array_names:
            arrays[f'step{index}.state.{name}'] = state.array(name)
        for name in step.array_names:
            arrays[f'step{index}.transport.{name}'] = step.array(name)
        # Exact decoder independently checks stored records and seed commitments.
        decoded = at.ThermochemicalState.restore(state.descriptor(),
                          {k: state.array(k) for k in state.array_names}, budget=budget)
        require(decoded.state_id == state.state_id, 'Post-timing typed-state roundtrip failed.')
    write_json(out / (label + '.states.json'), states)
    np.savez(out / (label + '.arrays.npz'), **arrays)
    validated = dict(outcome='VALIDATED', seed_chain_checked=True,
                     step_metrics=[{'step': s.state.step_index,
                         'balances': s.state.descriptor()['step_record']['balances'],
                         'mechanics': s.state.descriptor()['step_record']['nonlinear_mechanics']}
                         for s in steps],
                     typed_decode_checked=True, final_state_id=steps[-1].state.state_id,
                     input_state_id=record['initial_state_id'],
                     state_ids=[s.state.state_id for s in steps],
                     array_hashes={k: array_record(v) for k, v in arrays.items()},
                     validation_export_seconds=time.perf_counter() - validation,
                     budget_after_validation=budget.statistics(),
                     caller_retained_step_bytes=sum(s.nbytes for s in steps))
    require(validated['budget_after_validation']['reserved_bytes'] == 0,
            'Validation leaked work reservations.')
    write_json(out / (label + '.validation.json'), validated)
    return record, validated


def run_child_cooperatively(command):
    """Wait for owned child shutdown before releasing the benchmark host lease.

    A native call/JIT may exceed the allowance; no SIGKILL, stale-lock deletion or
    fabricated completion is used. On Windows, wait for the child's own deadline
    instead of turning SIGTERM into an unsafe TerminateProcess call.
    """
    interrupted = []
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True) as child:
        def request(signum, _frame):
            interrupted.append(signum)
            if os.name != 'nt' and child.poll() is None:
                try:
                    child.send_signal(signum)
                except ProcessLookupError:
                    pass
        handlers = {sig: signal.signal(sig, request)
                    for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            stdout, stderr = child.communicate()
        finally:
            # communicate normally waits; this also covers unexpected reader errors.
            if child.poll() is None:
                if os.name != 'nt':
                    child.send_signal(signal.SIGTERM)
                child.wait()
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
    return subprocess.CompletedProcess(command, child.returncode, stdout, stderr), bool(interrupted)


def cli_restart_check(runner, args, out):
    """Actual existing switches, independent fresh processes, exact resume equality.

    These are correctness invocations, not warm-JIT performance measurements.
    Endpoint sampling and checkpoint writes are unchanged, and are retained.
    """
    results = {}
    for mode in MODES:
        full, split = out / ('cli-full-' + mode), out / ('cli-split-' + mode)
        calls = [(full, False, 2), (split, False, 1), (split, True, 1)]
        observations = []
        for number, (directory, resume, segment) in enumerate(calls):
            argv = profile_argv(directory, 16, mode, args.dt, args.seconds,
                                resume=resume, segment=segment)
            cmd = [sys.executable, '-I', '-B', str(ROOT / 'tools/run_convection_r4_4.py'), *argv]
            clock = time.perf_counter()
            # No forced kill: the runner's cooperative bound preserves accepted-state save.
            p, interrupted = run_child_cooperatively(cmd)
            elapsed = time.perf_counter() - clock
            (out / f'cli-{mode}-{number}.stdout.txt').write_text(p.stdout, encoding='utf-8')
            (out / f'cli-{mode}-{number}.stderr.txt').write_text(p.stderr, encoding='utf-8')
            item = {'command': cmd, 'returncode': p.returncode,
                    'cold_correctness_seconds_not_performance': elapsed}
            observations.append(item)
            write_json(out / f'cli-{mode}-{number}.json', item)
            if interrupted:
                raise CancelledError('Controller cancelled; child has finished shutdown.')
            require(p.returncode == 0, 'Fresh-process runner correctness invocation failed.')
            config = json.loads((directory / 'run.json').read_bytes())
            records, _ = runner.read_receipts(directory, runner.digest(runner.encode(config)))
            target = 1 if not resume and segment == 1 else 2
            require(records[-1]['step'] == target, 'CLI cancelled before the requested accepted endpoint.')
        a = json.loads((full / 'receipt_000000002.json').read_bytes())
        b = json.loads((split / 'receipt_000000002.json').read_bytes())
        require(a == b, 'Fresh-process uninterrupted/restarted receipt differs.')
        # Both stores must independently decode every array, including the accepted seed.
        for directory in (full, split):
            with runner.ArrayStore(directory / 'states.sqlite',
                    runner.StoreLimits(chunk_bytes=65536, max_store_bytes=2 << 30,
                                       max_array_bytes=32 << 20)) as store:
                restored = runner.atlas.load_thermochemical_state(store, a['state_id'])
                require(restored.state_id == a['state_id'], 'Fresh-process store decode differs.')
        results[mode] = {'calls': observations, 'receipt_exact': True, 'state_id': a['state_id']}
    write_json(out / 'cli-restart-checks.json', results)
    return results


def environment():
    versions = {}
    for name in ('numpy', 'scipy', 'numba', 'llvmlite', 'threadpoolctl', 'blosc2', 'shapely'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return dict(python=sys.version, executable=sys.executable, platform=platform.platform(),
                machine=platform.machine(), processor=platform.processor(),
                cpu_count=os.cpu_count(), versions=versions,
                threads={k: os.environ.get(k) for k in THREAD_VARIABLES},
                command=sys.argv, utc=datetime.now(timezone.utc).isoformat())


def arguments(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--exclusive-host-confirmed', action='store_true',
                   help='Required acknowledgement: no other numerical benchmark uses this host.')
    p.add_argument('--lock-file', type=Path,
                   default=Path(tempfile.gettempdir()) / 'atlas-native-numerical-benchmark.lock')
    p.add_argument('--repeats', type=int, choices=(1, 2, 3), default=3)
    p.add_argument('--dt', type=float, default=1e-7)
    p.add_argument('--seconds', type=float, default=120., help='Cooperative allowance per trial.')
    p.add_argument('--fixture', type=Path, help='Optional already-128-square raw fields, never a checkpoint.')
    p.add_argument('--fixture-manifest', type=Path)
    p.add_argument('--profile', action='store_true', help='Separate cProfile trials excluded from A/B samples.')
    p.add_argument('--preflight-only', action='store_true', help='No Atlas import or numerical work.')
    a = p.parse_args(argv)
    require(math.isfinite(a.dt) and 0 < a.dt <= .01, 'Invalid fixed timestep.')
    require(math.isfinite(a.seconds) and 0 < a.seconds <= 300, 'Allowance must be 0 < seconds <= 300.')
    require((a.fixture is None) == (a.fixture_manifest is None), 'Fixture and manifest must be supplied together.')
    require(a.exclusive_host_confirmed or a.preflight_only, 'Exclusive numerical host not confirmed.')
    return a


def main(argv=None):
    args = arguments(argv)
    out = no_symlink(args.output)
    out.mkdir(parents=False, exist_ok=False)
    sys.dont_write_bytecode = True
    for key in THREAD_VARIABLES:
        os.environ[key] = '1'
    report = dict(**STATUS, base=BASE, harness_sha256=sha(Path(__file__).read_bytes()),
                  numerical_trials_completed=0,
                  recommendation='DO_NOT_PROMOTE_PROFILE_WITHOUT_MEASURED_EVIDENCE')
    write_json(out / 'environment.json', environment())
    try:
        before = source_audit(ROOT)
        write_json(out / 'source-before.json', before)
        if args.preflight_only:
            report['outcome'] = 'PREFLIGHT_ONLY_NO_NUMERICS'
            return 0
        with host_lock(args.lock_file):
            # Import numerical libraries only after exact-byte and exclusivity checks.
            runner = load_runner(ROOT)
            import numba
            from threadpoolctl import threadpool_info, threadpool_limits
            numba.set_num_threads(1)
            with threadpool_limits(limits=1):
                pools = threadpool_info()
                require(all(p['num_threads'] == 1 for p in pools), 'Native thread limit not effective.')
                write_json(out / 'native-threadpools.json', pools)
                with runner.ExecutionContext('numba') as context:
                    write_json(out / 'runtime-identity.json', {'identity': context.identity})
                cli_restart_check(runner, args, out)
                suites = {}
                for cells in (16, 128):
                    t, c, meta = fixture(runner, cells, args, out)
                    warm = {}
                    for mode in MODES:
                        label = f'n{cells}-warmup-{mode}'
                        # Warm the actual combined signature and mesh paths; no warm-up sample is timed evidence.
                        warm[mode] = trial(runner, t, c, meta, mode, args, out, label)
                    require(warm[MODES[0]][1]['input_state_id'] == warm[MODES[1]][1]['input_state_id'],
                            'Baseline and candidate did not start from the identical typed input.')
                    warm_diff = compare_arrays(out / f'n{cells}-warmup-zero-rate.arrays.npz',
                                               out / f'n{cells}-warmup-previous-stage1.arrays.npz')
                    write_json(out / f'n{cells}-warmup-differences.json', warm_diff)
                    # Check exact accepted-state restart, including first/second-stage seed identity.
                    for mode in MODES:
                        label = f'n{cells}-restart-{mode}'
                        _, checked = trial(runner, t, c, meta, mode, args, out, label, split=True)
                        require(checked['state_ids'] == warm[mode][1]['state_ids'],
                                'Recreated-plan restart differs from uninterrupted state identity.')
                        delta = compare_arrays(out / (label + '.arrays.npz'),
                                               out / f'n{cells}-warmup-{mode}.arrays.npz')
                        require(not delta['only_baseline'] and not delta['only_candidate'] and
                                all(x['bit_equal'] for x in delta['fields'].values()),
                                'Restart changed numerical output arrays.')
                    pairs, comparisons, sample_details = [], [], []
                    for rep in range(args.repeats):
                        pair, detail = {}, {}
                        for mode in order(rep):
                            require(all(p['num_threads'] == 1 for p in threadpool_info()),
                                    'Native thread count changed before a trial.')
                            label = f'n{cells}-r{rep + 1}-{mode}'
                            record, checked = trial(runner, t, c, meta, mode, args, out, label)
                            require(checked['state_ids'] == warm[mode][1]['state_ids'],
                                    'Same-mode repeated state identity changed.')
                            pair[mode] = record['elapsed_seconds']
                            detail[mode] = record
                            report['numerical_trials_completed'] += 1
                        comparison = compare_arrays(out / f'n{cells}-r{rep + 1}-zero-rate.arrays.npz',
                                                     out / f'n{cells}-r{rep + 1}-previous-stage1.arrays.npz')
                        write_json(out / f'n{cells}-r{rep + 1}-differences.json', comparison)
                        pairs.append(pair); comparisons.append(comparison); sample_details.append(detail)
                    components = {}
                    for component in ('preparation_seconds', 'close_seconds', 'step1', 'step2'):
                        samples = [{m: (item[m]['step_seconds'][int(component[-1]) - 1]
                                        if component.startswith('step') else item[m][component])
                                    for m in MODES} for item in sample_details]
                        components[component] = {'raw_seconds': samples, 'summary': summary(samples)}
                    suites[str(cells)] = dict(input=meta, raw_seconds=pairs, summary=summary(pairs),
                        components=components,
                        order=[list(order(i)) for i in range(args.repeats)],
                        sample_details=sample_details, differences=comparisons,
                        warmup_seconds={m: warm[m][0]['elapsed_seconds'] for m in MODES})
                    write_json(out / f'n{cells}-summary.json', suites[str(cells)])
                    if args.profile:
                        for mode in MODES:
                            profiler = cProfile.Profile()
                            label = f'n{cells}-profile-{mode}'
                            profiler.runcall(trial, runner, t, c, meta, mode, args, out, label)
                            profiler.dump_stats(str(out / (label + '.prof')))
                            with (out / (label + '.profile.txt')).open('x', encoding='utf-8') as stream:
                                pstats.Stats(profiler, stream=stream).sort_stats('cumulative').print_stats(60)
                    del t, c, warm
                report['suites'] = suites
                report['outcome'] = 'BOUNDED_BENCHMARK_COMPLETE_PENDING_REVIEW'
                report['recommendation'] = 'PARENT_REVIEW_REQUIRED_NO_DEFAULT_CHANGE'
        after = source_audit(ROOT)
        require(after == before, 'Source changed during measurements.')
        write_json(out / 'source-after.json', after)
        return 0
    except BaseException as exc:
        report.update(outcome='BLOCKED_OR_FAILED_NO_PROFILE_PROMOTION',
                      error=type(exc).__name__ + ': ' + str(exc), traceback=traceback.format_exc())
        return 2
    finally:
        write_json(out / 'result.json', report)
        print(json.dumps({k: report[k] for k in ('outcome', 'numerical_trials_completed', 'recommendation')
                          if k in report}), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
