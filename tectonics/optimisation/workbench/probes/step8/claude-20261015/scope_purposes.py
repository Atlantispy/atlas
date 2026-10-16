"""Non-zero retained-scope purposes at named checkpoints of capacity runs.

Usage: python -B scope_purposes.py CAPACITY.json PHASE [PHASE ...]
Prints purpose_bytes (current) and purpose_peak_bytes for each named phase,
largest first, so each held family can be attributed to its charge purpose.
"""
import json
import sys


def main():
    record = json.loads(open(sys.argv[1], encoding='utf-8').read())
    wanted = sys.argv[2:]
    for row in record.get('checkpoints', []):
        if row['name'] not in wanted:
            continue
        scope = row.get('scope') or {}
        current = {k: v for k, v in (scope.get('purpose_bytes') or {}).items() if v}
        print(f"== {row['name']} retained={scope.get('retained_bytes')} peak={scope.get('peak_retained_bytes')}")
        for name, value in sorted(current.items(), key=lambda kv: -kv[1]):
            print(f'   {value:>12,}  {name}')


if __name__ == '__main__':
    main()
