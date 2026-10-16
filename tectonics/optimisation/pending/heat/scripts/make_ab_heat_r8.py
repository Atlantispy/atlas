"""Make harness ab_heat_r8.py, job_h1c_r4c_r2.sh and dry_job_r4c_r2.py (the hash-seed rule) as NEW files.

Usage: python -B make_ab_heat_r8.py SCRIPTS_DIR
Sources (pinned): ab_heat_r5.py 790be9283501, job_h1c_r4c.sh 5101699619aa, dry_job_r4c.py 01d1dda3bd3d.
Every edit is an exact-once replacement (a moved anchor refuses); outputs must not exist. Prints the new digests.
"""
from hashlib import sha256
from pathlib import Path
import sys

PINS = {'ab_heat_r5.py': '790be9283501', 'job_h1c_r4c.sh': '5101699619aa', 'dry_job_r4c.py': '01d1dda3bd3d'}


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit('anchor not found exactly once: %r' % old[:80])
    return text.replace(old, new)


def every(text, old, new, count):
    if text.count(old) != count:
        raise SystemExit('expected %d of %r, found %d' % (count, old, text.count(old)))
    return text.replace(old, new)


R8_DOC = r'''"""A/B harness r8 (T/hs): same-call heat control on the genuine W4 call, one fresh process per arm.

r8 (16 Oct) is r5 plus the hash-seed rule for every process that imports the runtime. The r6/r7 start-gate changes
are NOT in it: gates and history handling are r5's. Production needs string-hash seed 0 (parallel binding raises
without it; parallel selection falls back to serial under a random seed), and -I implies -E, which ignores
PYTHONHASHSEED, so a check of the environment alone is fail-open; sys.flags says what the interpreter did.
  - Every child (time, proof, prof) starts as python -B -s -P with a cleaned environment: no inherited PYTHON*
    variable, PYTHONHASHSEED=0, one BLAS/OpenMP thread; prof adds back only its PYTHONPATH (the worker profiler).
    Each arm records child_flags and the PYTHON* names removed.
  - Before any heat work the child refuses unless sys.flags shows seed 0, no user site, safe path and neither -E nor
    -I; unless its PYTHON* variables are exactly those; unless functionals_parallel_r1 still starts each worker as
    [sys.executable, '-B', <file>, 'worker'] with this environment plus OPENBLAS_NUM_THREADS (so the workers honour
    the same seed); and unless a probe started that same way reports seed 0. The result records it as
    ab.interpreter.
  - `python -B -s -P ab_heat_r8.py flags MODE LAYOUT` runs only that check (the dry run starts it).
Everything else is r5's.

'''

R8_FUNCS = r'''def _child_env(mode):
    """r8: a child's environment: nothing inherited that starts with PYTHON, seed 0, one BLAS/OpenMP thread."""
    removed = sorted(k for k in os.environ if k.upper().startswith('PYTHON'))
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('PYTHON')}
    env.update(PYTHONHASHSEED='0', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    if mode == 'prof':
        env['PYTHONPATH'] = str(HS/'workerprof')
    return env, removed


def _launch(mode, layout, outdir, k):
    """r8: (command, environment, removed PYTHON* names) of arm K's child."""
    env, removed = _child_env(mode)
    if mode == 'prof':
        env['HS_PROF_DIR'] = str((Path(outdir)/f'arm-{k}').resolve())
    command = [sys.executable, *CHILD_FLAGS, str(Path(__file__).resolve()), 'child', mode, str(layout),
               str(Path(outdir).resolve()), str(k)]
    return command, env, removed


def _interpreter(mode, PAR):
    """r8: refuse unless this child and the workers it starts have string-hash seed 0 (fail-closed: sys.flags)."""
    f = sys.flags
    if f.hash_randomization or not f.no_user_site or not f.safe_path or f.ignore_environment or f.isolated:
        raise SystemExit('child interpreter: hash_randomization=%d no_user_site=%d safe_path=%r ignore_environment=%d '
                         'isolated=%d' % (f.hash_randomization, f.no_user_site, f.safe_path, f.ignore_environment,
                                          f.isolated))
    present = {k.upper(): v for k, v in os.environ.items() if k.upper().startswith('PYTHON')}
    wanted = dict(PYTHONHASHSEED='0')
    if mode == 'prof':
        wanted['PYTHONPATH'] = str(HS/'workerprof')
    if present != wanted:
        raise SystemExit('child environment: PYTHON* variables %r, expected %r' % (sorted(present), sorted(wanted)))
    source = Path(PAR.__file__).read_text(encoding='utf8')
    if any(source.count(line) != 1 for line in WORKER_LAUNCH):
        raise SystemExit('functionals_parallel_r1 no longer starts its workers as r8 checks')
    probe = subprocess.run([sys.executable, '-B', '-c', 'import sys; print(sys.flags.hash_randomization)'],
                           env=dict(os.environ, OPENBLAS_NUM_THREADS='1'), capture_output=True, text=True, timeout=120)
    if probe.returncode or probe.stdout.strip() != '0':
        raise SystemExit('worker-style probe: seed not fixed (exit %d, %r)' % (probe.returncode, probe.stdout[-200:]))
    return dict(flags=list(CHILD_FLAGS), hash_randomization=f.hash_randomization, no_user_site=f.no_user_site,
                safe_path=f.safe_path, python_variables=sorted(present), worker_probe_hash_randomization=0)


def child(mode, layout, outdir, k):
'''


def harness(text):
    text = once(text, '"""A/B harness r5 (T/hs): same-call heat control on the genuine W4 call, one fresh process per arm.\n\n',
                R8_DOC)
    text = once(text, '  python -B ab_heat_r5.py run OUTDIR', '  python -B ab_heat_r8.py run OUTDIR')
    text = once(text, '  python -B ab_heat_r5.py child MODE LAYOUT OUTDIR K          (one arm; started by run)\n',
                '  python -B -s -P ab_heat_r8.py child MODE LAYOUT OUTDIR K    (one arm; started by run)\n'
                '  python -B -s -P ab_heat_r8.py flags MODE LAYOUT             (r8: the child\'s interpreter check only)\n')
    text = once(text, "WORKER_TAG = 'private_heat_functionals_parallel_r1.py'   # in every reconstruction worker's command line\n",
                "WORKER_TAG = 'private_heat_functionals_parallel_r1.py'   # in every reconstruction worker's command line\n"
                "CHILD_FLAGS = ('-B', '-s', '-P')   # r8: never -I/-E, which ignore PYTHONHASHSEED\n"
                "WORKER_LAUNCH = (\"environment = dict(os.environ, OPENBLAS_NUM_THREADS='1')\",\n"
                "                 \"command = [sys.executable, '-B', str(Path(__file__).resolve()), 'worker']\")\n")
    text = once(text, 'def child(mode, layout, outdir, k):\n', R8_FUNCS)
    text = once(text, "        raise SystemExit('functionals_parallel_r1 did not load from the layout')\n    workers = PAR.configure()\n",
                "        raise SystemExit('functionals_parallel_r1 did not load from the layout')\n"
                "    interpreter = _interpreter(mode, PAR)\n    workers = PAR.configure()\n")
    text = once(text, "    result['ab'] = dict(mode=mode, layout=str(layout), workers_configured=workers, calls=calls,\n",
                "    result['ab'] = dict(mode=mode, layout=str(layout), workers_configured=workers, calls=calls,\n"
                "                        interpreter=interpreter,\n")
    text = once(text, """        env = dict(os.environ, PYTHONHASHSEED='0', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
        if mode == 'prof':
            (outdir/f'arm-{k}').mkdir()
            env['HS_PROF_DIR'] = str((outdir/f'arm-{k}').resolve())
            env['PYTHONPATH'] = str(HS/'workerprof')
        command = [sys.executable, '-B', str(Path(__file__).resolve()), 'child', mode, arm['layout'],
                   str(outdir.resolve()), str(k)]
""", """        if mode == 'prof':
            (outdir/f'arm-{k}').mkdir()
        command, env, removed = _launch(mode, arm['layout'], outdir, k)
        arm.update(child_flags=list(CHILD_FLAGS), removed_python_variables=removed)
""")
    text = once(text, "        child(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))\n",
                "        child(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))\n"
                "    elif sys.argv[1] == 'flags':\n"
                "        sys.path[:0] = json.loads((Path(sys.argv[3]).resolve()/'control.json').read_text(encoding='utf8'))['paths']\n"
                "        import private_heat_functionals_parallel_r1 as PAR\n"
                "        print(json.dumps(_interpreter(sys.argv[2], PAR)), flush=True)\n")
    if 'ab_heat_r5' in text:
        raise SystemExit('an r5 name is left in r8')
    return text


def job(text, r8_sha):
    text = once(text, '# q10 split, part B, FULL symmetric order',
                '# r2 (16 Oct): job_h1c_r4c.sh on harness r8 (the hash-seed rule). Nothing else differs.\n'
                '# q10 split, part B, FULL symmetric order')
    text = once(text, '# Harness ab_heat_r5.py (790be928).',
                '# Harness ab_heat_r8.py (%s: r5 + the hash-seed rule; children -B -s -P, cleaned env, seed 0 checked\n'
                '# by sys.flags in the child and a worker-style probe).' % r8_sha[:8])
    text = once(text, '"$PY" -B "$HS/scripts/ab_heat_r5.py" run "$OUT"', '"$PY" -B "$HS/scripts/ab_heat_r8.py" run "$OUT"')
    if 'ab_heat_r5' in text:
        raise SystemExit('an r5 name is left in job r2')
    return text


CASE4 = r'''def interpreter_cases():
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
'''


def dry(text, job_sha):
    text = once(text, '"""Dry run of scripts/job_h1c_r4c.sh (q22, full ABBA)',
                '"""Dry run r2: dry_job_r4c.py on job_h1c_r4c_r2.sh (harness ab_heat_r8, the hash-seed rule), plus case 4,\n'
                'which starts the REAL r8 child launch in its \'flags\' mode (interpreter check only, no heat work). Below is\n'
                'r1\'s text with the names changed.\n\n'
                'Dry run of scripts/job_h1c_r4c_r2.sh (q22, full ABBA)')
    text = once(text, "JOB = HERE/'job_h1c_r4c.sh'\n", "JOB = HERE/'job_h1c_r4c_r2.sh'\n")
    text = every(text, '5101699619aa95ab', job_sha[:16], 2)
    text = once(text, "DRY = HS/'evidence/dry-r4c-r1'\n", "DRY = HS/'evidence/dry-r4c-r2'\n")
    n = text.count('ab_heat_r5')
    if n < 8:
        raise SystemExit('expected the r5 harness names in dry r1, found %d' % n)
    text = text.replace('ab_heat_r5', 'ab_heat_r8')
    text = once(text, 'def driver():\n', CASE4)
    text = once(text, "    for case, ok in report:\n        print('CASE', case, 'PASS' if ok else 'FAIL')\n",
                "    report += interpreter_cases()\n"
                "    for case, ok in report:\n        print('CASE', case, 'PASS' if ok else 'FAIL')\n")
    return text


def main():
    folder = Path(sys.argv[1])
    texts = {}
    for name, pin in PINS.items():
        raw = (folder/name).read_bytes()
        if not sha256(raw).hexdigest().startswith(pin) or b'\r' in raw:
            raise SystemExit('unexpected source %s' % name)
        texts[name] = raw.decode('utf8')
    made = {}
    made['ab_heat_r8.py'] = harness(texts['ab_heat_r5.py'])
    r8_sha = sha256(made['ab_heat_r8.py'].encode('utf8')).hexdigest()
    made['job_h1c_r4c_r2.sh'] = job(texts['job_h1c_r4c.sh'], r8_sha)
    job_sha = sha256(made['job_h1c_r4c_r2.sh'].encode('utf8')).hexdigest()
    made['dry_job_r4c_r2.py'] = dry(texts['dry_job_r4c.py'], job_sha)
    for name, text in made.items():
        if (folder/name).exists():
            raise SystemExit('%s exists' % name)
        if name.endswith('.py'):
            compile(text, name, 'exec')
    for name, text in made.items():
        data = text.encode('utf8')
        (folder/name).write_bytes(data)
        print(name, sha256(data).hexdigest())


if __name__ == '__main__':
    main()
