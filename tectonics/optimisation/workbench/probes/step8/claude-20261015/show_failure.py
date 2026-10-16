"""Print the recorded failure, its traceback and any cleanup failure of a capacity result (read-only).

Usage: python -B show_failure.py CAPACITY_JSON
"""
import json
import sys
from pathlib import Path


def main():
    record = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    failure = record.get('failure') or {}
    print('status:', record.get('status'), '| stage:', record.get('stage'))
    print('errors:', json.dumps(record.get('errors')))
    print('failure:', failure.get('type'), '|', failure.get('message'), '| phase:', failure.get('phase'))
    print('cleanup_failure:', record.get('cleanup_failure'))
    print('--- traceback ---')
    print(failure.get('traceback', '(none)'))


if __name__ == '__main__':
    main()
