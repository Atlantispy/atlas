"""Canonical byte size of each top-level field of the r9 interval-1 root metadata (read-only).

Usage: python -B root_metadata_sizes.py RECEIPT.json
Finds every 'root_metadata' object in the receipt and prints the canonical
JSON size of each of its top-level fields, largest first, and the total.
"""
import json
import sys
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def find(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'root_metadata' and isinstance(item, dict):
                yield path+(key,), item
            yield from find(item, path+(key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from find(item, path+(index,))


def main():
    receipt = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    for path, root in find(receipt):
        sizes = sorted(((len(canonical(v)), k) for k, v in root.items()), reverse=True)
        print('/'.join(map(str, path)), 'total', len(canonical(root)), 'fields', len(root))
        for size, key in sizes:
            print(f'  {size:>9,}  {key}')


if __name__ == '__main__':
    main()
