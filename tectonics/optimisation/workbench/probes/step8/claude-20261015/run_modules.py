"""Run each unittest module in its own fresh process (as the baseline did).

Usage: python -B run_modules.py OUT.json SECONDS_PER_MODULE module [module ...]
Writes per-module command, exit code, pass/fail/error/skip counts, wall time
and the tail of any failing output. Several suites refuse to share a process
(they patch or compose runtime sources), so isolation is part of the method.
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
C = os.path.join(R, 'compact-geometry-r1')
WATCHDOG = os.path.join(HERE, 'run_test_watchdog.py')


def main():
    out, seconds, modules = sys.argv[1], sys.argv[2], sys.argv[3:]
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
    rows = []
    for module in modules:
        started = time.perf_counter()
        child = subprocess.run([sys.executable, '-B', WATCHDOG, seconds, module], cwd=C, env=env,
                               capture_output=True, text=True, encoding='utf-8', errors='replace')
        wall = time.perf_counter()-started
        text = child.stdout+'\n'+child.stderr
        ran = re.search(r'Ran (\d+) tests? in ([0-9.]+)s', text)
        summary = re.search(r'\n(OK|FAILED)( \(([^)]*)\))?', text)
        counts = dict(re.findall(r'(failures|errors|skipped|expected failures)=(\d+)', summary.group(3) or '')) if summary else {}
        row = dict(module=module, exit=child.returncode, ran=int(ran.group(1)) if ran else None,
                   unittest_seconds=float(ran.group(2)) if ran else None, wall_seconds=round(wall, 3),
                   status=summary.group(1) if summary else 'NO-SUMMARY',
                   failures=int(counts.get('failures', 0)), errors=int(counts.get('errors', 0)),
                   skipped=int(counts.get('skipped', 0)))
        if child.returncode != 0:
            lines = [l for l in text.splitlines() if 'PermissionError' not in l and '_rmtree' not in l]
            row['tail'] = '\n'.join(lines[-80:])
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != 'tail'}), flush=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(dict(python=sys.executable, cwd=C, modules=rows), f, indent=1)
    return 0 if all(r['exit'] == 0 for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
