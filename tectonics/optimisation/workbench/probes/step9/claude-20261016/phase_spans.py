"""Read-only: per-phase spans from a guarded run record's ``phases`` list (item 11 question).

Usage: python -B phase_spans.py <run.json> [<more.json> ...]
Prints each phase's start (s), its span to the next phase start (s), the observed return
counts, and the phase names that recur (with their summed spans). Nothing is written.
"""
import json
import sys
from collections import defaultdict

WATCH = ('heat-conservative-finish', 'heat-native-projection', 'actual-heat-endpoint-committed',
         'actual-composed-heat-forward', 'heat-low-predictor', 'heat-certified-polygon-reconstruction')


def find(value, key):
    """Every value stored under ``key`` anywhere in the record."""
    if isinstance(value, dict):
        for name, item in value.items():
            if name == key:
                yield item
            yield from find(item, key)
    elif isinstance(value, list):
        for item in value:
            yield from find(item, key)


def main(paths):
    for path in paths:
        with open(path, encoding='utf8') as stream:
            record = json.load(stream)
        print('==', path)
        for phases in find(record, 'phases'):
            if not (isinstance(phases, list) and phases and isinstance(phases[0], dict) and 'seconds' in phases[0]):
                continue
            total = defaultdict(float)
            calls = defaultdict(int)
            for here, after in zip(phases, phases[1:] + [None]):
                span = (after['seconds'] - here['seconds']) if after else None
                calls[here['name']] += 1
                if span is not None:
                    total[here['name']] += span
                if here['name'] in WATCH or (span is not None and span >= 30):
                    print(f"  {here['seconds']:9.1f}s  span {'' if span is None else f'{span:8.1f}s'}  {here['name']}")
            print('  phases', len(phases), 'last at', f"{phases[-1]['seconds']:.1f}s")
            for name in sorted(calls, key=lambda n: -total[n])[:12]:
                print(f'  sum {total[name]:9.1f}s  starts {calls[name]:5d}  {name}')
        for key in ('observed_returns_at_the_end', 'counts'):
            for counts in find(record, key):
                if isinstance(counts, dict):
                    print(' ', key, json.dumps(counts, sort_keys=True)[:600])


if __name__ == '__main__':
    main(sys.argv[1:])
