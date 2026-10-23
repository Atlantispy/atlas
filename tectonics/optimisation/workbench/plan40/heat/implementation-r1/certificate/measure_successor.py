"""Actual full-module C3 arms. Default is no-clock smoke; timing needs queue GO."""
import sys
if not __debug__:
    raise RuntimeError('Normal Python mode required')
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

CONTROL_SHA = 'ba7dda0d0565f2fee86d38b07e098e921253987b93da22003e85546a1449e392'
DELTA_SHA = '673267ab8d11b9b591c4e430bf10d3917282faad68793b31c0f2c20f3c4757ee'
ORDERS = (('baseline', 'candidate'), ('candidate', 'baseline')) * 2


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def initialise(args, clock):
    root = Path(__file__).resolve().parent
    require(args.repo.is_absolute() and args.controls.is_absolute(), 'Explicit absolute input paths required')
    require(sha(args.controls) == CONTROL_SHA, 'Accepted controls changed')
    require(sha(root / 'SOURCE-DELTA.json') == DELTA_SHA, 'Source delta changed')
    delta = json.loads((root / 'SOURCE-DELTA.json').read_text())
    for name, expected in delta['successors'].items():
        require(sha(root / 'source/helpers' / name) == expected, 'Successor changed: ' + name)
    H = load('accepted_measurement_support', args.controls)
    # This is the unchanged selected dependency/resource resolver from accepted
    # controls. Neither arithmetic nor either caller is extracted or patched.
    fixture = args.output.with_name(args.output.stem + '-sources')
    fixture.mkdir(exist_ok=False)
    for name in ('private_heat_certification_kernel_r1.py', 'private_heat_compiled_dot_r1.py'):
        text = H.source(name)
        (fixture / name).write_bytes(text.encode('utf-8'))
        require(sha(fixture / name) == H.SOURCES[name]['public_sha256'], 'Baseline staging changed bytes')
    r3_name = 'private_heat_certification_kernel_r3.py'
    H.source(r3_name)
    r3_path = args.repo / H.SOURCES[r3_name]['public_path']
    modules, imports = {}, {}
    for arm, folder in (('baseline', fixture), ('candidate', root / 'source/helpers')):
        started = clock() if clock else None
        K = load('c3_full_' + arm, folder / 'private_heat_certification_kernel_r1.py')
        # Bind the unchanged r3 import once, before any arm loop. Each complete
        # r3 module retains its own actual K, with no algorithm monkeypatch.
        sys.modules['private_heat_certification_kernel_r1'] = K
        CERT = load('c3_r3_' + arm, r3_path)
        require(CERT.K is K, 'Caller import split')
        item = {'kernel_sha256': sha(folder / 'private_heat_certification_kernel_r1.py'),
                'r3_sha256': sha(r3_path)}
        if clock:
            item['module_import_seconds'] = clock() - started
        sys.modules.pop(K._H3_NAME, None)
        started = clock() if clock else None
        native = K._h3_module()
        if clock:
            item['native_import_compile_selftest_seconds'] = clock() - started
        require(native is not None, 'Actual pinned native helper unavailable: ' + arm)
        require(native._H3_SEAL == (str((folder / (K._H3_NAME + '.py')).resolve()), K._H3_SHA256),
                'Native source seal mismatch')
        # The complete module owns this cached route. Both modules remain live;
        # no sys.modules switching or source checks are moved out of arm calls.
        require(K._h3_module() is native, 'Native route not stable')
        item['native_sha256'] = K._H3_SHA256
        item['compiled_signature_count'] = sum(len(f.signatures) for f in native._COMPILED)
        imports[arm] = item
        modules[arm] = (K, CERT)
    return H, modules, imports, delta


def factory(H, modules, rank, scenario):
    K, CERT = modules
    rows = H.matrix(rank, 0)
    rhs = tuple(H.G.mpq(i + 1, 8) for i in range(rank))
    keys = [('cell', i) for i in range(rank)]
    budget = H.WorkBudget(256 * 1024 * 1024)

    def operation():
        if scenario == 'solve_physical':
            plan = H.INVENTORY.interval_plan(rank, rank, 320, 64, H.R)
            work = H.R.OwnedWorkspace(budget, plan.total, category='benchmark-full-interval')
            work.__enter__()
            dual = ar = proof = bounds = None
            try:
                dual, ar, proof = K.solve_enclosure(rows, rhs, precision=320)
                bounds = K.physical_bounds(rows, dual, keys, keys[:2], H.G.mpq(0),
                                          [H.G.mpq(1)] * rank, ar)
                answer = H.sig([dual, proof, bounds])
                dual = ar = proof = bounds = None
            except BaseException:
                work.__exit__(*sys.exc_info())
                raise
            else:
                work.__exit__(None, None, None)
        else:
            owner, reason = CERT._attempt(rows, rhs, keys, keys[:2], H.G.mpq(0),
                [H.G.mpq(1)] * rank, {}, precision=320, largest_owned_bytes=64,
                budget=budget, cancelled=None, audit={}, resource_evidence=[])
            require(owner is not None, 'Actual complete r3 attempt refused: ' + str(reason))
            try:
                answer = H.sig(owner.value)
            finally:
                owner.close()
        require(budget.reserved_bytes == 0, 'Retained charge after full component release')
        return answer, budget.peak_reserved_bytes

    return operation, digest(H.sig({'rows': rows, 'rhs': rhs, 'keys': keys, 'precision': 320}))


def arm_loop(H, modules, clock):
    records = []
    for rank in (4, 20):
        for scenario in ('solve_physical', 'r3_attempt_export'):
            built = {arm: factory(H, modules[arm], rank, scenario) for arm in modules}
            require(len({value[1] for value in built.values()}) == 1, 'Arm input mismatch')
            calls = 4 if rank == 4 else 1
            samples = []
            for pair, order in enumerate(ORDERS):
                for arm in order:
                    started = clock() if clock else None
                    values = [built[arm][0]() for _ in range(calls)]
                    seconds = clock() - started if clock else None
                    hashes = [digest(value[0]) for value in values]
                    require(len(set(hashes)) == 1, 'Nonrepeatable actual module output')
                    sample = dict(pair=pair, arm=arm, complete_calls=calls,
                        result_sha256=hashes[0], peak_accounted_bytes=max(value[1] for value in values))
                    if clock:
                        sample['seconds'] = seconds
                    samples.append(sample)
            require(len({sample['result_sha256'] for sample in samples}) == 1,
                    'Full baseline/candidate result mismatch')
            records.append(dict(rank=rank, precision=320, scenario=scenario, samples=samples,
                workload_sha256=next(iter(built.values()))[1],
                scope='Synthetic identity; complete actual module calls, source runtime guards, ownership and release'))
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--controls', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--smoke', action='store_true')
    mode.add_argument('--benchmark', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('--output must be new')
    import psutil
    process = psutil.Process()
    process.cpu_affinity(process.cpu_affinity()[:1])
    clock = None
    if args.benchmark:
        from time import perf_counter
        clock = perf_counter
    result = dict(schema='plan40b.certificate-actual-module-measurement.r1', status='FAIL', candidate='C3',
        mode='benchmark' if clock else 'smoke', script_sha256=sha(Path(__file__)),
        control_sha256=CONTROL_SHA, source_delta_sha256=DELTA_SHA, candidates={},
        bounds=dict(one_core=True, projected_peak_rss_mib=700, projected_runtime_seconds=180),
        limits=['Testing support needs no independent review; timed invocation still needs exact queue GO.',
                'No workers, scientific run, private runtime binding or whole-heat gain.',
                'Input creation, pinned source verification and import/build are outside arm clocks.',
                'Actual arithmetic/runtime guards, plan creation, owned envelope, output encoding and release are inside.',
                'Unchanged accepted source-bound dependency bootstrap includes extracted escaping-workspace support only.',
                'Native module internal import self-test clocks remain in source, but smoke records no elapsed performance.'])
    try:
        H, modules, imports, delta = initialise(args, clock)
        result['imports'] = imports
        result['successors'] = delta['successors']
        result['candidates']['C3'] = dict(status='PASS', benchmarks=arm_loop(H, modules, clock))
        result['sources'] = H.SOURCES
        result['status'] = 'PASS'
    except Exception as error:
        result['candidates']['C3'] = dict(status='FAIL', error_type=type(error).__name__, error=str(error))
    with args.output.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(result, handle, indent=2)
        handle.write('\n')
    print(json.dumps({'status': result['status'], 'mode': result['mode'], 'candidate': 'C3'}))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
