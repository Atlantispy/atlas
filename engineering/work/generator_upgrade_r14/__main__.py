"""Run explicit small ground-feedback recipes with the existing journal/cache."""
import argparse
import hashlib
from pathlib import Path
import sys
from work.generator_runtime_r12 import _raw

_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed R14 CLI differs from current source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()

from work.generator_runtime_r12.store import Store
from work.generator_upgrade_r13 import storage
from . import pipeline, provenance as p, reference


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--recipe', type=Path)
    source.add_argument('--reference', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stop-after', type=int)
    parser.add_argument('--resume', type=Path)
    cache = parser.add_mutually_exclusive_group()
    cache.add_argument('--cache', type=Path)
    cache.add_argument('--no-cache', action='store_true')
    args = parser.parse_args(argv)
    try:
        output = storage.safe_output(args.output)
        spec = reference.recipe() if args.reference else storage.read_json(args.recipe)
        pipeline.validate(spec)
        checkpoint = None if args.resume is None else storage.load(args.resume)['scientific']['checkpoint']
        binding = p.identity()
        if checkpoint is not None and (checkpoint['source_sha256'] != p.sha(binding)
                or checkpoint['recipe_sha256'] != p.sha(spec)):
            raise ValueError('ground source/recipe differs; old checkpoint preserved')
        cache_path = args.cache if args.cache is not None else output.parent/'c'
        if not args.no_cache and (cache_path.is_relative_to(output) or output.is_relative_to(cache_path)):
            raise ValueError('ground cache and output paths overlap')
        store = None if args.no_cache else Store(cache_path, p.sha(binding))
        journal = None
        def commit(result):
            nonlocal journal
            if journal is None:
                journal = storage.Journal(output, spec)
            journal.commit(result)
        result = pipeline.run(spec, stop_after=args.stop_after, resume=checkpoint,
                              store=store, on_checkpoint=commit)
        if storage.load(output) != {'recipe': spec, **result}:
            raise ValueError('ground final persisted readback differs')
    except (ValueError, OSError, ArithmeticError) as error:
        parser.error(str(error))
    science = result['scientific']
    print(p.encoded({'status': science['status'], 'completed_events': science['completed_events'],
        'reused_events': result['execution']['reused_events'], 'reason': science['reason'],
        'elapsed_wall_seconds': result['execution']['elapsed_wall_seconds'],
        'output': str(output), 'whole_diadem_year_verified': False}).decode())
    return 0 if science['status'] in ('MODELLED_GROUND_FEEDBACK', 'STOPPED') else 1


if __name__ == '__main__':
    raise SystemExit(main())
