"""Refuter probe for the S2 r4 -> r5 delta: importers, route check, R driver tests on the patched drivers,
ledger allocation and read bounds. Writes only under this folder (tmp/)."""
import gzip, hashlib, json, os, subprocess, sys, tempfile, types
from pathlib import Path

T = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10'
R = T+'/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
RUNTIME = T+'/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/runtime-integration-r1/runtime-src'
S2R5 = T+'/so/s2/r5'
DRV = T+'/so/s2/r5-check/drivers'
HELP, SRC, CAP, CG = R+'/composed-r2/helpers', R+'/composed-r2/src', R+'/diagnostic-captures', R+'/compact-geometry-r1'
HERE = Path(__file__).resolve().parent
TMP = HERE/'tmp'
PY = sys.executable


def load(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def mode_import(label):
    sys.path[:0] = {'step8': [S2R5, CG, RUNTIME, R], 'composed': [S2R5, HELP, SRC]}[label]
    import compact_restart_patch as C
    print('imported', C.__file__.replace('\\', '/').split('/')[-2], hasattr(C, 'require_capture_route'),
          'capture_store loaded:', 'capture_store' in sys.modules)


def mode_route(case):
    sys.path[:0] = [S2R5, HELP, SRC] + ([CAP] if case in ('compact-cap', 'compact-loader') else [])
    import compact_restart_patch as C
    if case == 'stub-atlas':  # the stand-in package test_prepared_interval_driver's scenarios install
        stub = types.ModuleType('atlas_tectonics')
        stub.__path__ = []
        sys.modules['atlas_tectonics'] = stub
        try:
            print('result', C.require_capture_route(types.SimpleNamespace()))
        except BaseException as error:
            print('raised', type(error).__name__, str(error)[:120])
        return
    if case == 'noncompact-preloaded':
        import compact_restart_store  # as every composed workflow open/create does via accepts_store
    if case.startswith('noncompact'):
        before = set(sys.modules)
        result = C.require_capture_route(types.SimpleNamespace())
        new = sorted(set(sys.modules)-before)
        print('result', result, '| new modules', len(new), new[:6])
        return
    import compact_restart_store as CRS
    store = CRS.CompactRestartStore.__new__(CRS.CompactRestartStore)
    if case == 'compact-loader':  # same shape as run_prepared_restart.selected(): pin checked in get_code
        import importlib.machinery

        class Loader(importlib.machinery.SourceFileLoader):
            def get_code(self, fullname):
                raise RuntimeError('unbound source import: '+Path(self.path).name)

        class Finder:
            def find_spec(self, fullname, path=None, target=None):
                spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
                if spec and fullname == 'capture_store':
                    spec.loader = Loader(fullname, spec.origin)
                return spec
        sys.meta_path.insert(0, Finder())
    try:
        result = C.require_capture_route(store)
        print('result', result[:8] if result else result, '| capture_store loaded', 'capture_store' in sys.modules)
    except BaseException as error:
        print('raised', type(error).__name__, str(error)[:120])


def mode_prepared(variant, scenario):
    sys.path[:0] = [R]
    if variant == 'patched':  # landed state: R holds r5 compact_restart_patch and the driver lines
        load('compact_restart_patch', S2R5+'/compact_restart_patch.py')
        load('prepared_interval_driver', DRV+'/prepared_interval_driver.py')
    tm = load('test_prepared_interval_driver_probe', R+'/test_prepared_interval_driver.py')
    with tempfile.TemporaryDirectory(prefix='pd-', dir=TMP) as directory:
        tm.scenario_main(scenario, directory)


def mode_fresh(variant):
    import unittest
    sys.path[:0] = [R]
    if variant == 'patched':
        load('compact_restart_patch', S2R5+'/compact_restart_patch.py')
        load('fresh_interval_driver', DRV+'/fresh_interval_driver.py')
    tm = load('test_fresh_interval_driver_probe', R+'/test_fresh_interval_driver.py')
    print('driver', tm.F.__file__.replace('\\', '/').split('/')[-2])
    suite = unittest.TestSuite()
    for name in ('WiringTests', 'MeasurementHookTests'):
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(getattr(tm, name)))
    with open(os.devnull, 'w') as sink:
        result = unittest.TextTestRunner(stream=sink).run(suite)
    print('ran', result.testsRun, 'failures', len(result.failures), 'errors', len(result.errors))
    for test, trace in (result.failures+result.errors)[:3]:
        print('   ', test.id().split('.')[-1], '|', trace.strip().splitlines()[-1][:150])


def mode_ledger():
    sys.path[:0] = [S2R5, HELP, CAP, SRC]
    from atlas_tectonics.resources import WorkBudget
    import compact_restart_patch as C
    import ledger_fresh_interval as LG
    import capture_store
    import psutil
    print('machine RAM GiB', round(psutil.virtual_memory().total/2**30, 1), '| main() except tuple has MemoryError:',
          'MemoryError' in Path(LG.__file__).read_text(encoding='utf8'))
    caught = (LG.LedgerRefused, KeyError, TypeError, ValueError, OSError)
    state = dict(opened=False, requested=[])
    original_init = capture_store.CaptureReader.__init__

    def init(self, *args, **kwargs):
        state['opened'] = True
        return original_init(self, *args, **kwargs)
    capture_store.CaptureReader.__init__ = init

    class Stop(Exception):
        pass

    def recorder(n=0, *rest):
        state['requested'].append((n, 'reader opened' if state['opened'] else 'BEFORE reader opened'))
        if type(n) is int and n > (256 << 20):
            raise Stop()
        return bytearray(n, *rest)
    LG.bytearray = recorder

    def attempt(label, directory, operand):
        state.update(opened=False, requested=[])
        try:
            LG.capture(directory, operand)
            outcome = 'PASSED'
        except Stop:
            outcome = 'allocation intercepted (not performed)'
        except BaseException as error:
            outcome = '%s caught=%s %s' % (type(error).__name__, isinstance(error, caught), str(error)[:70])
        print('L', label, '->', outcome, '| bytearray requests:', state['requested'])

    with tempfile.TemporaryDirectory(dir=TMP) as d:
        d = Path(d)
        raw = json.dumps({'cells': [{'cell_id': str(i)} for i in range(5000)]}).encode()
        row = C.capture_operands(d, budget=WorkBudget(256 << 20), check=lambda: None, bounds=raw)['bounds']
        print('genuine capture: raw_bytes', row['raw_bytes'], 'stored_bytes', row['stored_bytes'])
        for label, change in (('genuine', {}), ('raw_bytes = 1 GiB', {'raw_bytes': 1 << 30}),
                              ('raw_bytes = 16 GiB (ceiling)', {'raw_bytes': 16 << 30}),
                              ('raw_bytes = 16 GiB + 1', {'raw_bytes': (16 << 30)+1})):
            attempt(label, d, dict(row, **change))
        # Legacy (no 'format'): what bounds the read and the decompression?
        seen, real = [], gzip.decompress

        def decompress(data, *args, **kwargs):
            out = real(data, *args, **kwargs)
            seen.append((len(data), len(out)))
            return out
        LG.gzip.decompress = decompress
        bomb = gzip.compress(bytes(64 << 20), 9)
        (d/'bomb.json.gz').write_bytes(bomb)
        sub = d/'sub'
        sub.mkdir()
        (d/'outside.json.gz').write_bytes(gzip.compress(raw))
        digest = hashlib.sha256(raw).hexdigest()
        for label, directory, operand in (
                ('legacy 64 MiB bomb, receipt raw_bytes 10', d,
                 dict(path='bomb.json.gz', raw_bytes=10, raw_sha256='0'*64, gzip_bytes=len(bomb))),
                ('legacy ../ path outside the run directory', sub,
                 dict(path='../outside.json.gz', raw_bytes=len(raw), raw_sha256=digest, gzip_bytes=1)),
                ('legacy absolute path', sub,
                 dict(path=str(d/'outside.json.gz'), raw_bytes=len(raw), raw_sha256=digest))):
            seen.clear()
            attempt(label, directory, operand)
            print('    gzip.decompress (input bytes, output bytes):', seen)


def child(*args, isolated=True):
    env = dict(os.environ, PYTHONHASHSEED='0', TEMP=str(TMP), TMP=str(TMP))
    command = [PY, '-B'] + (['-I'] if isolated else []) + [str(Path(__file__).resolve()), *args]
    out = subprocess.run(command, capture_output=True, text=True, cwd=str(TMP), env=env, timeout=300)
    return out.returncode, out.stdout.strip(), out.stderr.strip()


def main():
    TMP.mkdir(exist_ok=True)
    for label in ('step8', 'composed'):
        code, out, err = child('import', label)
        print('A import r5 on', label, 'path ->', out or err[-200:])
    for case in ('noncompact-preloaded', 'noncompact-cold', 'stub-atlas', 'compact-nocap', 'compact-cap', 'compact-loader'):
        code, out, err = child('route', case)
        print('C', case, '->', out or err[-200:])
    for variant in ('base', 'patched'):
        for scenario in ('success', 'compact-mesh'):
            code, out, err = child('prepared', variant, scenario, isolated=False)
            try:
                error = json.loads(out.splitlines()[-1])['error']
            except Exception:
                error = 'NO SUMMARY rc=%s %s' % (code, (err or out)[-200:])
            print('D prepared scenario', scenario, 'with', variant, 'driver -> error:', error)
        code, out, err = child('fresh', variant, isolated=False)
        print('D fresh WiringTests+MeasurementHookTests with', variant, 'driver ->', out.replace('\n', ' || ') or err[-300:])
    code, out, err = child('ledger')
    print(out if code == 0 else out+'\nERR '+err[-600:])


if __name__ == '__main__':
    if len(sys.argv) == 1:
        main()
    else:
        {'import': mode_import, 'route': mode_route, 'prepared': mode_prepared,
         'fresh': mode_fresh, 'ledger': mode_ledger}[sys.argv[1]](*sys.argv[2:])
