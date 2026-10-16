"""Trace a capacity run's live-producer and retained bytes per checkpoint (read-only).

Usage: python -B capacity_producer_trace.py CAPACITY_JSON
Prints, for every checkpoint: seconds, name, producer bytes by purpose, retained bytes and
the run budget's reserved bytes, so the phase where a residual owner first appears and
never drops can be read off.
"""
import json
import sys
from pathlib import Path


def main():
    record = json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
    for row in record['checkpoints']:
        scope = row.get('scope') or {}
        purposes = {key.removeprefix('live-producer:'): value
                    for key, value in (scope.get('producer_purpose_bytes') or {}).items() if value}
        tracked = row.get('tracked') or {}
        print(f"{row['seconds']:9.1f}  {row['name'][:58]:58s}  producer={scope.get('producer_bytes')} "
              f"{purposes}  retained={scope.get('retained_bytes')}  reserved={tracked.get('reserved_bytes')}")


if __name__ == '__main__':
    main()
