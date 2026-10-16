"""Print one string value of a JSON file at a dotted path, unescaped (read-only).

Usage: python -B json_text.py FILE PATH [LAST_LINES]
"""
import json
import sys
from pathlib import Path


def main():
    value = json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
    for part in sys.argv[2].split('.'):
        value = value[int(part)] if isinstance(value, list) else value[part]
    lines = str(value).splitlines()
    keep = int(sys.argv[3]) if len(sys.argv) > 3 else len(lines)
    print('\n'.join(lines[-keep:]))


if __name__ == '__main__':
    main()
