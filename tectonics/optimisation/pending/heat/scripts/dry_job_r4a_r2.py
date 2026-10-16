"""r2 (16 Oct 15:5x): r1 launched one REAL lw proof arm in case 3 (runq small sets no RUNQ_PRED_PEAK_GIB, so
case 1 refused at arm 1 before OUTDIR existed, and case 3 then called the real run() on a missing OUTDIR). r2: the
driver sets RUNQ_PRED_PEAK_GIB=1.1 (the q10a booking, as `runq run` does); every loaded ab_heat_r5 module gets a
subprocess whose Popen raises (nothing can launch); case 3 runs only if OUTDIR exists. Output evidence/dry-r4a-r2.

Dry run of scripts/job_h1c_r4a.sh (q10a) before RESUME (coordinator ~15:45: "bash -n plus a pre-flight or dry-run
... argument parsing, inputs present, OUTDIR refusal"). ab_heat_r5.py has no dry-run mode, so this runs the EXACT job
text in bash with two lines changed (exactly once each): PY becomes a shell function that records every call and
routes it here, and OUT moves under evidence/dry-r4a-r1/. No control, worker or heat call starts.

Usage: python -B dry_job_r4a.py            (driver; run under runq small --cores 1 --gib 1.1, so RUNQ_PRED_PEAK_GIB is
                                           the q10a booking, as `runq run` sets it)
Cases:
1. fresh dry job: exit 0, RESULT PASS; ab_heat_r5's real main() parses the arguments (its run() is replaced by
   dry_run below, which repeats run()'s steps up to the first launch: history load, spec parse, the real predict(),
   the start gate); every compare/check input outside OUT exists; call count 1 + 1 + 6.
2. the same dry job again: the job refuses its existing OUT (exit 5) and calls nothing.
3. the real ab_heat_r5.run() on an existing OUTDIR: FileExistsError before any arm (mkdir exist_ok=False).
4. the real compare_ab_r2.py on q03 arm-0 against itself: exit 0 (the observer-q03 compare's input loads).
Also: the real OUT (evidence/h1c-r4a) must not exist; the job file must be c0ffada4.
"""
import importlib.util
import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
HS = HERE.parent
JOB = HERE/'job_h1c_r4a.sh'
JOB_SHA = 'c0ffada40a4099d0'
DRY = HS/'evidence/dry-r4a-r2'
PY_LINE = 'PY="$T/.r44-env/Scripts/python.exe"\n'
OUT_LINE = 'OUT="$HS/evidence/h1c-r4a"\n'
STUB = '''REALPY="$T/.r44-env/Scripts/python.exe"
PY=drypy
drypy() { printf '%s\\n' "$*" >> "$DRYDIR/calls.log"; "$REALPY" -B "$DRYTOOL" stub "$OUT" "$@"; }
'''


class _NoLaunch:
    """Replaces ab_heat_r5's subprocess module: any launch raises."""
    @staticmethod
    def Popen(*args, **kwargs):
        raise RuntimeError('DRY: launch blocked')

    STDOUT = subprocess.STDOUT


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.subprocess = _NoLaunch
    return module


def dry_run(M, outdir, specs, history_files=(), pred_cli=None):
    """ab_heat_r5.run() up to its first Popen, without starting anything; then OUTDIR is created as run() does."""
    history = []
    for name in history_files:
        history += [(str(name), a) for a in json.loads(Path(name).read_text(encoding='utf8'))['arms']]
    print('DRY ab_heat_r5: history', [str(n) for n in history_files], len(history), 'records')
    arms = []
    for k, spec in enumerate(specs):
        mode, label, layout = spec.split(':', 2)
        if mode not in ('time', 'proof', 'prof'):
            raise SystemExit('mode must be time, proof or prof')
        arm = dict(arm=k, mode=mode, label=label, layout=str(Path(layout).resolve()))
        arms.append(arm)
        if not (Path(arm['layout'])/'control.json').is_file():
            raise SystemExit('DRY arm %d: no control.json in %s' % (k, arm['layout']))
        predicted, basis = M.predict(arm, history+[('this run', a) for a in arms[:-1]], pred_cli)
        if predicted is None:
            raise SystemExit('DRY arm %d refused: %s' % (k, basis))
        gate = (predicted*1.2+2)
        print('DRY arm %d %s %s %s: pred %.3f GiB (%s), start gate %.2f GiB, free now %.2f GiB' % (
            k, mode, label, Path(layout).name, predicted, basis, gate, M.psutil.virtual_memory().available/M.GIB))
    Path(outdir).mkdir(parents=True, exist_ok=False)
    (Path(outdir)/'DRY').write_text('dry run only; no arm ran\n', encoding='utf8')


def stub(out, args):
    """One "$PY" call of the job. args = ['-B', script, ...]."""
    assert args[0] == '-B', args
    script = Path(args[1])
    if not script.is_file():
        raise SystemExit('DRY missing script %s' % script)
    if script.name == 'ab_heat_r5.py':
        M = _module(script, 'ab_heat_r5')
        M.run = lambda outdir, specs, history_files=(), pred_cli=None: dry_run(M, outdir, specs, history_files, pred_cli)
        sys.argv = [str(script), *args[2:]]
        M.main()
        return
    if script.name == 'check_arms.py':
        assert args[2:] == [out, '5'], args
        print('DRY check_arms ok')
        return
    if script.name == 'compare_ab_r2.py':
        sides, roots = args[2:4], args[4:]
        assert len(sides) == 2 and len(roots) in (0, 2), args
        for side in sides:
            if side.startswith(out + '/arm-'):
                continue
            d = Path(side)
            if not ((d/'arrays.json').is_file() and d.with_name(d.name + '.json').is_file()):
                raise SystemExit('DRY compare input missing: %s' % side)
        for root in roots:
            if not (Path(root)/'control.json').is_file():
                raise SystemExit('DRY compare root has no control.json: %s' % root)
        print('DRY compare ok', [Path(s).name for s in sides], [Path(r).name for r in roots])
        return
    raise SystemExit('DRY unexpected call %s' % script)


def driver():
    report = []
    raw = JOB.read_bytes()
    assert sha256(raw).hexdigest().startswith(JOB_SHA), 'job file changed'
    assert not (HS/'evidence/h1c-r4a').exists(), 'real OUT exists'
    text = raw.decode('utf8')
    for line in (PY_LINE, OUT_LINE):
        assert text.count(line) == 1, line
    dry = text.replace(PY_LINE, STUB).replace(OUT_LINE, 'OUT="$DRYDIR/h1c-r4a"\n')
    DRY.mkdir(parents=True, exist_ok=False)
    (DRY/'job_dry.sh').write_bytes(dry.encode('utf8'))
    env = dict(os.environ, DRYDIR=DRY.as_posix(), DRYTOOL=Path(__file__).resolve().as_posix(), RUNQ_PRED_PEAK_GIB='1.1')
    print('RUNQ_PRED_PEAK_GIB =', env['RUNQ_PRED_PEAK_GIB'], '(set here as runq run sets it for q10a)')
    for case, expect in (('1 fresh', 0), ('2 OUT exists', 5)):
        before = (DRY/'calls.log').read_text(encoding='utf8').count('\n') if (DRY/'calls.log').exists() else 0
        done = subprocess.run([os.environ["DRYBASH"], str(DRY/"job_dry.sh")], env=env, capture_output=True, text=True)
        calls = (DRY/'calls.log').read_text(encoding='utf8').split('\n')[before:-1] if (DRY/'calls.log').exists() else []
        print('--- case %s: exit %d (expect %d), %d calls' % (case, done.returncode, expect, len(calls)))
        print(done.stdout.rstrip())
        if done.stderr.strip():
            print('stderr:', done.stderr.rstrip())
        ok = done.returncode == expect
        if expect == 0:
            kinds = [c.split()[1].rsplit('/', 1)[-1] for c in calls]
            ok = ok and kinds == ['ab_heat_r5.py', 'check_arms.py'] + ['compare_ab_r2.py']*6
            ok = ok and (DRY/'h1c-r4a/RESULT').read_text(encoding='utf8') == 'PASS\n'
        else:
            ok = ok and not calls and 'refusing to overwrite' in done.stdout
        report.append((case, ok))
    M = _module(HERE/'ab_heat_r5.py', 'ab_heat_r5_case3')
    if not (DRY/'h1c-r4a').is_dir():
        report.append(('3 harness OUTDIR refusal (not run: no OUTDIR)', False))
    else:
      try:
        M.run(DRY/'h1c-r4a', ['proof:base:%s' % (HS/'lw')], [HS/'evidence/h12-r1/summary.json'])
        report.append(('3 harness OUTDIR refusal', False))
      except FileExistsError as error:
        print('--- case 3: FileExistsError', error)
        report.append(('3 harness OUTDIR refusal', True))
    arm0 = HS/'evidence/h12-r1/arm-0'
    done = subprocess.run([sys.executable, '-B', str(HERE/'compare_ab_r2.py'), str(arm0), str(arm0)],
                          capture_output=True, text=True)
    print('--- case 4: compare q03 arm-0 vs itself exit %d: %s' % (done.returncode, done.stdout.strip().split('\n')[-1]))
    report.append(('4 compare loads q03 arm-0', done.returncode == 0))
    for case, ok in report:
        print('CASE', case, 'PASS' if ok else 'FAIL')
    print('DRY RESULT', 'PASS' if all(ok for _, ok in report) else 'FAIL')
    return 0 if all(ok for _, ok in report) else 1


if __name__ == '__main__':
    if sys.argv[1:2] == ['stub']:
        stub(sys.argv[2], sys.argv[3:])
    else:
        sys.exit(driver())
