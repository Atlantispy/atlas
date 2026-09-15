"""Explicit shared-store import/fork/export and one unchanged R4 proposed interval."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/terrain_reconstruction_r1/runtime'))
from work.generator_runtime_r12 import _raw
from work.native_terrain_r3.session import _adapt
from work.native_terrain_r4 import runner as retained, scheduling as old_schedule
from . import session as s, provenance as p, history as h

_SOURCE = _raw(Path(__file__))
if sys._getframe().f_code != compile(_SOURCE, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed native R5 CLI differs from source')
_R12_EXECUTED_SHA256 = hashlib.sha256(_SOURCE).hexdigest()


def latest_accepted_row(history):
    if type(history) is not h.History:
        raise ValueError('authenticated shared native history required')
    h._verify_source()
    return h._parse(history._raw(history._entries[-1], authenticate_summary=True)) if len(history) else None


class _Schedule:
    propose_duration = staticmethod(_adapt(old_schedule.propose_duration, latest_accepted_row=latest_accepted_row))


_Schedule.propose_duration.__kwdefaults__ = dict(old_schedule.propose_duration.__kwdefaults__)


step = _adapt(retained.step, s=s, p=p, scheduling=_Schedule)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    migrate = commands.add_parser('migrate')
    migrate.add_argument('--input', type=Path, required=True)
    migrate.add_argument('--output', type=Path, required=True)
    migrate.add_argument('--store', type=Path, required=True)
    for command in ('fork', 'export'):
        sub = commands.add_parser(command)
        sub.add_argument('--input', type=Path, required=True)
        sub.add_argument('--output', type=Path, required=True)
    advance = commands.add_parser('step')
    advance.add_argument('--checkpoint', type=Path, required=True)
    advance.add_argument('--variant', choices=('coarse', 'primary'), required=True)
    args = parser.parse_args()
    if args.command == 'step':
        print(json.dumps(step(args.checkpoint, args.variant)))
        return
    if args.output.exists():
        raise ValueError('new destination required; predecessors remain untouched')
    if args.command == 'migrate':
        saved = s.save(args.output, s.import_r4(args.input, args.store))
    elif args.command == 'fork':
        saved = s.fork(s.load(args.input), args.output)
    else:
        saved = s.export(s.load(args.input), args.output)
    print(json.dumps({'status': 'R5_' + args.command.upper() + '_SAVED', 'path': saved.control_path,
                      'source_status': 'WORKING NON-CANON', 'integrity_schema': p.INTEGRITY_SCHEMA,
                      'body_commitment_sha256': saved.wrapper['envelope']['body_sha256']}))


if __name__ == '__main__':
    main()
