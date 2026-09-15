"""Explicit native-case migration/one-step runner; never replaces R1/R2 controls."""
import argparse
from dataclasses import replace
from fractions import Fraction as F
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/terrain_reconstruction_r1/runtime'))
from work.generator_runtime_r12 import _CapturedLoader, _raw
from . import session as s, provenance as p

_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed R3 CLI differs from current source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()

RETAINED_RUNNER_SHA = '87e962448b36191ad9d77d2d5aebb2b577bf7ac2a2d45150841e043369118288'


def retained_runner():
    path = ROOT / 'outputs/native-terrain-r2/run.py'
    if hashlib.sha256(_raw(path)).hexdigest() != RETAINED_RUNNER_SHA:
        raise ValueError('retained case runner differs; no silent source adoption')
    name = 'native_r3_retained_case_runner'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path, loader=_CapturedLoader(path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    module = sys.modules[name]
    if getattr(module, '_R12_EXECUTED_SHA256', None) != RETAINED_RUNNER_SHA:
        raise ValueError('executed case runner differs')
    return module


def step(checkpoint, variant):
    run = retained_runner()
    current = s.load(checkpoint)
    context = run.frozen(variant)
    binding = current.wrapper['binding']
    if binding['variant'] != variant or binding['recipe_sha256'] != p.sha(context['recipe']):
        raise ValueError('frozen case/variant differs from imported checkpoint')
    envelope = current.wrapper['envelope']
    duration = min(F(5), F(1000) - run.elapsed(envelope))
    if duration <= 0:
        raise ValueError('already at target; no further step')
    count = envelope['body']['parent']['predecessor']['history_count'] + len(envelope['body']['history']) + 1
    operation = variant + '-r2-' + str(count).zfill(4)
    started = time.perf_counter()
    following = current.advance(context['executor'], duration, context['acceptance'], operation_id=operation)
    advance_seconds = time.perf_counter() - started
    wrapper = dict(following.wrapper, cumulative_model_seconds=following.wrapper['cumulative_model_seconds'] + advance_seconds)
    following = replace(following, wrapper=wrapper)
    saving = time.perf_counter()
    following = s.save(checkpoint, following)
    return {'status': 'ONE_INTERVAL_SAVED', 'source_status': 'WORKING NON-CANON',
            'elapsed_years': str(run.elapsed(following.wrapper['envelope'])),
            'advance_seconds': advance_seconds, 'save_seconds': time.perf_counter() - saving,
            'body_sha256': following.wrapper['envelope']['body_sha256'],
            'physical_acceptance': 'INCOMPLETE', 'production_selected': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    migrate = sub.add_parser('migrate')
    migrate.add_argument('--input', type=Path, required=True)
    migrate.add_argument('--output', type=Path, required=True)
    advance = sub.add_parser('step')
    advance.add_argument('--checkpoint', type=Path, required=True)
    advance.add_argument('--variant', choices=('primary', 'coarse'), required=True)
    args = parser.parse_args()
    if args.command == 'migrate':
        if args.output.exists() or args.output.parent == args.input.parent:
            raise ValueError('migration requires a separate new output control')
        current = s.import_legacy(args.input, args.output.parent)
        saved = s.save(args.output, current)
        print(json.dumps({'status': 'LOSSLESS_MIGRATION_SAVED', 'path': str(args.output.resolve()),
                          'body_sha256': saved.wrapper['envelope']['body_sha256']}))
    else:
        print(json.dumps(step(args.checkpoint, args.variant)))


if __name__ == '__main__':
    main()
