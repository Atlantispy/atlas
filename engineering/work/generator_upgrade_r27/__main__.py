"""Run R26 scientific recipes or R27 execution plans using duration forecasts."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from work.generator_runtime_r12 import _raw

# runpy's -m entrypoint does not use exec_module; capture its bytes explicitly.
_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE,__file__,'exec',dont_inherit=True):
    raise ValueError('executed R27 entrypoint differs from current source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()
from . import registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe',type=Path)
    parser.add_argument('--expected-seconds',type=float,default=None,
        help='Estimated serial seconds after expected cache reuse; no trial run required')
    parser.add_argument('--parallel-threshold-s',type=float,default=120.)
    parser.add_argument('--cache-root',type=Path)
    parser.add_argument('--no-cache',action='store_true')
    parser.add_argument('--workers',type=int,default=None)
    parser.add_argument('--memory-budget-mb',type=int,default=1024)
    parser.add_argument('--worker-memory-mb',type=int,default=512)
    parser.add_argument('--scheduling',choices=('ready','wave'),default='ready')
    parser.add_argument('--startup-budget-s',type=float,default=1.5)
    args = parser.parse_args()
    with args.recipe.open('rb') as source:
        raw = source.read(8*1024*1024+1)
    if len(raw)>8*1024*1024:
        raise ValueError('bounded recipe required')
    print(json.dumps(registry.run(json.loads(raw),expected_seconds=args.expected_seconds,
        parallel_threshold_s=args.parallel_threshold_s,cache=not args.no_cache,
        cache_root=args.cache_root,workers=args.workers,memory_budget_mb=args.memory_budget_mb,
        worker_memory_mb=args.worker_memory_mb,scheduling=args.scheduling,
        startup_budget_s=args.startup_budget_s),sort_keys=True,allow_nan=False))


if __name__ == '__main__':
    main()
