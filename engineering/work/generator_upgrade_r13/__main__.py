"""Run one source-bound coupled soil year from an explicit R13 recipe."""
import argparse
import hashlib
from pathlib import Path
import sys
from work.generator_runtime_r12 import _raw

_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed R13 CLI differs from current source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()

from . import storage, year
from work.generator_runtime_r12.store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--stop-after', type=int)
    parser.add_argument('--resume', type=Path, help='Previously saved R13 result directory')
    parser.add_argument('--progress', action='store_true', help='Report each independently verified complete event')
    cache = parser.add_mutually_exclusive_group()
    cache.add_argument('--cache', type=Path, help='Authenticated reuse store; default is short sibling directory c')
    cache.add_argument('--no-cache', action='store_true', help='Disable authenticated reuse; resumes replay the saved prefix')
    args = parser.parse_args(argv)
    try:
        output = storage.safe_output(args.output)
        spec = storage.read_json(args.recipe)
        year.validate(spec)
        if args.stop_after is not None and not 0 <= args.stop_after <= len(spec['events']):
            raise ValueError('bounded complete soil event cursor required')
        checkpoint = None if args.resume is None else storage.load(args.resume)['scientific']['checkpoint']
        binding = year.p.identity()
        if checkpoint is not None and (checkpoint['source_sha256'] != year.p.sha(binding)
                or checkpoint['recipe_sha256'] != year.p.sha(spec)):
            raise ValueError('soil checkpoint source/recipe binding differs; old results are preserved')
        cache_path = args.cache if args.cache is not None else output.parent/'c'
        if not args.no_cache and (cache_path.is_relative_to(output) or output.is_relative_to(cache_path)):
            raise ValueError('soil output and dedicated cache paths must not overlap')
        store = None if args.no_cache else Store(cache_path, year.p.sha(binding))
        journal = None

        def checkpoint_written(value):
            nonlocal journal
            if journal is None:
                journal = storage.Journal(output, spec)
            journal.commit(value)

        result = year.run(spec, stop_after=args.stop_after, resume=checkpoint,
                          progress=args.progress, store=store, on_checkpoint=checkpoint_written)
        if storage.load(output) != {'recipe': spec, **result}:
            raise ValueError('coupled soil final persisted readback differs')
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    scientific = result['scientific']
    print(year.p.encoded({'status': scientific['status'], 'output': str(output),
          'completed_events': scientific['completed_events'],
          'elapsed_wall_seconds': result['execution']['elapsed_wall_seconds'],
          'whole_diadem_year_verified': False}).decode())
    return 0 if scientific['status'] in ('MODELLED_COUPLED_SOIL_YEAR', 'STOPPED') else 1


if __name__ == '__main__':
    raise SystemExit(main())
