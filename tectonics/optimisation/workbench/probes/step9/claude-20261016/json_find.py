"""Read-only: print every occurrence of the named keys in a JSON file, with its path and a short value.

Usage: python -B json_find.py FILE KEY [KEY ...] [--width N]
"""
import json
import sys


def walk(value, path, keys, width):
    if isinstance(value, dict):
        for key, item in value.items():
            here = f'{path}.{key}'
            if key in keys:
                print(here, json.dumps(item)[:width])
            walk(item, here, keys, width)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            walk(item, f'{path}[{index}]', keys, width)


def main():
    argv = sys.argv[1:]
    width = 400
    if '--width' in argv:
        at = argv.index('--width')
        width = int(argv[at+1])
        del argv[at:at+2]
    with open(argv[0], encoding='utf8') as handle:
        data = json.load(handle)
    walk(data, '$', set(argv[1:]), width)


if __name__ == '__main__':
    main()
