"""Memory of a bare worker-like process: the composed package imported, no interval inputs loaded.

Imports what an interface batch worker needs (geometry, moving-interface moments, parallel
dispatch/results) and reports this process's peak working set, peak commit and RSS (MiB).
Usage: measure_import_memory.py --runtime test:<folder>
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runtime', required=True)
    args = ap.parse_args()
    import psutil
    before = psutil.Process().memory_info()
    rc1_env.install(args.runtime)
    from atlas_tectonics import integration_differential_geometry  # noqa: F401
    from atlas_tectonics import integration_moving_interface_moments  # noqa: F401
    from atlas_tectonics import integration_parallel_dispatch  # noqa: F401
    from atlas_tectonics import integration_parallel_results  # noqa: F401
    after = psutil.Process().memory_info()
    mib = lambda v: round(v/2**20, 1)
    print(json.dumps(dict(interpreter_only=dict(rss_mib=mib(before.rss)),
                          imported=dict(rss_mib=mib(after.rss), peak_working_set_mib=mib(after.peak_wset),
                                        peak_commit_mib=mib(after.peak_pagefile)))))


if __name__ == '__main__':
    main()
