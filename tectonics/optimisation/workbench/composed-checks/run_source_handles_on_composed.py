"""Run the geometry chat's test_source_handles.py against a COMPOSED tree (unchanged script).

Usage: python -B run_source_handles_on_composed.py HELPERS_DIR -- <test_source_handles args>

test_source_handles.py's import roots (EXTRA) name RC1's composed-r1 helpers. After the
Step 8 STAGES the composed package imports Step 8 helper modules (live_collar_patch etc.),
which live in the composed tree's helpers/. This loads the script by path, puts HELPERS_DIR
first in its EXTRA (its child processes read EXTRA at call time), and runs its main() with
the remaining arguments. The script file itself is not modified.
"""
import importlib.util
from pathlib import Path
import sys

SCRIPT = Path(r'C:\Users\LOCAL_USER\Documents\Codex\2026-09-02\the-diadem-local-tasks-10\fidelity-integration-20261005'
              r'\continuation-repair-20261013\optimisation-20261014\resumability-r1\geometry-growth-r1\scripts'
              r'\test_source_handles.py')


def main():
    helpers = str(Path(sys.argv[1]).resolve())
    if sys.argv[2] != '--':
        raise SystemExit('usage: HELPERS_DIR -- <test args>')
    spec = importlib.util.spec_from_file_location('test_source_handles', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.argv = [str(SCRIPT), *sys.argv[3:]]
    spec.loader.exec_module(module)
    module.EXTRA[:0] = [helpers]
    module.main()


if __name__ == '__main__':
    main()
