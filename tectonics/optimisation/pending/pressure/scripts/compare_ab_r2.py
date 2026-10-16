"""compare_ab.py r2 (T/ps): the r1 verdicts, plus a null-control FIELD SET for full-scale runs.

r1 (compare_ab.py, unchanged) needs a NULL_DIR run of the same case: a third admission at full
scale. r2 adds two modes; everything else is r1's logic, imported from compare_ab.py:

  compare_ab_r2.py --write-null-fields BASE_DIR NULL_DIR OUT.json
      From an identity-control pair (base + a docstring-only module, e.g. the small-case
      ab2/base and ab2/null), record the descriptor fields that moved by identity alone, as
      index-free patterns ('[3]' -> '[]'), with the two reports' sha256. Refuses unless the
      pair's numbers (arrays, integration_leaves, datum) are equal and every moved field is an
      identity: strings on both sides, named *_id/*_ids (r1's rule) or both sha256 hex digests.
  compare_ab_r2.py BASE_DIR CANDIDATE_DIR --null-fields OUT.json
      NUMBERS EQUAL as r1. Otherwise IDENTITY-ONLY (D-b, null-field-controlled) only if
      numbers and structure are equal and EVERY differing field (a) is an identity (as above)
      and (b) matches a pattern in the field set. Anything else: DIFFER.
Exit 0 on NUMBERS EQUAL / IDENTITY-ONLY, 1 otherwise.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_ab import _flat, _identity_path  # noqa: E402

SCHEMA = 'atlas.private.ps-null-fields.r1'
NUMBERS = ('arrays', 'integration_leaves', 'datum')


_DIGEST = re.compile(r'[0-9a-f]{64}')


def _identity(path, x, y):
    """Both sides strings, and an identity by name (r1's rule) or both sha256 hex digests."""
    if not (isinstance(x, str) and isinstance(y, str)):
        return False
    return _identity_path(path) or bool(_DIGEST.fullmatch(x) and _DIGEST.fullmatch(y))


def _pattern(path):
    return re.sub(r'\[\d+\]', '[]', path)


def _load(folder):
    raw = (folder/'report.json').read_bytes()
    report = json.loads(raw)
    descriptor = dict(_flat(json.loads((folder/'descriptor-0.json').read_text())))
    return report, descriptor, hashlib.sha256(raw).hexdigest()


def write_null_fields(base, null, out):
    rb, db, hb = _load(base)
    rn, dn, hn = _load(null)
    ib, in_ = rb['arms'][0]['identity'], rn['arms'][0]['identity']
    if not all(ib[k] == in_[k] for k in NUMBERS):
        raise SystemExit('NULL-FIELDS REFUSED: the control pair\'s numbers differ')
    if sorted(db) != sorted(dn):
        raise SystemExit('NULL-FIELDS REFUSED: the control pair\'s descriptor structure differs')
    moved = sorted(path for path in db if db[path] != dn[path])
    bad = [p for p in moved if not _identity(p, db[p], dn[p])]
    if bad:
        raise SystemExit('NULL-FIELDS REFUSED: non-identity fields moved: %r' % bad)
    record = dict(schema=SCHEMA, base=str(base), null=str(null), base_report_sha256=hb, null_report_sha256=hn,
                  moved_paths=moved, patterns=sorted({_pattern(p) for p in moved}))
    Path(out).write_text(json.dumps(record, indent=1, sort_keys=True), encoding='utf8')
    print('NULL-FIELDS WRITTEN', out, 'paths', len(moved), 'patterns', len(record['patterns']))
    return 0


def compare(base, cand, fields_file):
    fields = json.loads(Path(fields_file).read_text(encoding='utf8'))
    if fields.get('schema') != SCHEMA or not isinstance(fields.get('patterns'), list):
        raise SystemExit('DIFFER: not a %s file' % SCHEMA)
    patterns = set(fields['patterns'])
    rb, db, _ = _load(base)
    rc, dc, _ = _load(cand)
    ib, ic = rb['arms'][0]['identity'], rc['arms'][0]['identity']
    numbers = all(ib[k] == ic[k] for k in NUMBERS)
    structure = sorted(db) == sorted(dc)
    print('arrays/leaves/datum equal:', numbers, '| descriptor structure equal:', structure)
    differing = [p for p in sorted(set(db) | set(dc)) if db.get(p) != dc.get(p)]
    if numbers and structure and not differing and ib['forcing_id'] == ic['forcing_id']:
        print('NUMBERS EQUAL (byte-identical stage output)')
        return 0
    outside = []
    for path in differing:
        x, y = db.get(path), dc.get(path)
        ok = _identity(path, x, y) and _pattern(path) in patterns
        print('  %s %s' % ('identity (null set)' if ok else 'UNEXPLAINED', path),
              '' if ok else '%s -> %s' % (repr(x)[:100], repr(y)[:100]))
        if not ok:
            outside.append(path)
    print('null field set: %d patterns from %s | candidate fields outside it: %r'
          % (len(patterns), fields_file, outside))
    if numbers and structure and not outside:
        print('IDENTITY-ONLY (D-b, null-field-controlled): numbers equal; every differing field is an identity '
              'that also moves under a docstring-only source change')
        return 0
    print('DIFFER')
    return 1


def main(argv):
    if len(argv) == 4 and argv[0] == '--write-null-fields':
        return write_null_fields(Path(argv[1]), Path(argv[2]), argv[3])
    if len(argv) == 4 and argv[2] == '--null-fields':
        return compare(Path(argv[0]), Path(argv[1]), argv[3])
    raise SystemExit(__doc__)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
