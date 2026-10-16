"""S9 W4 summary (read-only). Fails closed: exit 0 only if every check below holds.

Usage: python -B summarise_s9_w4.py OUTDIR W4_DIR REFERENCE_JSON ARM [ARM ...]

OUTDIR holds K-ARM.json (heat_control_on_frozen.py child output) and K-ARM/ (its saved arrays) for
K = 1..n in the order given. W4_DIR holds the prepared layouts base/ and cand/ (control.json each).
Checks:
- layouts: the two copied-helper inventories differ in private_heat_indexed_runtime.py only; base has
  BASE_SHA, cand has CAND_SHA, and cand's copy came from W4_DIR/cand-src;
- every arm: control status PASS, frozen_check status PASS, nothing loaded outside the frozen paths,
  no difference from the reference, the save complete (frozen_check.json status PASS);
- across arms: identical array digests (equal to the reference's), the same array names and cell count,
  the same legacy and compact metadata lengths; result IDs and metadata digests are path-bound (helper
  source paths) and are listed, not required equal;
- every timing field present.
A missing key, a None or a missing arm is a FAIL. Writes OUTDIR/summary.json and prints a short table.
"""
import json
import statistics
import sys
from hashlib import sha256
from pathlib import Path

BASE_SHA = '997277d845d81db007933f7e0d21531044571d09b7b7de31ac567e84f3c65ead'
CAND_SHA_PREFIX = 'ec170fc4'
RUNTIME = 'private_heat_indexed_runtime.py'


def main(argv):
    out, w4, reference, arms = Path(argv[1]), Path(argv[2]), Path(argv[3]), argv[4:]
    problems, rows = [], []

    def need(condition, message):
        if not condition:
            problems.append(message)
        return condition

    need(arms and set(arms) <= {'base', 'cand'}, 'arms must be base/cand: %r' % arms)
    copied = {}
    for name in ('base', 'cand'):
        try:
            copied[name] = json.loads((w4/name/'control.json').read_text(encoding='utf8'))['copied_helpers']
        except (OSError, ValueError, KeyError) as error:
            need(False, '%s layout: %r' % (name, error))
    if need(set(copied) == {'base', 'cand'}, 'both layouts needed'):
        base, cand = copied['base'], copied['cand']
        differing = sorted(k for k in set(base) | set(cand) if base.get(k, {}).get('sha256') != cand.get(k, {}).get('sha256'))
        need(differing == [RUNTIME], 'layouts differ in %r, expected only %s' % (differing, RUNTIME))
        need(base.get(RUNTIME, {}).get('sha256') == BASE_SHA, 'base runtime sha %r' % base.get(RUNTIME))
        cand_entry = cand.get(RUNTIME, {})
        need(str(cand_entry.get('sha256', '')).startswith(CAND_SHA_PREFIX), 'cand runtime sha %r' % cand_entry)
        need(Path(str(cand_entry.get('source', ''))).resolve() == (w4/'cand-src'/RUNTIME).resolve(),
             'cand runtime source %r' % cand_entry.get('source'))
        for name in ('base', 'cand'):
            on_disk = w4/name/'helpers'/RUNTIME
            need(on_disk.is_file() and sha256(on_disk.read_bytes()).hexdigest() == copied[name][RUNTIME]['sha256'],
                 '%s layout runtime on disk differs from its control.json' % name)
    try:
        expected_arrays = json.loads(reference.read_text(encoding='utf8'))['arrays']
    except (OSError, ValueError, KeyError) as error:
        expected_arrays = None
        need(False, 'reference: %r' % error)
    need(type(expected_arrays) is dict and bool(expected_arrays), 'reference has no arrays')

    for k, arm in enumerate(arms, 1):
        path, save = out/('%d-%s.json' % (k, arm)), out/('%d-%s' % (k, arm))
        try:
            result = json.loads(path.read_text(encoding='utf8'))
            frozen = result['frozen_check']
            saved = json.loads((save/'frozen_check.json').read_text(encoding='utf8'))
            row = dict(k=k, arm=arm, status=result['status'], frozen=frozen['status'],
                       leaks=frozen['loaded_outside_frozen'], differences=frozen['differences_from_reference'],
                       save=saved['status'], arrays=result['arrays'], array_names=sorted(result['arrays']),
                       cells=result['cell_count'],
                       legacy_id=result['legacy']['result_id'], compact_id=result['compact']['result_id'],
                       legacy_meta=result['legacy']['metadata_sha256'], compact_meta=result['compact']['metadata_sha256'],
                       legacy_bytes=result['legacy']['metadata_bytes'], compact_bytes=result['compact']['metadata_bytes'],
                       legacy_s=float(result['legacy']['seconds']), compact_s=float(result['compact']['seconds']),
                       elapsed_s=float(result['elapsed_seconds']), peak_wset=int(result['peak_working_set_bytes']))
        except (OSError, ValueError, KeyError, TypeError) as error:
            need(False, 'arm %d %s: %s %r' % (k, arm, type(error).__name__, error))
            continue
        need(row['status'] == 'PASS', 'arm %d control %r' % (k, row['status']))
        need(row['frozen'] == 'PASS', 'arm %d frozen_check %r' % (k, row['frozen']))
        need(row['save'] == 'PASS', 'arm %d save %r' % (k, row['save']))
        need(row['leaks'] == [], 'arm %d loaded outside the frozen paths: %r' % (k, row['leaks'][:5]))
        need(row['differences'] == [], 'arm %d differs from the reference: %r' % (k, row['differences']))
        need(row['arrays'] == expected_arrays, 'arm %d array digests differ from the reference' % k)
        rows.append(row)
    need(len(rows) == len(arms), '%d of %d arms readable' % (len(rows), len(arms)))
    for key in ('arrays', 'array_names', 'cells', 'legacy_bytes', 'compact_bytes'):
        need(len({json.dumps(row[key], sort_keys=True) for row in rows}) <= 1, 'arms differ in %s' % key)

    def mean(arm, key):
        values = [row[key] for row in rows if row['arm'] == arm]
        return statistics.fmean(values) if values else None

    timing = {key: dict(base=mean('base', key), cand=mean('cand', key)) for key in ('legacy_s', 'compact_s', 'elapsed_s')}
    for value in timing.values():
        value['gain_s'] = None if None in (value['base'], value['cand']) else value['base']-value['cand']
    summary = dict(status='PASS' if not problems else 'FAIL', problems=problems, arms=arms,
                   timing_means=timing,
                   path_bound_ids=[dict(k=r['k'], arm=r['arm'], legacy_id=r['legacy_id'], compact_id=r['compact_id'],
                                        legacy_meta=r['legacy_meta'], compact_meta=r['compact_meta']) for r in rows],
                   rows=[{key: r[key] for key in ('k', 'arm', 'status', 'frozen', 'save', 'cells', 'legacy_bytes',
                                                  'compact_bytes', 'legacy_s', 'compact_s', 'elapsed_s', 'peak_wset')}
                         for r in rows])
    target = out/'summary.json'
    if target.exists():
        problems.append('summary.json exists')
        summary['status'] = 'FAIL'
    else:
        target.write_text(json.dumps(summary, indent=1, sort_keys=True), encoding='utf8')
    print('k arm control frozen save legacy_s compact_s elapsed_s peak_GiB')
    for r in rows:
        print(r['k'], r['arm'], r['status'], r['frozen'], r['save'], '%.2f' % r['legacy_s'], '%.2f' % r['compact_s'],
              '%.2f' % r['elapsed_s'], '%.2f' % (r['peak_wset']/2**30))
    for key, value in timing.items():
        print(key, {name: None if v is None else round(v, 3) for name, v in value.items()})
    print('STATUS', summary['status'])
    for problem in problems:
        print('  FAIL:', problem)
    return 0 if summary['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
