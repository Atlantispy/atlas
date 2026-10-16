"""Print the failing-output tails recorded by run_modules.py.

Usage: python -B show_failures.py REGRESSION.json [MAX_LINES]
"""
import json
import sys


def main():
    rows = json.loads(open(sys.argv[1], encoding='utf-8').read())
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    for row in rows if type(rows) is list else rows.get('modules', []):
        if row.get('exit') != 0:
            print('==', row['module'], row.get('status'), 'failures', row.get('failures'), 'errors', row.get('errors'))
            lines = [line for line in (row.get('tail') or '').splitlines() if not line.endswith(' ok')]
            print('\n'.join(lines[-limit:]))


if __name__ == '__main__':
    main()
