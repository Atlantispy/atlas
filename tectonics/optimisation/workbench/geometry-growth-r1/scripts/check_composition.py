"""Fail-closed pre-flight for a test composition (rc1_env's test: loader does not compare files).
Usage: python -B -I check_composition.py FOLDER [RELPATH=SHA256 ...]
Exits 0 only if FOLDER/TEST_COMPOSITION.json exists, the folder's .py files (no __pycache__ anywhere)
are exactly the manifest's file map, byte for byte, and every RELPATH pin equals that file's sha256.
"""
import json
import sys
from hashlib import sha256
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    root = Path(sys.argv[1]).resolve()
    errors = []
    manifest = root/'TEST_COMPOSITION.json'
    if not manifest.is_file():
        raise SystemExit('FAIL %s: no TEST_COMPOSITION.json' % root)
    files = json.loads(manifest.read_text(encoding='utf8')).get('files')
    if type(files) is not dict or not files:
        raise SystemExit('FAIL %s: manifest has no file map' % root)
    if any(p.name == '__pycache__' for p in root.rglob('*')):
        errors.append('__pycache__ present')
    found = {}
    for p in sorted(root.rglob('*.py')):
        name = str(p.relative_to(root)).replace('\\', '/')
        try:
            found[name] = sha256(p.read_bytes()).hexdigest()
        except OSError as exc:   # e.g. a path past MAX_PATH: unreadable is a failure, never a skip
            found[name] = 'unreadable'
            errors.append('%s unreadable: %s' % (name, type(exc).__name__))
    for name in sorted(set(files) | set(found)):
        if files.get(name) != found.get(name):
            errors.append('%s: manifest %s, folder %s' % (name, files.get(name), found.get(name)))
    for pin in sys.argv[2:]:
        name, sep, want = pin.partition('=')
        if not sep or len(want) != 64:
            errors.append('bad pin %r' % pin)
        elif found.get(name) != want:
            errors.append('%s is %s, pinned %s' % (name, found.get(name), want))
    print('%s %s (%d files, %d pins)' % ('FAIL' if errors else 'OK', root.name, len(found), len(sys.argv) - 2))
    for e in errors[:20]:
        print('  ' + e)
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
