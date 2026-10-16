"""Reproducer: profile_initial_metrics.py's opening sequence only (contexts + measurement store).

Usage: probe_store_open.py --runtime RT --output-dir NEW_DIR [--store-first]
Prints 'open ok' or the exception. --store-first opens the store before the contexts.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402

MEASUREMENT_CACHE = {'chunk_bytes': 65536, 'max_array_bytes': 1 << 20, 'max_store_bytes': 128 << 20}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runtime', required=True)
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--store-first', action='store_true')
    ap.add_argument('--script-imports', action='store_true', help="also the profile script's fixture imports")
    args = ap.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=False)
    rc1_env.install(args.runtime)
    sys.path.append(str(HERE.parents[1] / 'composed-r1' / 'ram'))
    sys.path.append(str(HERE.parents[4] / 'heat-repair-20261007' / 'source' / 'tectonics' / 'tests'))
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
    if args.script_imports:
        import psutil  # noqa: F401
        import i04_differential_fixture  # noqa: F401
        import private_heat_original_spatial_r1  # noqa: F401
        import probe_heat_original_connected_r9  # noqa: F401
    require_strict_execution()
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    store = lambda: ArrayStore(out/'initial-measurements.sqlite', StoreLimits(**MEASUREMENT_CACHE),
                               Compression(codec='raw'), budget=budget)
    try:
        if args.store_first:
            with store(), ExecutionContext('reference'), ExecutionContext('scipy'):
                pass
        else:
            with ExecutionContext('reference'), ExecutionContext('scipy'), store():
                pass
        print(args.runtime[-14:], 'store-first' if args.store_first else 'contexts-first', 'open ok')
    except Exception as exc:
        print(args.runtime[-14:], 'store-first' if args.store_first else 'contexts-first', 'FAIL',
              type(exc).__name__, str(exc)[:160], repr(exc.__cause__)[:200])


if __name__ == '__main__':
    main()
