"""Relocated copy of the owner's test_run_fresh_interval.py: imports F from its own folder, owner tree read-only."""
import sys
from pathlib import Path

R = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
source, target = Path(R)/'test_run_fresh_interval.py', Path(sys.argv[1])
s = source.read_bytes().decode('utf8')
edits = [
    ("HERE = Path(__file__).resolve().parent\nCOMPACT = HERE/'compact-geometry-r1'\nRUNTIME = HERE.parent/'runtime-integration-r1'/'runtime-src'\nsys.path[:0] = [str(COMPACT), str(RUNTIME), str(HERE)]\n",
     "HERE = Path(__file__).resolve().parent\nROOT = Path('"+R+"')  # SO: relocated copy\nWORKSPACE = Path(os.path.commonpath([HERE, ROOT]))\nCOMPACT = ROOT/'compact-geometry-r1'\nRUNTIME = ROOT.parent/'runtime-integration-r1'/'runtime-src'\nsys.path[:0] = [str(HERE), str(COMPACT), str(RUNTIME), str(ROOT)]\n"),
    ("WP17_PACKAGE = (HERE.parents[2]/", "WP17_PACKAGE = (ROOT.parents[2]/"),
    ("Path(name).resolve().parent == HERE:", "Path(name).resolve().parent in (HERE, ROOT):"),
    ("'workspace': str(HERE),", "'workspace': str(WORKSPACE),"),
    ("relative_to(HERE).as_posix()", "relative_to(WORKSPACE).as_posix()"),
    ("(HERE/'fresh_interval_driver.py')", "(ROOT/'fresh_interval_driver.py')"),
]
for old, new in edits:
    if s.count(old) != 1:
        raise SystemExit('seam count %d: %r' % (s.count(old), old[:60]))
    s = s.replace(old, new)
target.write_bytes(s.encode('utf8'))
print('relocated', target)
