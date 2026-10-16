"""select_composed against the smoke tree's composed runtime (read-only probe, 16 Oct 2026).

Usage: python -B probe_worker_selection.py REAL_PEAK_BYTES LOGICAL_PEAK_BYTES
Prints the selection record for a parent with the given measured peaks under the 16 GiB
logical budget; the composed policy's accepted maximum is detected, not assumed.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]


def main():
    sys.path[:0] = [str(R/'s1'/'src'), str(R)]
    import interface_worker_selection as S
    record = S.select_composed(parent={'real_peak_bytes': int(sys.argv[1]), 'logical_peak_bytes': int(sys.argv[2])},
                               logical_budget_bytes=16 << 30)
    print(json.dumps({key: record[key] for key in ('chosen', 'selected', 'policy_maximum', 'reason', 'checks',
                                                    'free_at_launch', 'per_worker_booked_bytes')}, indent=1))


if __name__ == '__main__':
    main()
