"""Attribute test_segment_store's fresh-process reader failure to a source set.

Usage: python -B repro_segment_child.py OUT.json
Runs test_codec_sealed_chain_fresh_process_roundtrip once. The test's parent
part (pack, publish, promote) runs unchanged; when it launches its fresh child
reader, the child is run twice on the same catalog: with the test's own
PYTHONPATH (current C first) and with premerge-wave1/ placed first (record
views and tables as before review wave 1). Each child's exit code and stderr
tail are recorded, and the live owners left at scope.close() are listed by
running the same child code with a diagnostic epilogue. Nothing in C changes.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
PREMERGE = HERE/'premerge-wave1'
DIAGNOSE = '''
import content_cache as _CC
_scope = scope
_rows = []
for name in dir(_scope):
    if name.startswith('_') and not name.startswith('__'):
        value = getattr(_scope, name, None)
        if isinstance(value, (dict, list, set)) and len(value) and len(value) < 10000:
            _rows.append((name, len(value), repr(list(value)[:6])[:600]))
print(json.dumps(dict(diagnostic=_rows, reserved=budget.reserved_bytes,
                      statistics=getattr(budget, 'statistics', lambda: None)())), file=sys.stderr)
'''


def main():
    out = Path(sys.argv[1])
    sys.path[:0] = [str(C), str(R.parent/'runtime-integration-r1'/'runtime-src'), str(R)]
    import test_segment_store as TSS
    runs = []
    real_run = subprocess.run

    def patched(command, **kwargs):
        code, catalog = command[3], command[4]
        env = dict(kwargs['env'])
        variants = [('current', env['PYTHONPATH']),
                    ('premerge-wave1', os.pathsep.join((str(PREMERGE), env['PYTHONPATH'])))]
        first = None
        for label, path in variants:
            child = real_run(command, **dict(kwargs, env=dict(env, PYTHONPATH=path)))
            runs.append(dict(variant=label, exit=child.returncode, stdout=child.stdout[-1500:],
                             stderr=child.stderr[-2500:]))
            if child.returncode:
                marked = code.replace('scope.close()\nassert budget', 'try:\n    scope.close()\nexcept RuntimeError as exc:\n'
                                      '    print(repr(exc), file=sys.stderr)\n'+'\n'.join(
                                          '    '+line for line in DIAGNOSE.strip().splitlines())+
                                      '\n    raise\nassert budget')
                again = real_run([command[0], command[1], command[2], marked, catalog],
                                 **dict(kwargs, env=dict(env, PYTHONPATH=path)))
                runs[-1]['diagnostic_stderr'] = again.stderr[-6000:]
            first = first or child
        return first

    TSS.subprocess.run = patched
    suite = unittest.defaultTestLoader.loadTestsFromName(
        'SegmentStoreTests.test_codec_sealed_chain_fresh_process_roundtrip', TSS)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    out.write_text(json.dumps(dict(test_ok=result.wasSuccessful(), runs=runs), indent=1), encoding='utf8')
    for row in runs:
        print(row['variant'], 'exit', row['exit'])


if __name__ == '__main__':
    main()
