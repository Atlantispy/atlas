"""Step 10 fresh-process import test over a frozen composition (coordinator, 16 Oct ~11:20).

Usage: python -B -I import_every_module.py COMPOSED_ROOT H_TESTS OUT.json

Run in a FRESH process with -I (no PYTHONPATH, no user site, no script folder on sys.path) and
PYTHONHASHSEED=0. sys.path gets exactly the frozen roots: COMPOSED_ROOT/src (native root),
COMPOSED_ROOT/helpers, H_TESTS. Imports every module of the composed atlas_tectonics package and
every non-test helper module, one by one, and records failures. Afterwards every loaded module
whose file is not in the standard library or site-packages must lie under one of the frozen
roots: nothing may fall through to live R/C or any other folder. Exit 1 on any failure.
"""
import importlib
import json
import os
from pathlib import Path
import sys
import sysconfig
import traceback


def main():
    root, h_tests, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3])
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise SystemExit('PYTHONHASHSEED=0 required')
    src, helpers = root / 'src', root / 'helpers'
    sys.path[:0] = [str(src), str(helpers), str(h_tests)]
    sys.dont_write_bytecode = True
    names = []
    for path in sorted((src / 'atlas_tectonics').rglob('*.py')):
        parts = path.relative_to(src).with_suffix('').parts
        names.append('.'.join(parts[:-1]) if parts[-1] == '__init__' else '.'.join(parts))
    names += [p.stem for p in sorted(helpers.glob('*.py')) if not p.stem.startswith('test_')]
    failures = []
    for name in names:
        try:
            importlib.import_module(name)
        except BaseException as error:  # noqa: BLE001 - every failure is recorded, nothing is swallowed silently
            failures.append(dict(module=name, error=f'{type(error).__name__}: {str(error)[:300]}',
                                 where=traceback.format_exception(error)[-2].strip()[:300]))
    allowed = [Path(sysconfig.get_paths()[k]).resolve() for k in ('stdlib', 'platstdlib', 'purelib', 'platlib')]
    allowed.append((Path(sys.base_prefix) / 'DLLs').resolve())   # the interpreter's own extension modules
    frozen = [src, helpers, h_tests]
    outside = []
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if not path or name in ('__main__', '__mp_main__'):
            continue
        resolved = Path(path).resolve()
        if any(resolved.is_relative_to(base) for base in frozen + allowed):
            continue
        outside.append(dict(module=name, file=str(resolved)))
    result = dict(root=str(root), modules_attempted=len(names), failures=failures, loaded_outside_roots=outside,
                  loaded_total=len(sys.modules))
    out.write_text(json.dumps(result, indent=1) + '\n', encoding='utf8')
    print(json.dumps(dict(modules_attempted=len(names), failures=len(failures), loaded_outside_roots=len(outside),
                          loaded_total=len(sys.modules)), indent=1))
    for row in failures[:30]:
        print('FAIL', row['module'], '|', row['error'][:200])
    for row in outside[:20]:
        print('OUTSIDE', row['module'], row['file'])
    if failures or outside:
        raise SystemExit(1)
    print('import-every-module-pass')


if __name__ == '__main__':
    main()
