"""Dry run r2: dry_job_r4c.py on job_h1c_r4c_r2.sh (harness ab_heat_r8, the hash-seed rule), plus case 4,
which starts the REAL r8 child launch in its 'flags' mode (interpreter check only, no heat work). Below is
r1's text with the names changed.

Dry run of scripts/job_h1c_r4c_r2.sh (q22, full ABBA) before it is queued (coordinator ~15:50: "dry r2 PASS on r4c
itself"). Generated from dry_job_r4a_r2.py (5f42c3f9) by an exact-once generator; the launch block is unchanged: every
loaded ab_heat_r8 module gets a subprocess whose Popen raises, so no control, worker or heat call can start.
The EXACT job text runs in bash with three lines changed (exactly once each): PY becomes a shell function that records
every call and routes it here; A (part A's output) moves to evidence/dry-r4c-r1/a; OUT moves to evidence/dry-r4c-r1/.
The driver sets RUNQ_PRED_PEAK_GIB=1.1 as `runq run` does for the ticket.

Usage: python -B dry_job_r4c.py            (driver; run under runq small --cores 1)
Cases:
0. part A has no RESULT: the job refuses (exit 4) and calls nothing.
1. part A RESULT = PASS, its summary.json = the real lw proof record of evidence/dry-r4a-r1 (so --history loads a
   part-A-shaped file): exit 0; ab_heat_r8's real main() parses the 11 arm specs and options (run() replaced by
   dry_run: history load, spec parse, every layout's control.json, the real predict(), the start gate); then
   check_arms with OUT and 11. Calls: ab_heat_r8 once, check_arms once.
2. the same dry job again: the job refuses its existing OUT (exit 5) and calls nothing.
3. the real ab_heat_r8.run() on the existing dry OUTDIR: FileExistsError before any arm (only if that OUTDIR exists).
Also: the real OUT (evidence/h1c-r4c) must not exist; the job file must be 12fa7955e8fd9926.
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
JOB = HERE/'job_h1c_r4c_r2.sh'
JOB_SHA = '12fa7955e8fd9926'
DRY = HS/'evidence/dry-r4c-r2'
N_ARMS = 11
PART_A_RECORD = HS/'evidence/dry-r4a-r1/h1c-r4a/summary.json'   # the real lw proof arm of 15:42-15:44
PY_LINE = 'PY="$T/.r44-env/Scripts/python.exe"\n'
OUT_LINE = 'OUT="$HS/evidence/h1c-r4c"\n'
A_LINE = 'A="$HS/evidence/h1c-r4a"\n'
STUB = '''REALPY="$T/.r44-env/Scripts/python.exe"
PY=drypy
drypy() { printf '%s\\n' "$*" >> "$DRYDIR/calls.log"; "$REALPY" -B "$DRYTOOL" stub "$OUT" "$@"; }
'''


class _NoLaunch:
    """Replaces ab_heat_r8's subprocess module: any launch raises."""
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
    """ab_heat_r8.run() up to its first Popen, without starting anything; then OUTDIR is created as run() does."""
    history = []
    for name in history_files:
        history += [(str(name), a) for a in json.loads(Path(name).read_text(encoding='utf8'))['arms']]
    print('DRY ab_heat_r8: history', [str(n) for n in history_files], len(history), 'records')
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
    if script.name == 'ab_heat_r8.py':
        M = _module(script, 'ab_heat_r8')
        M.run = lambda outdir, specs, history_files=(), pred_cli=None: dry_run(M, outdir, specs, history_files, pred_cli)
        sys.argv = [str(script), *args[2:]]
        M.main()
        return
    if script.name == 'check_arms.py':
        assert args[2:] == [out, str(N_ARMS)], args
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


def interpreter_cases():
    """Case 4 (r2): the REAL r8 child launch (command and environment from ab_heat_r8._launch) in its 'flags' mode.

    4a-c: time, prof and proof children on layout lh pass r8's interpreter check (seed 0 by sys.flags, no user site,
    safe path, exactly the expected PYTHON* variables, the worker launch lines, a worker-style probe with seed 0).
    4d-g must each refuse: PYTHONHASHSEED removed; -I added (it ignores the variable); an extra PYTHONUTF8; -s and -P
    dropped. No heat work runs: 'flags' imports only functionals_parallel_r1.
    """
    M = _module(HERE/'ab_heat_r8.py', 'ab_heat_r8_case4')
    layout, out, results = HS/'lh', DRY/'flags', []
    for k, mode in enumerate(('time', 'prof', 'proof')):
        command, env, removed = M._launch(mode, layout, out, k)
        argv = command[:command.index('child')] + ['flags', mode, str(layout)]
        done = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=300)
        try:
            seen = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            seen = None
        ok = (done.returncode == 0 and seen is not None and command[1:4] == ['-B', '-s', '-P']
              and seen['hash_randomization'] == 0 and seen['worker_probe_hash_randomization'] == 0
              and seen['no_user_site'] == 1 and seen['safe_path'] is True)
        print('--- case 4%s %s: exit %d, removed %s, %s %s' % ('abc'[k], mode, done.returncode, removed, seen,
                                                           done.stderr.strip()[-300:]))
        results.append(('4%s %s child passes the interpreter check' % ('abc'[k], mode), ok))
    command, env, _ = M._launch('time', layout, out, 0)
    base = command[:command.index('child')] + ['flags', 'time', str(layout)]
    no_seed = {k: v for k, v in env.items() if k != 'PYTHONHASHSEED'}
    for name, argv, environment, expect in (
            ('4d no PYTHONHASHSEED', base, no_seed, 'set PYTHONHASHSEED=0'),
            ('4e -I added', [base[0], '-I', *base[1:]], env, 'set PYTHONHASHSEED=0'),
            ('4f extra PYTHONUTF8', base, dict(env, PYTHONUTF8='1'), 'child environment'),
            ('4g -s -P dropped', [x for x in base if x not in ('-s', '-P')], env, 'child interpreter')):
        done = subprocess.run(argv, env=environment, capture_output=True, text=True, timeout=300)
        said = (done.stdout + done.stderr).strip()
        print('--- case %s: exit %d, %s' % (name, done.returncode, said[-200:]))
        results.append((name + ' refuses', done.returncode != 0 and expect in said))
    return results


def driver():
    report = []
    raw = JOB.read_bytes()
    assert sha256(raw).hexdigest().startswith(JOB_SHA), 'job file changed'
    assert not (HS/'evidence/h1c-r4c').exists(), 'real OUT exists'
    text = raw.decode('utf8')
    for line in (PY_LINE, OUT_LINE, A_LINE):
        assert text.count(line) == 1, line
    dry = text.replace(PY_LINE, STUB).replace(OUT_LINE, 'OUT="$DRYDIR/h1c-r4c"\n').replace(
        A_LINE, 'A="$DRYDIR/a"\n')
    DRY.mkdir(parents=True, exist_ok=False)
    (DRY/'job_dry.sh').write_bytes(dry.encode('utf8'))
    env = dict(os.environ, DRYDIR=DRY.as_posix(), DRYTOOL=Path(__file__).resolve().as_posix(), RUNQ_PRED_PEAK_GIB='1.1')
    print('RUNQ_PRED_PEAK_GIB =', env['RUNQ_PRED_PEAK_GIB'], '(set here as runq run sets it for the ticket)')
    for case, expect in (('0 part A not passed', 4), ('1 fresh', 0), ('2 OUT exists', 5)):
        if case.startswith('1'):
            (DRY/'a').mkdir()
            (DRY/'a/RESULT').write_bytes(b'PASS\n')
            (DRY/'a/summary.json').write_bytes(PART_A_RECORD.read_bytes())
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
            ok = ok and kinds == ['ab_heat_r8.py', 'check_arms.py'] and (DRY/'h1c-r4c/DRY').is_file()
            ok = ok and (DRY/'h1c-r4c/check-arms.txt').read_text(encoding='utf8') == 'DRY check_arms ok\n'
        else:
            ok = ok and not calls and ('refusing to overwrite' if expect == 5 else 'part A has not passed') \
                in done.stdout
        report.append((case, ok))
    M = _module(HERE/'ab_heat_r8.py', 'ab_heat_r8_case3')
    if not (DRY/'h1c-r4c').is_dir():
        report.append(('3 harness OUTDIR refusal (not run: no OUTDIR)', False))
    else:
      try:
        M.run(DRY/'h1c-r4c', ['proof:base:%s' % (HS/'lw')], [HS/'evidence/h12-r1/summary.json'])
        report.append(('3 harness OUTDIR refusal', False))
      except FileExistsError as error:
        print('--- case 3: FileExistsError', error)
        report.append(('3 harness OUTDIR refusal', True))
    report += interpreter_cases()
    for case, ok in report:
        print('CASE', case, 'PASS' if ok else 'FAIL')
    print('DRY RESULT', 'PASS' if all(ok for _, ok in report) else 'FAIL')
    return 0 if all(ok for _, ok in report) else 1


if __name__ == '__main__':
    if sys.argv[1:2] == ['stub']:
        stub(sys.argv[2], sys.argv[3:])
    else:
        sys.exit(driver())
