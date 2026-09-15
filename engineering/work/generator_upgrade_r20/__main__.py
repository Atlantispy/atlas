"""Run the bounded political district reference; caching is on by default."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from work.generator_runtime_r12 import _raw

_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed R20 CLI differs from current source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()

from . import output, pipeline, reference, provenance as p


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('outputs/generator-upgrade-r20'))
    args = parser.parse_args(argv)
    start = time.perf_counter()
    try:
        physical = reference.physical()
        result = pipeline.run(physical, reference.political, cache=not args.no_cache)
        product = output.product(result, expected_context=physical['context'])
        scientific_path = output.save(args.output, 'scientific', result['scientific'])
        product_path = output.save(args.output, 'product', product)
        reporting = {'status': result['scientific']['status'], 'execution': result['execution'],
            'scientific_sha256': p.sha(result['scientific']), 'scientific_path': str(scientific_path.resolve()),
            'product_path': str(product_path.resolve()), 'reporting': result['reporting'],
            'elapsed_wall_seconds': time.perf_counter()-start,
            'scope': 'SYNTHETIC TEST / WORKING NON-CANON METHOD; NOT ACTUAL DIADEM MAP'}
        receipt = output.save(args.output, 'run', reporting)
        print(json.dumps({'status': reporting['status'], 'elapsed_wall_seconds': reporting['elapsed_wall_seconds'],
                          'receipt': str(receipt.resolve()), 'reporting': result['reporting']}))
        return 0 if reporting['status'] == 'MODELLED' else 2
    except Exception as exc:
        print(json.dumps({'status': 'INCOMPLETE', 'error': type(exc).__name__+': '+str(exc),
                          'elapsed_wall_seconds': time.perf_counter()-start}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
