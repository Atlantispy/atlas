"""Fail-closed check of an ab_heat(_r2) run's summary.json (16 Oct, "review before you queue").

Usage: python -B check_arms.py OUTDIR EXPECTED_ARM_COUNT
Every expected arm must be present and completed: status PASS, no leaks, nothing stopped, exit
code 0, and on both heat calls 6 workers used, with no fallback (the CPU gate silently runs
serial on a loaded machine, which would spoil a timing). Prints one line per arm and exits
non-zero on any failure.
"""
import json
import sys
from pathlib import Path

out, expected = Path(sys.argv[1]), int(sys.argv[2])
arms = json.loads((out/'summary.json').read_text(encoding='utf8'))['arms']
bad = 0 if len(arms) == expected else 1
if bad:
    print('ARM COUNT', len(arms), 'expected', expected)
for a in arms:
    ok = (a.get('status') == 'PASS' and a.get('leaks') == 0 and 'stopped' not in a and a.get('exit_code') == 0
          and a.get('used') == [6, 6] and a.get('fallback') == [None, None])
    bad += not ok
    print(a.get('arm'), a.get('mode'), a.get('label'), 'OK' if ok else 'FAIL',
          {k: a.get(k) for k in ('status', 'leaks', 'stopped', 'exit_code', 'used', 'fallback', 'arm_wall_seconds')})
print('ARMS PASS' if not bad else 'ARMS FAIL %d' % bad)
sys.exit(1 if bad else 0)
