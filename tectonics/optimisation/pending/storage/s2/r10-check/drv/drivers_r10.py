"""S2 r10 evidence: R's own driver tests, every class, on R's drivers (base) and on the patched drivers with the
r8 compact_restart_patch preloaded, as the integrator would land them. Writes only under T/so/tmp.

  drivers_r10.py fresh VARIANT       all classes of R/test_fresh_interval_driver.py (60fba3c7 since 18:19; r9 pinned ace18923), in process
  drivers_r10.py prepared VARIANT    all classes of R/test_prepared_interval_driver.py (cb3f0aac); its run_scenario
                                    is replaced by the same subprocess call with this file's preloads and a temp
                                    folder under T/so/tmp (R's own puts it in R)
  drivers_r10.py scenario VARIANT NAME DIRECTORY   one scenario (R's '--scenario' entry), same preloads
VARIANT: base (nothing preloaded) or r10 (that CRP + T/so/s2/r8-check/drivers). Run with -B -P.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

T = Path(__file__).resolve().parents[4]
R = T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
S2 = T/'so/s2'
DRIVERS = S2/'r8-check/drivers'
TMP = T/'so/tmp'
PINS = {R/'test_fresh_interval_driver.py': '60fba3c7', R/'test_prepared_interval_driver.py': 'cb3f0aac',
        R/'fresh_interval_driver.py': 'd7bba076', R/'prepared_interval_driver.py': '6fb4ab6d',
        R/'compact_restart_patch.py': '9d076c80', DRIVERS/'fresh_interval_driver.py': '16b23929',
        DRIVERS/'prepared_interval_driver.py': 'f4f2ccc3', S2/'r10/compact_restart_patch.py': 'b9228231'}


def pinned():
    for path, short in PINS.items():
        if hashlib.sha256(path.read_bytes()).hexdigest()[:8] != short:
            raise SystemExit('%s is not %s: refusing' % (path, short))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def prepare(variant):
    sys.path.insert(0, str(R))
    if variant != 'base':
        load('compact_restart_patch', S2/variant/'compact_restart_patch.py')
        load('fresh_interval_driver', DRIVERS/'fresh_interval_driver.py')
        load('prepared_interval_driver', DRIVERS/'prepared_interval_driver.py')


def run(module, label):
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    with open(os.devnull, 'w') as sink:
        result = unittest.TextTestRunner(stream=sink).run(suite)
    loaded = {name: Path(sys.modules[name].__file__).parent.name for name in
              ('compact_restart_patch', 'fresh_interval_driver', 'prepared_interval_driver') if name in sys.modules}
    print('%s ran %d failures %d errors %d skipped %d | loaded %s' % (
        label, result.testsRun, len(result.failures), len(result.errors), len(result.skipped), loaded))
    for test, trace in result.failures+result.errors:
        print('   ', test.id().split('.', 1)[-1], '|', trace.strip().splitlines()[-1][:200])


def main():
    mode, variant = sys.argv[1], sys.argv[2]
    # R's prepared tests run one scenario without the seed on purpose, to see the driver refuse it.
    if sys.flags.hash_randomization != 0 and not (mode == 'scenario' and 'PYTHONHASHSEED' not in os.environ):
        raise SystemExit('refusing: the string-hash seed is not 0 (run without -I or -E, with PYTHONHASHSEED=0)')
    pinned()
    prepare(variant)
    if mode == 'fresh':
        run(load('test_fresh_interval_driver', R/'test_fresh_interval_driver.py'), 'fresh/'+variant)
    elif mode == 'scenario':
        load('test_prepared_interval_driver', R/'test_prepared_interval_driver.py').scenario_main(*sys.argv[3:5])
    elif mode == 'prepared':
        tm = load('test_prepared_interval_driver', R/'test_prepared_interval_driver.py')
        if variant != 'base':
            tm.DRIVER = DRIVERS/'prepared_interval_driver.py'

        def run_scenario(name, *, seeded=True):  # R's run_scenario, with this file's preloads and own temp folder
            env = {k: v for k, v in tm.R.launch_environment().items() if seeded or k != 'PYTHONHASHSEED'}
            env.update(TMP=str(TMP), TEMP=str(TMP))
            with tempfile.TemporaryDirectory(prefix='pd-', dir=TMP) as directory:
                result = subprocess.run([sys.executable, '-B', '-P', __file__, 'scenario', variant, name, directory],
                                        cwd=TMP, env=env, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                raise AssertionError(result.stdout[-3000:]+result.stderr[-6000:])
            return json.loads(result.stdout.strip().splitlines()[-1])
        tm.run_scenario = run_scenario
        run(tm, 'prepared/'+variant)
    else:
        raise SystemExit('unknown mode '+mode)


if __name__ == '__main__':
    main()
