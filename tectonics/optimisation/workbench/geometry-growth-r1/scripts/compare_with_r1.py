"""Does today's replay_surfaces.py (d1ac5775, changed after jets-r1 ran) select and compute what the
jets-r1 version did? Compares the data rows of NEW shards with jets-r1's rows of the same stage and arm
(the same runtime folder): row keys (surfaces_stage_check's key) and every field except cpu_s/wall_s.
A capped row on either side is compared by key only (its partial values depend on timing).
Usage: r1_rows.py MODE NEW_DIR NEW_PREFIX OLD_DIR OLD_PREFIX  (MODE subset: NEW's keys within OLD's;
equal: the same keys, as often). Shards are <prefix>-s*.jsonl. Exit 0 only if no key or value differs."""
import json
import sys
from collections import Counter
from pathlib import Path

TIMING = ('cpu_s', 'wall_s')


def key(r):
    return (r.get('kind'), r.get('support_index'), r.get('cell'), r.get('other'),
            r.get('constraint_name') or (r.get('axis'), r.get('end')))


def rows(folder, prefix):
    out = {}
    files = sorted(Path(folder).glob(prefix + '-s*.jsonl'))
    for p in files:
        for line in p.read_text(encoding='utf8').splitlines():
            r = json.loads(line)
            if r.get('done') or 'job_counts' in r:
                continue
            out.setdefault(key(r), []).append(r)
    return out, len(files)


def strip(r):
    return json.dumps({k: v for k, v in r.items() if k not in TIMING}, sort_keys=True)


def main(mode, new_dir, new_prefix, old_dir, old_prefix):
    new, nf = rows(new_dir, new_prefix)
    old, of = rows(old_dir, old_prefix)
    errors, same, capped = [], 0, 0
    if not nf or not of or not new:
        errors.append('no shards or rows (new %d files, old %d files)' % (nf, of))
    cn = Counter({k: len(v) for k, v in new.items()})
    co = Counter({k: len(v) for k, v in old.items()})
    missing = cn - co
    if missing:
        errors.append('%d new keys not in jets-r1 (first %s)' % (sum(missing.values()), next(iter(missing))))
    if mode == 'equal' and co - cn:
        errors.append('%d jets-r1 keys not in new' % sum((co - cn).values()))
    for k, vs in new.items():
        olds = old.get(k, [])
        for a, b in zip(sorted(vs, key=strip), sorted(olds, key=strip)):
            if 'capped' in (a.get('status'), b.get('status')):
                capped += 1
            elif strip(a) == strip(b):
                same += 1
            else:
                errors.append('value differs at %s: %s' % (k, sorted(f for f in set(a) | set(b)
                                                                       if f not in TIMING and a.get(f) != b.get(f))))
    print('%s %s vs r1 %s: %d rows, %d identical, %d capped (key only), mode %s'
          % ('FAIL' if errors else 'OK', new_prefix, old_prefix, sum(cn.values()), same, capped, mode))
    for e in errors[:10]:
        print('  ' + e)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:6]))
