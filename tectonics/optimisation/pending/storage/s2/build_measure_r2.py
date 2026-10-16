"""q15 harness revision 2: measure_s2.py (895c687d) -> measure_s2_r2.py (new file).

- Every process that imports the runtime runs with the string-hash seed 0: the harness refuses unless
  sys.flags.hash_randomization == 0 (no -I or -E; PYTHONHASHSEED=0), before any runtime import, and records it.
- The candidate is the final S2 revision (s2/r9: compact_restart_patch, ledger_fresh_interval); the loaded
  files and their sha256 are recorded.
- Roots come from this file's place, not absolute paths.
Timed region, arms, order and control are unchanged.
"""
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLD, NEW = HERE/'measure_s2.py', HERE/'measure_s2_r2.py'
EDITS = [
    ('"""S2 (WP16) before/after on the r9 IV1 pre-advance operands, same input, one process.\n',
     '"""S2 (WP16) before/after on the r9 IV1 pre-advance operands, same input, one process (harness r2).\n\n'
     'r2: refuses unless the string-hash seed is 0 (no -I or -E, PYTHONHASHSEED=0); the candidate is s2/r9;\n'
     'roots come from this file\'s place; the summary records the seed flag and the loaded files\' sha256.\n'),
    ("from pathlib import Path\n\nHERE = Path(__file__).resolve().parent\n",
     "from pathlib import Path\n\n"
     "if sys.flags.hash_randomization != 0:\n"
     "    raise SystemExit('refusing: the string-hash seed is not 0 (run without -I or -E, with PYTHONHASHSEED=0)')\n"
     "HERE = Path(__file__).resolve().parent\n"
     "T = HERE.parents[1]\n"),
    ("R = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/'\n"
     "         'continuation-repair-20261013/optimisation-20261014/resumability-r1')\n",
     "R = T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'\n"),
    ("R9 = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/'\n"
     "          'heat-repair-20261007')\n",
     "R9 = T/'fidelity-integration-20261005/heat-repair-20261007'\n"),
    ("sys.path[:0] = [str(HERE), ", "sys.path[:0] = [str(HERE/'r9'), "),
    ("import compact_restart_patch as CRP  # noqa: E402  (candidate copy in s2)\n"
     "import ledger_fresh_interval as LG  # noqa: E402  (candidate copy in s2)\n",
     "import compact_restart_patch as CRP  # noqa: E402  (candidate s2/r9)\n"
     "import ledger_fresh_interval as LG  # noqa: E402  (candidate s2/r9)\n"),
    ("        'pid': os.getpid(), 'hashseed': os.environ.get('PYTHONHASHSEED')}\n",
     "        'pid': os.getpid(), 'hashseed': os.environ.get('PYTHONHASHSEED'),\n"
     "        'hash_randomization': sys.flags.hash_randomization,\n"
     "        'loaded': {m.__name__: [m.__file__, sha256(Path(m.__file__).read_bytes()).hexdigest()] for m in (CRP, LG)}}\n"),
]


def main():
    if NEW.exists():
        sys.exit('measure_s2_r2.py exists')
    text = OLD.read_text(encoding='utf8')
    for old, new in EDITS:
        if text.count(old) != 1:
            sys.exit('seam count %d: %r' % (text.count(old), old[:70]))
        text = text.replace(old, new)
    compile(text, 'measure_s2_r2', 'exec')
    NEW.write_text(text, encoding='utf8', newline='\n')
    print(hashlib.sha256(OLD.read_bytes()).hexdigest()[:8], OLD.name, '->', hashlib.sha256(NEW.read_bytes()).hexdigest()[:8], NEW.name)


if __name__ == '__main__':
    main()
