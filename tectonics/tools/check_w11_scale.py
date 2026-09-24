#!/usr/bin/env python3
"""Bounded W11 regional scale study; unchanged production, new evidence only.

Five alternating cold/prepared pairs at 8, 16 and 24 cells per direction.
Each trial produces the same three CHANGED steady mechanical outputs. This is
not a time integration, multiresolution solver or planetary performance claim.
"""
from concurrent.futures import CancelledError
from contextlib import ExitStack
from datetime import datetime, timezone
import argparse
import ctypes
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SIZES = (8, 16, 24)
PAIRS = 5
OUTPUTS = 3
LIMIT_BYTES = 128 * 1024**2
FIXTURE_BYTES = 4 * 1024**2
LIMIT_SECONDS = 120.0
REPORT_LIMIT_BYTES = 2 * 1024**2
CONTROLS = ((1.0, 0.5), (2.0, 1.0), (2.0, 1.5))


class Deadline:
    """The same cooperative cancellation object reaches every admitted solve."""
    def __init__(self, seconds, clock=time.perf_counter):
        self.clock = clock
        self.start = clock()
        self.end = self.start + seconds
        self.interrupted = False

    def is_set(self):
        return self.interrupted or self.clock() >= self.end

    def check(self):
        if self.is_set():
            raise CancelledError('study cancelled or 120 s cooperative deadline reached')


def pair_order(pairs=PAIRS):
    return tuple((False, True) if i % 2 == 0 else (True, False) for i in range(pairs))


class EvidenceWriter:
    """Claim the new destination before expensive work; never reopen/overwrite it."""
    def __init__(self, path):
        self.stream = path.open('xb')
        self.completed = False
        try:
            self.stream.write(b'{"schema":"atlas.w11-claimed-evidence.v1","status":"INCOMPLETE","stage":"destination claimed; final result not published"}\n')
            self.stream.flush()
        except BaseException:
            self.stream.close()
            raise

    def write(self, report):
        if self.completed:
            raise RuntimeError('evidence already delivered')
        raw = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
        if len(raw) > REPORT_LIMIT_BYTES:
            raise ValueError('bounded evidence exceeds 2 MiB')
        # Replace only the marker created by this still-owned exclusive handle.
        self.stream.seek(0)
        self.stream.write(raw)
        self.stream.truncate()
        self.stream.flush()
        self.completed = True
        return len(raw)

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def write_evidence(path, report):
    writer = EvidenceWriter(path)
    try:
        return writer.write(report)
    finally:
        writer.close()


def process_memory():
    """OS observation, never an allocation cap or per-trial isolated peak."""
    if os.name == 'nt':
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                    'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                    'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        value = Counters()
        value.cb = ctypes.sizeof(value)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb):
            return {'available': False, 'reason': 'GetProcessMemoryInfo failed'}
        return {'available': True, 'method': 'Windows GetProcessMemoryInfo',
                'current_rss_bytes': value.WorkingSetSize,
                'process_lifetime_peak_rss_bytes': value.PeakWorkingSetSize}
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result = {'available': True, 'method': 'getrusage(RUSAGE_SELF)',
                  'process_lifetime_peak_rss_bytes': int(peak * (1 if sys.platform == 'darwin' else 1024))}
        if sys.platform.startswith('linux'):
            for line in Path('/proc/self/status').read_text().splitlines():
                if line.startswith('VmRSS:'):
                    result['current_rss_bytes'] = int(line.split()[1]) * 1024
        return result
    except (ImportError, OSError):
        return {'available': False, 'reason': 'no supported standard-library OS observation'}


def hardware():
    out = {'platform': platform.platform(), 'machine': platform.machine(),
           'processor': platform.processor(), 'logical_cpus': os.cpu_count(),
           'python': platform.python_version(), 'pointer_bits': ctypes.sizeof(ctypes.c_void_p) * 8}
    if os.name == 'nt':
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ('total', 'available', 'page_total',
                    'page_available', 'virtual_total', 'virtual_available', 'extended')]
        value = MemoryStatus()
        value.length = ctypes.sizeof(value)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            out.update(physical_memory_bytes=value.total, available_physical_memory_bytes=value.available)
    return out


def execution_card(report_path):
    return {'question': 'Does existing prepared reuse preserve complete changed outputs as regional grids grow?',
        'classification': 'E: execution reuse; no equation, discretisation or tolerance change',
        'status': 'WORKING NON-CANON', 'grid_sizes': list(SIZES), 'paired_repetitions': PAIRS,
        'outputs_per_trial': OUTPUTS, 'trial_order': [['prepared' if r else 'cold' for r in p] for p in pair_order()],
        'hardware': hardware(),
        'installed_versions_before_import': {name: version(name) for name in ('numpy', 'scipy', 'threadpoolctl')},
        'shared_accounting_limit_bytes': LIMIT_BYTES,
        'fixture_allowance_bytes': FIXTURE_BYTES, 'native_threads': 1,
        'whole_study_cooperative_limit_s': LIMIT_SECONDS,
        'stop': 'one deadline from before scientific imports; SIGINT and all normal cancellation checks; no retry',
        'cancellation_limit': 'native calls and imports are not hard-interruptible; deadline checked at boundaries',
        'storage': {'scratch_files_bytes': 0, 'checkpoint_bytes': 0, 'report_limit_bytes': REPORT_LIMIT_BYTES,
                    'output_disk_free_bytes': shutil.disk_usage(report_path.parent).free},
        'memory_scope': '128 MiB shared numerical admission is not process RSS; no subprocesses or device work',
        'cold_warm_scope': 'new owner per output versus one owner per three outputs in the same process; OS caches uncontrolled',
        'oracle': {'u_absolute_error_m_s': 1e-9, 'w_absolute_error_m_s': 1e-9,
                   'shear_stress_absolute_error_pa': 1e-8, 'formula': 'u=shear*z, w=0, tau_xz=viscosity*shear'},
        'acceptance': 'complete byte/ID parity, three distinct results and no result hits, affine oracle, all retained gates, zero reservations',
        'useful_improvement': 'positive median total trial time saving at each tested size; report regressions without changing defaults',
        'limits': 'three synthetic stationary steady regional supports; no scale extrapolation, adaptive transfer or R4.4 campaign; 256 accepted-step ceiling unchanged'}


def load_backend():
    # Reuse the existing source inventory and full-array signature machinery.
    # Its typed upstream fixture helpers are imported but never executed here.
    sys.path.insert(0, str(ROOT / 'tools'))
    import check_evolving_inputs
    return check_evolving_inputs


def source_binding(backend):
    out = backend.source_binding()
    for path in (Path(__file__), ROOT / 'tools/check_evolving_inputs.py', ROOT / 'tests/test_w11_scale.py'):
        out['tools_and_fixtures'][path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def fixture(n, b, deadline):
    np = b.np
    kinds = {s: {c: 'velocity' for c in ('u', 'w')} for s in ('left', 'right', 'bottom', 'top')}
    requests = []
    owner = b.WorkBudget(LIMIT_BYTES)
    with owner.reserve(FIXTURE_BYTES, category='w11-fixture-construction'):
        for i, (eta, shear) in enumerate(CONTROLS):
            deadline.check()
            context = b.RegionalInputContext(n, n, 1., 1., 'w11-synthetic-section', 'z0', 'seconds', float(i), 0., 0.)
            common = dict(budget=owner, cancel=deadline)
            material = b.RegionalInputBlock(context, 'material',
                {'centre': np.full((n, n), eta), 'vertex': np.full((n+1, n+1), eta)},
                source_id='supplied Newtonian fixture', producer_state_id=f'material-{i}',
                sampling='uniform exact stress sites', **common)
            force = b.RegionalInputBlock(context, 'body-force',
                {'u': np.zeros((n, n+1)), 'w': np.zeros((n+1, n))}, source_id='known zero force',
                producer_state_id=f'force-{i}', sampling='full MAC faces', effect_ids=('no-body-force',), **common)
            boundary = b.RegionalInputBlock(context, 'boundary',
                {s+'_'+c: shear*b.boundary_coordinates(n, n, 1., 1., s, c)[1] if c == 'u' else 0.
                 for s in kinds for c in ('u', 'w')}, source_id='analytic simple shear',
                producer_state_id=f'boundary-{i}', sampling='exact affine trace',
                effect_ids=('plate-motion',), boundary_types=kinds, **common)
            requests.append(b.RegionalMechanicalRequest(material, (force,), boundary))
    if owner.reserved_bytes or sum(r.nbytes for r in requests) > FIXTURE_BYTES:
        raise AssertionError('fixture exceeds declared shared reservation')
    return requests, kinds, owner.statistics()


def checked_output(result, n, index, b):
    np = b.np
    eta, shear = CONTROLS[index]
    expected_u = np.broadcast_to(shear*(np.arange(n)+0.5)[:, None]/n, (n, n+1))
    errors = {'u_m_s': float(np.max(np.abs(result.array('u_m_s')-expected_u))),
              'w_m_s': float(np.max(np.abs(result.array('w_m_s')))),
              'shear_stress_pa': float(np.max(np.abs(result.array('deviatoric_stress_xz_pa')-eta*shear)))}
    if errors['u_m_s'] > 1e-9 or errors['w_m_s'] > 1e-9 or errors['shear_stress_pa'] > 1e-8:
        raise AssertionError('independent affine oracle failed')
    mechanics = result.mechanics.descriptor()
    if mechanics['diagnostics']['gates_passed'] is not True or mechanics['diagnostics']['linear_residual'] > 1e-12:
        raise AssertionError('retained mechanical gate failed')
    return {'affine_max_errors': errors, 'mechanical_diagnostics': mechanics['diagnostics'],
            'dimensional_diagnostics': mechanics['dimensional_diagnostics'], 'iterations': mechanics['iterations']}


def complete_signature(result, b):
    # The retained helper covers wrapper descriptor/ID and every array. Include
    # the nested mechanics descriptor/ID too, including diagnostics/iterations.
    return hashlib.sha256(b.encoded({'wrapper_and_arrays': b.signature(result),
        'mechanics_id': result.mechanics.result_id, 'mechanics': result.mechanics.descriptor()})).hexdigest()


def trial(n, requests, kinds, reuse, b, deadline, record):
    owner = b.WorkBudget(LIMIT_BYTES)
    hashes, result_ids, controls, stats = [], [], [], []
    phases = dict(owner_construction_s=0., evaluate_including_deferred_preparation_s=0.,
                  independent_checks_s=0., complete_output_hashing_s=0., close_s=0.)
    record.update(mode='prepared' if reuse else 'cold', process_memory_before=process_memory())
    started = time.perf_counter()
    try:
        with owner.reserve(FIXTURE_BYTES, category='w11-fixtures-and-oracle'):
            for indices in ((range(OUTPUTS),) if reuse else ((i,) for i in range(OUTPUTS))):
                deadline.check()
                before = time.perf_counter()
                plan = b.PreparedEvolvingRegionalMechanics(requests[0].context, kinds,
                    scales=b.RegionalMechanicsScales(1., 1.), viscosity_scale_pa_s=1.,
                    physical_mean_pressure_pa=0., budget=owner, cancel=deadline)
                phases['owner_construction_s'] += time.perf_counter()-before
                try:
                    for index in indices:
                        deadline.check()
                        before = time.perf_counter()
                        result = plan.evaluate(requests[index], cancel=deadline)
                        phases['evaluate_including_deferred_preparation_s'] += time.perf_counter()-before
                        before = time.perf_counter()
                        controls.append(checked_output(result, n, index, b))
                        phases['independent_checks_s'] += time.perf_counter()-before
                        before = time.perf_counter()
                        hashes.append(complete_signature(result, b))
                        result_ids.append(result.result_id)
                        phases['complete_output_hashing_s'] += time.perf_counter()-before
                        del result
                    stats.append(plan.statistics())
                finally:
                    before = time.perf_counter()
                    plan.close()
                    phases['close_s'] += time.perf_counter()-before
        deadline.check()
        if len(set(hashes)) != OUTPUTS or len(set(result_ids)) != OUTPUTS:
            raise AssertionError('three distinct changed outputs required')
        if sum(s['changed_outputs'] for s in stats) != OUTPUTS or any(
                s['latest_hits'] or s['mechanics']['latest_result_hits'] for s in stats):
            raise AssertionError('result reuse cannot masquerade as changed output computation')
        record['status'] = 'PASS'
    finally:
        record.update(elapsed_s=time.perf_counter()-started, phases_s=phases,
            complete_output_sha256=hashes, result_ids=result_ids, numerical_checks=controls,
            plan_statistics=stats, shared_accounting=owner.statistics(), process_memory_after=process_memory())
        record['phases_s']['other_trial_overhead_s'] = record['elapsed_s']-sum(phases.values())
        if owner.reserved_bytes:
            raise AssertionError('shared reservations survived trial cleanup')
    return hashes


def summarise_case(case):
    rows = case['trials']
    if len(rows) != PAIRS*2 or any(r.get('status') != 'PASS' for r in rows):
        raise AssertionError('incomplete pair coverage')
    expected = [mode for pair in pair_order() for mode in ('prepared' if p else 'cold' for p in pair)]
    if [r['mode'] for r in rows] != expected:
        raise AssertionError('changed pair order')
    baseline = rows[0]['complete_output_sha256']
    if any(r['complete_output_sha256'] != baseline for r in rows):
        raise AssertionError('complete output parity failed')
    timings = {mode: [r['elapsed_s'] for r in rows if r['mode'] == mode] for mode in ('cold', 'prepared')}
    summaries = {mode: {'raw_s': values, 'median_s': statistics.median(values),
                       'min_s': min(values), 'max_s': max(values)} for mode, values in timings.items()}
    cold, prepared = (summaries[m]['median_s'] for m in ('cold', 'prepared'))
    return {'status': 'PASS', 'complete_output_hash_parity': True, 'timing': summaries,
        'seconds_saved': cold-prepared, 'percent_saved': 100*(cold-prepared)/cold,
        'useful_improvement_observed': prepared < cold,
        'ranges_overlap': max(min(timings['cold']), min(timings['prepared'])) <= min(max(timings['cold']), max(timings['prepared'])),
        'peak_accounted_bytes': max(r['shared_accounting']['peak_reserved_bytes'] for r in rows),
        'final_reserved_bytes': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        raise FileExistsError('new evidence path required; no overwrite or retry')
    if not args.report.parent.is_dir():
        raise FileNotFoundError('existing evidence directory required')
    deadline = Deadline(LIMIT_SECONDS)
    card = execution_card(args.report)
    if card['storage']['output_disk_free_bytes'] < 2*REPORT_LIMIT_BYTES:
        raise ValueError('insufficient space for bounded evidence')
    print(json.dumps({'pre_run_execution_card': card}, sort_keys=True), flush=True)
    report = {'schema': 'atlas.w11-scale-evidence.v1', 'status': 'INCOMPLETE',
        'started_utc': datetime.now(timezone.utc).isoformat(), 'execution_card': card, 'cases': [],
        'process_memory_start': process_memory(),
        'included_in_trials': 'owner construction, deferred preparation, live source verification, three changed solves, all gates/oracles, full output hashing, close',
        'separate_costs': 'imports, one native lease, source inventories, fixture construction and evidence writing',
        'timing_limits': 'same-process serial instrumented wall time; no profiler, cold-disk claim, worker scaling or planet extrapolation',
        'memory_limits': 'OS peak is process-lifetime including imports/previous cases; current RSS sampled at trial boundaries; native and interpreter headroom separate'}
    # Refuse an unwritable/existing destination before importing or solving.
    # A killed process can leave this claimed file partial; it is never retried
    # under the same path, and a complete status is written only at closeout.
    writer = EvidenceWriter(args.report)
    old_handler = None
    b = None
    try:
        old_handler = signal.signal(signal.SIGINT, lambda *_: setattr(deadline, 'interrupted', True))
        before = time.perf_counter()
        b = load_backend()
        report['scientific_import_s'] = time.perf_counter()-before
        report['runtime'] = {'numpy': b.np.__version__, 'scipy': b.scipy.__version__, 'native_threads': 1}
        deadline.check()
        before = time.perf_counter()
        report['sources'] = source_binding(b)
        report['source_inventory_before_s'] = time.perf_counter()-before
        with ExitStack() as stack:
            before = time.perf_counter()
            stack.enter_context(b._native_lease())
            report['native_lease_setup_s'] = time.perf_counter()-before
            from threadpoolctl import threadpool_info
            pools = threadpool_info()
            report['native_pools'] = [{k: p[k] for k in ('internal_api', 'num_threads', 'version', 'architecture') if k in p} for p in pools]
            if any(p['num_threads'] != 1 for p in pools):
                raise AssertionError('native oversubscription')
            for n in SIZES:
                deadline.check()
                case = {'grid': [n, n], 'cells': n*n, 'trials': []}
                report['cases'].append(case)
                before = time.perf_counter()
                requests, kinds, accounting = fixture(n, b, deadline)
                case.update(fixture_setup_s=time.perf_counter()-before, fixture_accounting=accounting,
                    controls=CONTROLS, request_ids=[r.request_id for r in requests],
                    immutable_fixture_payload_bytes=sum(r.nbytes for r in requests))
                baseline = None
                for pair, order in enumerate(pair_order(), 1):
                    for reuse in order:
                        row = {'pair': pair}
                        case['trials'].append(row)
                        hashes = trial(n, requests, kinds, reuse, b, deadline, row)
                        if baseline is not None and hashes != baseline:
                            raise AssertionError('complete cold/prepared response identity changed')
                        baseline = hashes
                case['summary'] = summarise_case(case)
                del requests
                print(json.dumps({'grid': n, 'summary': case['summary']}, sort_keys=True), flush=True)
        deadline.check()
        report['status'] = 'PASS_BOUNDED_SCALE'
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status='CANCELLED' if isinstance(exc, (CancelledError, KeyboardInterrupt)) else 'FAIL',
            failure={'type': type(exc).__name__, 'message': str(exc).replace(str(ROOT.parent), '<repository>')})
    finally:
        if b is not None and 'sources' in report:
            before = time.perf_counter()
            try:
                final_sources = source_binding(b)
                report['source_bindings_unchanged'] = final_sources == report['sources']
                if not report['source_bindings_unchanged']:
                    report['status'] = 'FAIL_SOURCE_CHANGED'
                    report['sources_after_failure'] = final_sources
            except Exception as exc:
                report.update(status='FAIL_SOURCE_VERIFICATION', source_verification_error=type(exc).__name__)
            report['source_inventory_after_s'] = time.perf_counter()-before
        if old_handler is not None:
            signal.signal(signal.SIGINT, old_handler)
        report.update(wall_before_evidence_write_s=time.perf_counter()-deadline.start,
            process_memory_end=process_memory(), scratch_storage_created_bytes=0,
            scratch_cleanup='no scratch files or checkpoint stores created')
        if deadline.is_set() and report['status'] == 'PASS_BOUNDED_SCALE':
            report['status'] = 'CANCELLED'
        report['all_sizes_improve_median'] = len(report['cases']) == len(SIZES) and all(
            c.get('summary', {}).get('useful_improvement_observed', False) for c in report['cases'])
        before = time.perf_counter()
        try:
            size = writer.write(report)
        finally:
            writer.close()
        print(json.dumps({'status': report['status'], 'report_bytes': size,
            'evidence_write_s': time.perf_counter()-before,
            'wall_including_evidence_write_s': time.perf_counter()-deadline.start}, sort_keys=True), flush=True)
    return 0 if report['status'] == 'PASS_BOUNDED_SCALE' else 1


if __name__ == '__main__':
    raise SystemExit(main())
