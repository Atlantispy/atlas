"""Before-copies of start_gate.py and test_start_gate.py as accepted (4aadef45, 60d061da), rebuilt from the live files.

The route (1) helpers were appended to both live files before their before-copies were taken (16 Oct 2026, ~18:40).
Nothing loads start_gate yet, so no run saw either version. This rebuilds each accepted version by removing exactly
the added text, and writes a before-copy only if the result's SHA-256 is the accepted one; otherwise it writes
nothing and says so. Usage: python -B make_gate_before_copies.py   (writes only R/probes/step8/claude-20261015/before-src)
"""
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESUMABILITY = HERE.parents[2]
BEFORE = RESUMABILITY/'probes'/'step8'/'claude-20261015'/'before-src'
ACCEPTED = {'start_gate.py': '4aadef45', 'test_start_gate.py': '60d061da'}


def cut(text, start, end, keep):
    """Replace the one span from ``start`` up to and including ``end`` with ``keep``."""
    assert text.count(start) == 1, start
    head, tail = text.split(start, 1)
    assert tail.count(end) == 1, end
    return head + keep + tail.split(end, 1)[1]


def gate(text):
    text = cut(text, '\n\nRoute (1) (launch_fresh_interval', 'holding that gate.\n"""', '\n"""')
    old = 'import json\nimport sys\nfrom hashlib import sha256\nfrom pathlib import Path\n'
    assert text.count(old) == 1
    text = text.replace(old, 'import sys\n')
    assert text.count('\n\n\nSTAGE_SCHEMA = ') == 1
    return text.split('\n\n\nSTAGE_SCHEMA = ', 1)[0] + '\n'


def tests(text):
    old = ('import argparse\nimport json\nimport tempfile\nfrom hashlib import sha256\nfrom pathlib import Path\n'
           'from types import SimpleNamespace\n')
    assert text.count(old) == 1
    text = text.replace(old, 'from types import SimpleNamespace\n')
    old = 'import start_gate as G\n\nHERE = Path(__file__).resolve().parent\n\n'
    assert text.count(old) == 1
    text = text.replace(old, 'import start_gate as G\n\n')
    return cut(text, '\n\ndef stage_record(', "\n\nif __name__ == '__main__':", "\n\nif __name__ == '__main__':")


def main():
    failed = 0
    for name, rebuild in (('start_gate.py', gate), ('test_start_gate.py', tests)):
        live = (RESUMABILITY/name).read_bytes()
        text = rebuild(live.decode('utf8'))
        raw = text.encode('utf8')
        digest = sha256(raw).hexdigest()
        target = BEFORE/(name+'.before-wiring')
        if not digest.startswith(ACCEPTED[name]):
            failed += 1
            print(name, 'REBUILD DIFFERS: %s, accepted %s; nothing written' % (digest[:16], ACCEPTED[name]))
            continue
        if target.exists():
            print(name, 'before-copy exists:', sha256(target.read_bytes()).hexdigest()[:16])
            failed += sha256(target.read_bytes()).hexdigest() != digest
            continue
        with open(target, 'xb') as stream:
            stream.write(raw)
        print(name, 'live', sha256(live).hexdigest()[:16], '-> before-copy', digest[:16], target.name)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
