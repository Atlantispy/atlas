"""Run explicitly R24-bound recipes with automatic bounded parallel execution."""
import argparse
import json
from pathlib import Path
from . import registry

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe',type=Path)
    parser.add_argument('--cache-root',type=Path)
    parser.add_argument('--no-cache',action='store_true')
    parser.add_argument('--workers',type=int,default=None)
    parser.add_argument('--memory-budget-mb',type=int,default=1024)
    parser.add_argument('--worker-memory-mb',type=int,default=512)
    parser.add_argument('--scheduling',choices=('ready','wave'),default='ready')
    args = parser.parse_args()
    with args.recipe.open('rb') as source:
        raw = source.read(8*1024*1024+1)
    if len(raw)>8*1024*1024:
        raise ValueError('bounded recipe required')
    print(json.dumps(registry.run(json.loads(raw),cache=not args.no_cache,
        cache_root=args.cache_root,workers=args.workers,memory_budget_mb=args.memory_budget_mb,
        worker_memory_mb=args.worker_memory_mb,scheduling=args.scheduling),sort_keys=True,allow_nan=False))

if __name__ == '__main__':
    main()
