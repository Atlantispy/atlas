"""Print the first bytes of a gzip JSON capture and its top-level key layout (read-only).

Usage: python -B peek_gzip_json.py FILE.json.gz [BYTES]
The layout pass decodes the whole capture once in memory: use on bounded captures only.
"""
import gzip
import json
import sys


def main():
    path, count = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 600
    with gzip.open(path, 'rb') as stream:
        print(stream.read(count).decode('utf8', errors='replace'))
    with gzip.open(path, 'rb') as stream:
        value = json.load(stream)

    def show(item, prefix, depth):
        if isinstance(item, dict):
            for key, child in list(item.items())[:40]:
                size = len(child) if isinstance(child, (dict, list)) else ''
                print(f'{prefix}{key}: {type(child).__name__} {size}')
                if depth < 2:
                    show(child, prefix+'  ', depth+1)
        elif isinstance(item, list) and item and depth < 2:
            print(f'{prefix}[0] of {len(item)}: {type(item[0]).__name__}')
            show(item[0], prefix+'  ', depth+1)
    show(value, '', 0)


if __name__ == '__main__':
    main()
