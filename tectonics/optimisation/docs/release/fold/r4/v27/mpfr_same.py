"""RF2 condition c (FOLD.md §14): the MPFR library each parity arm loaded, read from arms_r8's native records.

    python -B mpfr_same.py OUT_JSON CHILD_DIR...

Each CHILD_DIR holds an arm.json from arms_r8.py child (R, A, A', B, B'), five distinct folders. PASS when:
- every child's record has no error and exactly one loaded module whose file name starts libmpfr, at the path RF2's
  _ASSEMBLY_MPFR_PATH is joined to from that child's sys.exec_prefix (compared resolved, case-folded);
- that file, by resolved path and sha256, is the same in every child;
- every worker that left a snapshot has no error and at most one libmpfr, and any it has is that same file. A heat
  worker need not load MPFR at all, so none is allowed there; a worker without a snapshot has no record and is
  counted as uncovered, not failed; a worker with a snapshot but no native record fails.
The GMP libraries are reported, not judged. OUT_JSON must not exist.
"""
import json
import os
import sys
from pathlib import Path

CHILDREN = 5   # R, A, A', B, B'


def _key(path):
    return os.path.normcase(os.path.realpath(path))


def _mpfr(record):
    return sorted((_key(path), sha) for path, sha in record.get('modules', {}).items()
                  if os.path.basename(path).lower().startswith('libmpfr'))


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    out, problems, files, rows = Path(argv[0]), [], set(), []
    workers = dict(total=0, snapshot=0, with_mpfr=0)
    distinct = {_key(directory) for directory in argv[1:]}
    if len(argv) - 1 != CHILDREN or len(distinct) != CHILDREN:
        problems.append('%d child folders, %d distinct; %d distinct are required'
                        % (len(argv) - 1, len(distinct), CHILDREN))
    for directory in argv[1:]:
        arm = json.loads((Path(directory)/'arm.json').read_bytes())
        native, name = arm.get('native'), Path(directory).name
        if not isinstance(native, dict) or 'error' in native or 'modules' not in native:
            problems.append('%s: no native record (%s)' % (name, None if native is None else native.get('error')))
            continue
        mpfr = _mpfr(native)
        expected = _key(os.path.join(native['exec_prefix'], 'Lib', 'site-packages', 'gmpy2.libs', 'libmpfr-6.dll'))
        if len(mpfr) != 1:
            problems.append('%s: %d libmpfr modules loaded, not 1: %s' % (name, len(mpfr), mpfr))
        elif mpfr[0][0] != expected:
            problems.append('%s: libmpfr loaded from %s, not %s' % (name, mpfr[0][0], expected))
        files.update(mpfr)
        gmp = sorted(_key(p) for p in native['modules'] if os.path.basename(p).lower().startswith('libgmp'))
        row = dict(child=name, exec_prefix=native['exec_prefix'], mpfr=mpfr, gmp=gmp, workers=[])
        for worker in arm.get('workers', []):
            workers['total'] += 1
            record = worker.get('native')
            if record is None:
                if worker.get('snapshot') is not False:   # r8 writes None for a snapshot without a native record too
                    problems.append('%s worker %s: a snapshot without a native record' % (name, worker.get('pid')))
                row['workers'].append(dict(pid=worker.get('pid'), snapshot=False))
                continue
            workers['snapshot'] += 1
            if 'error' in record or 'modules' not in record:
                problems.append('%s worker %s: no native record (%s)' % (name, worker.get('pid'), record.get('error')))
                continue
            loaded = _mpfr(record)
            workers['with_mpfr'] += bool(loaded)
            if len(loaded) > 1:
                problems.append('%s worker %s: %d libmpfr modules: %s' % (name, worker.get('pid'), len(loaded), loaded))
            files.update(loaded)
            row['workers'].append(dict(pid=worker.get('pid'), snapshot=True, mpfr=loaded))
        rows.append(row)
    if len(files) != 1:
        problems.append('%d distinct libmpfr files across the children and workers: %s' % (len(files), sorted(files)))
    report = dict(status='FAIL' if problems else 'PASS', problems=problems, mpfr=sorted(files), workers=workers,
                  children=rows)
    with open(out, 'x', encoding='utf8', newline='\n') as handle:
        json.dump(report, handle, indent=1, sort_keys=True)
    print(json.dumps(dict(status=report['status'], problems=problems[:3], mpfr=sorted(files), workers=workers)))
    return 0 if not problems else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
