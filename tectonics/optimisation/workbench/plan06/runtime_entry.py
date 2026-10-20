"""Seed-zero entry for unchanged runtime-importing proof scripts."""
import os
import runpy
import sys
from pathlib import Path

if os.environ.get('PYTHONHASHSEED') != '0' or sys.flags.hash_randomization or sys.flags.isolated:
    raise SystemExit('runtime proof requires seed 0 and non-isolated Python')
bytecode = os.environ.get('PYTHONDONTWRITEBYTECODE')
if bytecode is not None and (bytecode != '1' or not sys.dont_write_bytecode):
    raise SystemExit('unexpected bytecode setting')
if any(k.startswith('PYTHON') and k not in ('PYTHONHASHSEED', 'PYTHONDONTWRITEBYTECODE')
       for k in os.environ):
    raise SystemExit('unexpected PYTHON environment variable')
target = Path(sys.argv[1]).resolve()
sys.argv = [str(target), *sys.argv[2:]]
sys.path.insert(0, str(target.parent))
runpy.run_path(str(target), run_name='__main__')
