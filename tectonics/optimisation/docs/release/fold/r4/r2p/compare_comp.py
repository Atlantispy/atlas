"""p20c-r2 against p20c-r1: confirm the staged composition differs only where Plan 20 says it does.

    python -B compare_comp.py R1_DIR R2_DIR R2_COMPOSITION_SHA256 OUT_JSON ALLOWED [ALLOWED ...]

Every file under each composition root is hashed. ALLOWED entries are paths relative to the root (forward slashes);
an entry ending in '*' allows any new file with that prefix (a new selftest). composition.json itself must have
R2_COMPOSITION_SHA256, and its `helpers` and `outputs` tables may differ only on allowed files. Other
composition.json keys that differ (the root path, the reviewed-inputs record) are listed for review, not refused.
Exit 0 iff nothing outside ALLOWED differs, is added or is removed.
"""
import hashlib
import json
import sys
from pathlib import Path


def tree(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def allowed(rel, rules):
    return any(rel == r or (r.endswith('*') and rel.startswith(r[:-1])) for r in rules)


def table_entry(rel):
    """(table, key) for a file: composition.json keys helpers by the path under helpers/ and outputs by the path
    under src/."""
    for table, prefix in (('helpers', 'helpers/'), ('outputs', 'src/')):
        if rel.startswith(prefix):
            return table, rel[len(prefix):]
    return None


def main(argv):
    if len(argv) < 5:
        print(__doc__)
        return 2
    r1, r2, want, out, rules = Path(argv[0]), Path(argv[1]), argv[2], Path(argv[3]), argv[4:]
    t1, t2 = tree(r1), tree(r2)
    got = t2.get('composition.json')
    changed = sorted(k for k in set(t1) & set(t2) if t1[k] != t2[k] and k != 'composition.json')
    added, removed = sorted(set(t2) - set(t1)), sorted(set(t1) - set(t2))
    bad = [k for k in changed + added if not allowed(k, rules)] + removed
    c1, c2 = (json.loads((r/'composition.json').read_bytes()) for r in (r1, r2))
    table_bad, keys_differ = [], sorted(k for k in set(c1) | set(c2) if c1.get(k) != c2.get(k))
    entries = {table_entry(k) for k in changed + added if allowed(k, rules)}
    for table in ('helpers', 'outputs'):
        a, b = c1.get(table) or {}, c2.get(table) or {}
        for name in sorted(set(a) | set(b)):
            if a.get(name) != b.get(name) and (table, name) not in entries:
                table_bad.append('%s/%s' % (table, name))
    ok = got == want and not bad and not table_bad
    report = dict(status='PASS' if ok else 'FAIL', composition_sha256=got, expected_sha256=want, changed=changed,
                  added=added, removed=removed, not_allowed=bad, table_entries_not_allowed=table_bad,
                  composition_keys_differ=keys_differ, files=[len(t1), len(t2)])
    out.write_text(json.dumps(report, indent=1) + '\n', encoding='utf8', newline='\n')
    print(json.dumps(dict(report, changed=changed[:8], added=added[:8])))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
