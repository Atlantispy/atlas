"""User-facing bounded execution entrypoint; full reference remains available."""
import argparse
from pathlib import Path
import json
import time
import sys
import hashlib

from . import integration, provenance

_ENTRY_RAW = provenance.checked(Path(__file__))
if sys._getframe().f_code != compile(_ENTRY_RAW, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed R12 entrypoint differs from current source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_ENTRY_RAW).hexdigest()


def preflight(args):
    """Reject basic invalid requests without loading science or creating files.

    Authoritative path/JSON/schema checks still run through the sealed reader.
    This inexpensive screen is not a replacement for scientific validation.
    """
    integration.validate_options(workers=args.workers, memory_budget_mb=args.memory_budget_mb,
                                 worker_memory_mb=args.worker_memory_mb, stop_after=args.stop_after)
    if not args.output.is_absolute() or '..' in args.output.parts:
        raise ValueError('--output must be an absolute path without parent traversal')
    if args.output.exists() or args.output.is_symlink():
        raise ValueError('--output must name a new result directory')
    for option in ('recipe', 'parent', 'resume'):
        path = getattr(args, option)
        if path is not None:
            value = json.loads(provenance.checked(path).decode('utf-8'))
            if type(value) is not dict:
                raise ValueError('--' + option + ' must contain a JSON object')
    if args.cache is not None and not args.no_cache and not args.reference:
        if not args.cache.is_absolute() or '..' in args.cache.parts or args.cache == Path(args.cache.anchor):
            raise ValueError('--cache must be an absolute non-root path without parent traversal')
        if args.cache.is_symlink() or args.cache.exists() and not args.cache.is_dir():
            raise ValueError('--cache must name a directory, not a file or link')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New result directory')
    parser.add_argument('--recipe', type=Path)
    parser.add_argument('--parent', type=Path)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--workers', type=int, default=1,
                        help='Requested independent workers; measured bounded-reference default is 1')
    parser.add_argument('--memory-budget-mb', type=int, default=1024)
    parser.add_argument('--worker-memory-mb', type=int, default=512)
    parser.add_argument('--stop-after', type=int)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--reference', action='store_true', help='Unchanged uncached serial/replay R11 path')
    args = parser.parse_args(argv)
    try:
        preflight(args)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    bundle = provenance.load_science()
    s = bundle.storage
    root = s.plain_path(args.output)
    recipe = bundle.reference.recipe(bundle) if args.recipe is None else s.read_json(args.recipe)
    parent = None if args.parent is None else s.read_json(args.parent)
    resume = None if args.resume is None else s.read_json(args.resume)
    cache = (provenance.TASK / 'outputs/generator-runtime-r12/cache'
             if args.cache is None else args.cache)
    if args.no_cache:
        cache = None
    started = time.perf_counter()
    if args.reference:
        scientific = bundle.run_workflow(recipe, stop_after=args.stop_after, resume=resume,
                                          supplied_parent=parent)
        result = {'scientific': scientific,
                  'execution': {'mode': 'UNCHANGED_R11_REFERENCE',
                                'elapsed_wall_seconds': time.perf_counter() - started}}
    else:
        result = integration.run_workflow(recipe, bundle=bundle, cache_root=cache,
            workers=args.workers, memory_budget_mb=args.memory_budget_mb,
            worker_memory_mb=args.worker_memory_mb, stop_after=args.stop_after,
            resume=resume, supplied_parent=parent)
    # Failed validation/computation must not leave an empty result directory.
    # Recheck the destination after work; never overwrite a concurrently created path.
    root = s.plain_path(root)
    root.mkdir(parents=True, exist_ok=False)
    verifier = bundle.module('verify')
    record = verifier.persist_workflow(bundle, root / 'scientific', result['scientific'])
    saved = verifier.read_workflow(bundle, record)
    if saved != result['scientific']:
        raise ValueError('saved result differs')
    s.write_json(root / 'execution.json', result['execution'])
    s.write_json(root / 'scientific-record.json', record)
    s.write_json(root / 'input-recipe.json', recipe)
    cache_warnings = result['execution'].get('cache_warnings', [])
    for warning in cache_warnings:
        print('Warning: ' + warning['message'], file=sys.stderr)
    print(json.dumps({'status': saved['status'], 'path': str(root),
                      'elapsed_wall_seconds': result['execution']['elapsed_wall_seconds'],
                      'cache_warnings': cache_warnings,
                      'cache_warning_scope': result['execution'].get('cache_statistics_scope', 'NOT_APPLICABLE'),
                      'whole_generator_complete': False}), flush=True)


if __name__ == '__main__':
    main()
