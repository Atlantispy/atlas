"""Apply hand-off packages listed by their manifest.json files, through apply_files.py (all or nothing).

Usage: python -B apply_manifest_generation.py LABEL EXPECTED_ROWS PACKAGE_DIR [PACKAGE_DIR ...]

Each package's manifest rows give the live path (relative to R), the origin SHA-256 (None for a
new file) and the new SHA-256; the source is PACKAGE_DIR/files/<name>. Two manifest shapes are
read: atlas.r1-handoff-manifest.v1 (live_path, origin_sha256, new_sha256) and
atlas.review-handoff.v1 (path, source, origin_sha256, sha256). The row count must equal
EXPECTED_ROWS. apply_files.py then checks every live and new hash before the first write.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None


def rows(package):
    manifest = json.loads((package/'manifest.json').read_text(encoding='utf-8'))
    for row in manifest['files']:
        if str(row.get('action', '')).startswith('none'):
            # Already live with these bytes (origin = new); apply_files' live check is not needed.
            print('skipped (action none): '+row['live_path'])
            continue
        if 'live_path' in row:
            target, new = row['live_path'], row['new_sha256']
            source = package/'files'/row['name']
        else:
            target, new = row['path'], row['sha256']
            source = package/row['source']
        yield [str(source), target, row['origin_sha256'] or '-', new]


def main():
    label, expected, packages = sys.argv[1], int(sys.argv[2]), [Path(p) for p in sys.argv[3:]]
    table = [row for package in packages for row in rows(package)]
    targets = [row[1] for row in table]
    for _, target, live, new in table:
        print(f'{target:58s} {live[:8]:8s} -> {new[:8]}')
    if len(table) != expected or len(set(targets)) != len(targets):
        raise SystemExit(f'{len(table)} rows ({len(set(targets))} distinct targets), expected {expected}')
    # A row already at its new hash was written earlier in this same generation (an apply
    # interrupted after its checks passed); it is listed, not rewritten.
    done = [row for row in table if row[2] != '-' and sha(R/row[1]) == row[3]]
    for row in done:
        print('already at its new hash (applied earlier in this generation): '+row[1])
    pending = [row for row in table if row not in done]
    arguments = [value for row in pending for value in row]
    return subprocess.run([sys.executable, '-B', str(HERE/'apply_files.py'), label, *arguments]).returncode


if __name__ == '__main__':
    raise SystemExit(main())
