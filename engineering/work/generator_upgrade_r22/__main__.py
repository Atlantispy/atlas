"""Run an explicitly bound R11/R12 recipe using implemented R22 producers."""
import argparse
import json
from pathlib import Path
from . import registry

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('recipe', type=Path)
parser.add_argument('--cache-root', type=Path)
parser.add_argument('--no-cache', action='store_true')
args = parser.parse_args()
raw = args.recipe.read_bytes()
if len(raw) > 8*1024*1024: raise ValueError('bounded recipe required')
print(json.dumps(registry.run(json.loads(raw), cache=not args.no_cache,
    cache_root=args.cache_root), sort_keys=True, allow_nan=False))
