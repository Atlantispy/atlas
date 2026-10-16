"""Run sens.py and micro.py against each mutant in T/ps/refute/p3/mutants (sequential subprocesses)."""
import subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
PY = sys.executable
for mutant in sorted((HERE/'mutants').glob('*.py')):
    for script in ('sens.py', 'micro.py'):
        out = subprocess.run([PY, '-B', str(HERE/script), str(mutant)], capture_output=True, text=True)
        lines = [l for l in out.stdout.splitlines() if l.startswith(('SENS', 'MICRO', 'VALUE/TYPE', 'IDENTITY-ONLY: _mul', 'IDENTITY-ONLY: _scale'))]
        print(mutant.stem, script, 'exit', out.returncode, '|', ' || '.join(lines)[:500], (out.stderr.strip().splitlines() or [''])[-1][:200], flush=True)
