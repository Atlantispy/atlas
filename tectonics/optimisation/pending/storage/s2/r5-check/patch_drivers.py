"""S2 r5 local check only: insert the two route-check lines into Runner's current drivers (sha-checked).

Writes r5-check/drivers/*.py (NOT FOR APPLICATION: Runner applies the lines on his own SHAs) and
r5/driver-lines.diff (the exact lines and placement, as text for the integration note).
"""
import difflib
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/'
         'continuation-repair-20261013/optimisation-20261014/resumability-r1')
IMPORT = '    from compact_restart_patch import require_capture_route\n'
EDITS = {
    'fresh_interval_driver.py': ('f328f314', '''    ``measurements``: see admission.
    """
    _seed_pinned()
    stages = _stages(m)
''', '''    ``measurements``: see admission.
    """
'''+IMPORT+'''    require_capture_route(store)
    _seed_pinned()
    stages = _stages(m)
'''),
    'prepared_interval_driver.py': ('c4f5c4fb', '''    _require(duration == first_duration,
             'frozen initial workload duration differs from the authenticated first interval')
''', '''    _require(duration == first_duration,
             'frozen initial workload duration differs from the authenticated first interval')
'''+IMPORT+'''    require_capture_route(workflow._store)
'''),
}


def main():
    out, diff = HERE/'drivers', []
    out.mkdir(exist_ok=False)
    (out/'NOT-FOR-APPLICATION.txt').write_text('Local S2 r5 wiring check only. Runner applies the lines in '
                                                'r5/driver-lines.diff on his own driver SHAs.\n', encoding='utf8')
    for name, (short, old, new) in EDITS.items():
        data = (R/name).read_bytes()
        if hashlib.sha256(data).hexdigest()[:8] != short:
            raise SystemExit('%s is not %s: refusing' % (name, short))
        text = data.decode('utf8')
        if text.count(old) != 1:
            raise SystemExit('%s: seam found %d times' % (name, text.count(old)))
        patched = text.replace(old, new)
        compile(patched, name, 'exec')
        (out/name).write_bytes(patched.encode('utf8'))
        diff += difflib.unified_diff(text.splitlines(True), patched.splitlines(True),
                                     'R/%s (%s)' % (name, short), 'R/%s + S2 route check' % name)
        print(name, short, '->', hashlib.sha256(patched.encode('utf8')).hexdigest()[:8], '(local check only)')
    (HERE.parent/'r5'/'driver-lines.diff').write_text(''.join(diff), encoding='utf8', newline='\n')


if __name__ == '__main__':
    sys.exit(main())
