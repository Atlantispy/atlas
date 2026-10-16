"""Structure of a gzipped JSON capture: keys, types, sizes, to a bounded depth.

Usage: python -B inspect_capture.py CAPTURE.json.gz EXPECTED_SHA256 [DEPTH]
Read-only. Prints each object key path with its type, item count and the
canonical byte width of its value (for lists, also the first item's keys).
"""
import gzip
import json
import sys
from hashlib import sha256


def width(value):
    return len(json.dumps(value, separators=(',', ':'), ensure_ascii=False))


def walk(value, path, depth, limit):
    kind = type(value).__name__
    count = len(value) if isinstance(value, (list, dict)) else ''
    print(f"{'  '*depth}{path or '<root>'}: {kind} {count} bytes={width(value):,}")
    if depth >= limit:
        return
    if isinstance(value, dict):
        for key in list(value)[:40]:
            walk(value[key], key, depth+1, limit)
    elif isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            print(f"{'  '*(depth+1)}[0] keys: {sorted(first)[:30]}")
            for key in list(first)[:30]:
                walk(first[key], '[0].'+key, depth+2, limit)


def main():
    path, expected = sys.argv[1], sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    raw = open(path, 'rb').read()
    actual = sha256(raw).hexdigest()
    if actual != expected:
        raise SystemExit(f'capture hash differs: {actual}')
    value = json.loads(gzip.decompress(raw))
    walk(value, '', 0, limit)


if __name__ == '__main__':
    main()
