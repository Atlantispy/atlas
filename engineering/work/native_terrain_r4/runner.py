"""Explicit source-bound migration and one accepted interval; no automatic runs."""
import argparse
from dataclasses import replace
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/terrain_reconstruction_r1/runtime'))
from work.generator_runtime_r12 import _raw
from work.native_terrain_r3.runner import retained_runner
from . import provenance as p, session as s, scheduling

_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed native R4 CLI differs from source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()


def step(checkpoint, variant):
    run = retained_runner()
    current = s.load(checkpoint)
    context = run.frozen(variant)
    binding = current.wrapper['binding']
    if binding['variant'] != variant or binding['recipe_sha256'] != p.sha(context['recipe']):
        raise ValueError('frozen case or variant differs')
    envelope = current.wrapper['envelope']
    previous = envelope['body']['parent']['predecessor']['history_count']
    proposal = scheduling.propose_duration(envelope['body']['history'], F(1000) - run.elapsed(envelope),
        context['acceptance'], elapsed_years=run.elapsed(envelope), previous_count=previous)
    count = previous + len(envelope['body']['history']) + 1
    operation = variant + '-r2-' + str(count).zfill(4)
    acceptance = replace(context['acceptance'], max_halvings=proposal.remaining_halvings)
    started = time.perf_counter()
    following = current.advance(context['executor'], proposal.duration_years, acceptance, operation_id=operation)
    advance_seconds = time.perf_counter() - started
    following = replace(following, wrapper=dict(following.wrapper,
        cumulative_model_seconds=following.wrapper['cumulative_model_seconds'] + advance_seconds,
        last_execution={'proposal': proposal.evidence, 'parallelism': 'SERIAL_MEASURED_SELECTION'}))
    started = time.perf_counter()
    following = s.save(checkpoint, following)
    return {'status': 'ONE_INTERVAL_SAVED', 'source_status': 'WORKING NON-CANON',
        'elapsed_years': str(run.elapsed(following.wrapper['envelope'])),
        'advance_seconds': advance_seconds, 'save_seconds': time.perf_counter() - started,
        'integrity_schema': p.INTEGRITY_SCHEMA,
        'body_commitment_sha256': following.wrapper['envelope']['body_sha256'],
        'proposal': proposal.evidence, 'physical_acceptance': 'INCOMPLETE', 'production_selected': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    migrate = commands.add_parser('migrate')
    migrate.add_argument('--input', type=Path, required=True)
    migrate.add_argument('--output', type=Path, required=True)
    advance = commands.add_parser('step')
    advance.add_argument('--checkpoint', type=Path, required=True)
    advance.add_argument('--variant', choices=('coarse', 'primary'), required=True)
    args = parser.parse_args()
    if args.command == 'migrate':
        current = s.import_r3(args.input, args.output.parent)
        saved = s.save(args.output, current)
        print(json.dumps({'status': 'LOSSLESS_R4_MIGRATION_SAVED', 'path': str(args.output.resolve()),
                          'integrity_schema': p.INTEGRITY_SCHEMA,
                          'body_commitment_sha256': saved.wrapper['envelope']['body_sha256']}))
    else:
        print(json.dumps(step(args.checkpoint, args.variant)))


if __name__ == '__main__':
    main()
