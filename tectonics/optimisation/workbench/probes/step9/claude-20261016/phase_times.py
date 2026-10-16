"""Read-only: per-phase durations of route (1) process records (run.json / reopen.json).

Usage: python -B phase_times.py LABEL=RECORD [LABEL=RECORD ...]

A record's top-level "phases" list holds {"name", "seconds"} start offsets; a phase lasts until
the next one starts, the last until the process's elapsed time (resources.elapsed_seconds, when
present). The guard's sampled peaks by phase (resources.sampled_peak_by_phase or the receipt's
"phases" map) are shown beside each phase when found: process tree RSS in MiB.
"""
import json
import sys


def peaks(record):
    resources = record.get('resources') or {}
    found = resources.get('sampled_peak_by_phase')
    if isinstance(found, dict):
        return found
    for value in record.values():
        if isinstance(value, dict) and isinstance(value.get('phases'), dict):
            return value['phases']
    return {}


def main():
    for item in sys.argv[1:]:
        label, path = item.split('=', 1)
        with open(path, encoding='utf8') as handle:
            record = json.load(handle)
        phases = record.get('phases') or []
        end = (record.get('resources') or {}).get('elapsed_seconds')
        table = peaks(record)
        print(f'## {label}: status {record.get("status")}, elapsed {end}')
        for k, phase in enumerate(phases):
            start = phase['seconds']
            stop = phases[k+1]['seconds'] if k+1 < len(phases) else end
            duration = None if stop is None else stop-start
            peak = table.get(phase['name']) or {}
            tree = peak.get('process_tree_rss') if isinstance(peak, dict) else None
            print(f'  {phase["name"]:<58} start {start:9.1f}  dur {"-" if duration is None else f"{duration:9.1f}"}'
                  + (f'  tree {tree >> 20} MiB' if isinstance(tree, int) else ''))


if __name__ == '__main__':
    main()
