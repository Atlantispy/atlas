"""Verify a merged generation against its manifests and write one merge record (read-only on C).

Usage: python -B record_generation.py OUT.json LABEL[,LABEL...] PACKAGE_DIR [PACKAGE_DIR ...]

Every manifest row must now be live at its new SHA-256. For each replaced file the before copy
before-src/<name>.before-<label> (first label that exists) must hash to the row's origin. The
record lists file, origin, new, before copy and package. OUT.json is created exclusively.
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None


def main():
    out, labels, packages = Path(sys.argv[1]), sys.argv[2].split(','), [Path(p) for p in sys.argv[3:]]
    record, problems = [], []
    for package in packages:
        for row in json.loads((package/'manifest.json').read_text(encoding='utf-8'))['files']:
            target = row.get('live_path') or row['path']
            new = row.get('new_sha256') or row['sha256']
            origin = row['origin_sha256']
            live = sha(R/target)
            if live != new:
                problems.append(f'{target}: live {live} is not the new {new}')
            before = None
            if origin is not None and origin != new:
                name = Path(target).name
                copies = [HERE/'before-src'/(name+'.before-'+label) for label in labels]
                before = next((copy for copy in copies if copy.is_file()), None)
                if before is None or sha(before) != origin:
                    problems.append(f'{target}: no before copy with the origin {origin}')
            record.append({'file': target, 'origin': origin, 'new': new, 'package': package.name if
                           package.name != 'handoff' else package.parent.name+'/handoff',
                           'before_copy': None if before is None else str(before.relative_to(HERE)),
                           'action': row.get('action', 'replace' if origin else 'new')})
    for row in record:
        print(f"{row['file']:56s} {str(row['origin'])[:8]:8s} -> {row['new'][:8]}  {row['before_copy'] or ''}")
    if problems:
        raise SystemExit('\n'.join(problems))
    with out.open('x', encoding='utf-8') as stream:
        json.dump({'generation': out.stem, 'rows': record}, stream, indent=1)
    print(f'{len(record)} rows verified; record {out.name}')


if __name__ == '__main__':
    main()
