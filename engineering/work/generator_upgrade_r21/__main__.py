"""Bounded agriculture runner: current coupled soil, or distinct reduced oracle."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from work.generator_runtime_r12 import _raw

_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed R21 runner differs from source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()

from . import output, pipeline


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--input', type=Path, help='explicit bounded working-scenario JSON')
    source.add_argument('--reference', choices=('coupled', 'seasonal', 'exclusion', 'dry'), default='coupled')
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('outputs/generator-upgrade-r21'))
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        if args.input:
            if args.input.stat().st_size > 8*1024*1024:
                raise ValueError('scenario exceeds existing 8 MiB input bound')
            scenario = json.loads(args.input.read_text(encoding='utf-8'))
        elif args.reference == 'coupled':
            from . import reference
            scenario = reference.scenario()
        else:
            from . import reduced_reference
            scenario = reduced_reference.scenario(args.reference)
        result = pipeline.run(scenario, cache=not args.no_cache)
        product = output.product(result, expected_context=scenario['context'])
        science_path = output.save(args.output, 'science', result['scientific'])
        product_path = output.save(args.output, 'product', product)
        receipt = {'status': result['scientific']['status'], 'execution': result['execution'],
            'scientific_sha256': result['scientific_sha256'], 'scientific_path': str(science_path),
            'product_path': str(product_path), 'reporting': result['reporting'],
            'elapsed_seconds': time.perf_counter()-started,
            'scope': 'WORKING NON-CANON ENGINEERING; NOT ACTUAL DIADEM FARM PLACEMENT'}
        receipt_path = output.save(args.output, 'run', receipt)
        print(json.dumps({'status': receipt['status'], 'elapsed_seconds': receipt['elapsed_seconds'],
                          'receipt': str(receipt_path), 'stages': result['reporting']}))
        return 0 if receipt['status'] == 'MODELLED' else 2
    except Exception as exc:
        print(json.dumps({'status': 'INCOMPLETE', 'error': type(exc).__name__+': '+str(exc),
                          'elapsed_seconds': time.perf_counter()-started}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
