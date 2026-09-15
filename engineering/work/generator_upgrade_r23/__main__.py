"""Run an explicitly R23-bound recipe; no automatic producer-source repinning."""
import argparse
import json
from pathlib import Path
from . import registry

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('recipe', type=Path)
parser.add_argument('--cache-root', type=Path)
parser.add_argument('--no-cache', action='store_true')
args = parser.parse_args()
with args.recipe.open('rb') as source:
    raw = source.read(8*1024*1024+1)
if len(raw) > 8*1024*1024:
    raise ValueError('bounded recipe required')
print(json.dumps(registry.run(json.loads(raw), cache=not args.no_cache,
    cache_root=args.cache_root), sort_keys=True, allow_nan=False))
