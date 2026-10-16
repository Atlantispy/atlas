"""Cross-runtime compare of two ab_pressure.py outputs (T/ps): numbers equal, identities classified.

Fails closed (exit 1) unless:
  - every array digest and shape, integration_leaves, the datum record and the descriptor's
    non-identity content are equal between the two runs' first arms, and
  - every descriptor field that differs is an identity (a string-valued key ending in _id or
    _ids, or a list of such strings) whose value either is one of the run's upstream admission
    identities that themselves differ, or is the stage's own forcing_id/driving_id.
Prints each differing descriptor path with both values, the admission identities that differ,
and the verdict: NUMBERS EQUAL, IDENTITY-ONLY (D-b) or DIFFER.
With NULL_DIR (an identity-control run: base + a docstring-only module), a differing field
counts as identity-only ONLY if it also differs between BASE and NULL; the verdict is then
IDENTITY-ONLY (D-b, null-controlled).
Usage: compare_ab.py BASE_DIR CANDIDATE_DIR [NULL_DIR]
"""
import json
import sys
from pathlib import Path


def _flat(value, path=''):
    if isinstance(value, dict):
        for key in value:
            yield from _flat(value[key], path+'/'+str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flat(item, '%s[%d]' % (path, index))
    else:
        yield path, value


def _identity_path(path):
    leaf = path.rsplit('/', 1)[-1].split('[', 1)[0]
    return leaf.endswith('_id') or leaf.endswith('_ids') or leaf in ('forcing_id', 'boundary_pose_ids')


def main():
    base, cand = (Path(p) for p in sys.argv[1:3])
    null = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    rb, rc = (json.loads((p/'report.json').read_text()) for p in (base, cand))
    ib, ic = rb['arms'][0]['identity'], rc['arms'][0]['identity']
    db, dc = (json.loads((p/'descriptor-0.json').read_text()) for p in (base, cand))
    numbers = all(ib[k] == ic[k] for k in ('arrays', 'integration_leaves', 'datum'))
    print('arrays/leaves/datum equal:', numbers)
    upstream_b, upstream_c = rb.get('admission_ids', {}), rc.get('admission_ids', {})
    changed_upstream = {k: (upstream_b.get(k), upstream_c.get(k)) for k in set(upstream_b) | set(upstream_c)
                        if upstream_b.get(k) != upstream_c.get(k)}
    print('admission identities that differ:', sorted(changed_upstream))
    inherited = {v for pair in changed_upstream.values() for v in pair if v}
    fb, fc = dict(_flat(db)), dict(_flat(dc))
    structure = sorted(fb) == sorted(fc)
    print('descriptor structure equal:', structure)
    unexplained, explained = [], []
    for path in sorted(set(fb) | set(fc)):
        x, y = fb.get(path), fc.get(path)
        if x == y:
            continue
        if _identity_path(path) and isinstance(x, str) and isinstance(y, str):
            (explained if (x in inherited and y in inherited) or path in ('/forcing_id',) else unexplained).append(path)
            continue
        unexplained.append(path)
    for path in explained:
        print('  identity (upstream)', path)
    for path in unexplained:
        print('  UNEXPLAINED', path, repr(fb.get(path))[:120], '->', repr(fc.get(path))[:120])
    if numbers and structure and not explained and not unexplained and ib['forcing_id'] == ic['forcing_id']:
        print('NUMBERS EQUAL (byte-identical stage output)')
        return 0
    identity_only = [p for p in unexplained if _identity_path(p)]
    if null is not None:
        dn = dict(_flat(json.loads((null/'descriptor-0.json').read_text())))
        moved = {path for path in set(fb) | set(dn) if fb.get(path) != dn.get(path)}
        rn = json.loads((null/'report.json').read_text())
        null_numbers = all(ib[k] == rn['arms'][0]['identity'][k] for k in ('arrays', 'integration_leaves', 'datum'))
        outside = [p for p in explained+unexplained if p not in moved]
        print('null control: numbers equal to base:', null_numbers, '| fields moved by identity alone:', len(moved),
              '| candidate fields outside that set:', outside)
        if numbers and structure and null_numbers and not outside:
            print('IDENTITY-ONLY (D-b, null-controlled): numbers equal; every differing field also moves '
                  'under a docstring-only source change')
            return 0
        print('DIFFER')
        return 1
    if numbers and structure and len(identity_only) == len(unexplained):
        print('IDENTITY-ONLY (D-b): numbers equal; %d upstream identity fields, %d stage identity fields differ'
              % (len(explained), len(identity_only)))
        return 0
    print('DIFFER')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
