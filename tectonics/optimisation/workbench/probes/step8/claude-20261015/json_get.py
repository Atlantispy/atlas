"""Print the values at dotted paths of a JSON file (read-only).

Usage: python -B json_get.py FILE PATH [PATH ...]
A PATH is dot-separated; a list index is a number (errors.0.message).
Each value is printed as indented JSON, truncated to 6,000 characters.
"""
import json
import sys
from pathlib import Path


def lookup(value, path):
    for part in path.split('.'):
        if isinstance(value, list):
            value = value[int(part)]
        else:
            value = value[part]
    return value


def main():
    data = json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
    for path in sys.argv[2:]:
        try:
            text = json.dumps(lookup(data, path), indent=1, sort_keys=True, default=str)
        except (KeyError, IndexError, ValueError) as error:
            text = 'missing: ' + repr(error)
        print('== ' + path)
        print(text[:6000])


if __name__ == '__main__':
    main()
