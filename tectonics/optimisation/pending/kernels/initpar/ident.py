"""Print the reference ExecutionContext identity of a native tree, as the admission harness would see it.

Usage: python -B ident.py NATIVE_ROOT IMPORT_ROOT [IMPORT_ROOT ...]   (PYTHONHASHSEED=0)
Same sys.path order as time_admission_parts.py / test_initpar.py. Read-only.
"""
import sys
from pathlib import Path

if sys.flags.hash_randomization:
    raise SystemExit('set PYTHONHASHSEED=0')
native, roots = Path(sys.argv[1]).resolve(), [Path(p).resolve() for p in sys.argv[2:]]
sys.path[:0] = [str(native), *map(str, roots)]
import atlas_tectonics  # noqa: E402
if not Path(atlas_tectonics.__file__).resolve().is_relative_to(native):
    raise SystemExit('atlas_tectonics did not load from the native root')
from atlas_tectonics.reuse import ExecutionContext, require_strict_execution  # noqa: E402
require_strict_execution()
with ExecutionContext('reference') as reference:
    print(reference.identity)
