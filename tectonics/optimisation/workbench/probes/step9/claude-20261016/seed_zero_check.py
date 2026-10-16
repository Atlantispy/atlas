"""Fail-closed seed check for the shells that start runtime-importing children (coordinator seed rule, 16 Oct 2026).

Production requires seed 0: parallel_binding raises without it, and parallel_selection silently falls back to
serial under a random seed. So every process that imports the runtime (parity, proof and timing) runs with
PYTHONHASHSEED=0 and without -I or -E, which would make the interpreter ignore that variable.

Run this with the same interpreter, flags and environment as those children, before starting them. It exits 0
only when hash randomisation is off and the environment holds no PYTHON* variable other than PYTHONHASHSEED=0
and PYTHONDONTWRITEBYTECODE (the same as -B). It imports nothing from the runtime.
"""
import os
import sys

ALLOWED = {'PYTHONHASHSEED', 'PYTHONDONTWRITEBYTECODE'}


def problems():
    found = []
    if sys.flags.hash_randomization != 0:
        found.append('hash randomisation is on (sys.flags.hash_randomization=%d)' % sys.flags.hash_randomization)
    if sys.flags.ignore_environment or sys.flags.isolated:
        found.append('-E or -I makes the interpreter ignore PYTHONHASHSEED')
    if os.environ.get('PYTHONHASHSEED') != '0':
        found.append('PYTHONHASHSEED is %r, not 0' % os.environ.get('PYTHONHASHSEED'))
    extra = sorted(name for name in os.environ if name.upper().startswith('PYTHON') and name.upper() not in ALLOWED)
    if extra:
        found.append('environment not cleaned: ' + ', '.join(extra))
    return found


if __name__ == '__main__':
    found = problems()
    if found:
        sys.exit('SEED CHECK REFUSED: ' + '; '.join(found))
    print('seed check: hash_randomization=0, PYTHONHASHSEED=0, no other PYTHON* variable')
