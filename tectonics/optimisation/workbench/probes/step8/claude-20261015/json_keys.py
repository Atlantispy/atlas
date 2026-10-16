"""Print a JSON file's key structure (read-only): key, value type and encoded size, to a depth.

Usage: python -B json_keys.py FILE [DEPTH] [PATH.TO.KEY]
"""
import json
import sys


def size(value):
    return len(json.dumps(value, separators=(',', ':')))


def walk(value, depth, prefix, limit):
    if isinstance(value, dict):
        for key, child in value.items():
            kind = type(child).__name__
            extra = f' len={len(child)}' if isinstance(child, (dict, list)) else f' = {json.dumps(child)[:80]}'
            print(f'{prefix}{key}: {kind} {size(child)}B{extra}')
            if depth < limit:
                walk(child, depth+1, prefix+'  ', limit)
    elif isinstance(value, list) and value and depth < limit:
        print(f'{prefix}[0]: {type(value[0]).__name__} {size(value[0])}B')
        walk(value[0], depth+1, prefix+'  ', limit)


def main():
    value = json.loads(open(sys.argv[1], encoding='utf8').read())
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    if len(sys.argv) > 3:
        for part in sys.argv[3].split('.'):
            value = value[int(part)] if isinstance(value, list) else value[part]
    walk(value, 0, '', limit)


if __name__ == '__main__':
    main()
