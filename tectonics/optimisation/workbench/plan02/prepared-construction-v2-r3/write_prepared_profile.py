"""Pinned profile orchestration only; no launch, store access or invented reviews.

Run only after authorised source construction, real identity measurement and
explicit complete-package review. Imports this selected assembler, not Atlas.
All actual source/native/evidence reads belong to its write_review contract.
"""
import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys


def pinned(path, expected):
    raw = Path(path).read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError('explicit selected bytes differ: '+str(path))
    return raw


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assembler-sha256', required=True)
    p.add_argument('--selected-restart', type=Path)
    p.add_argument('--selected-restart-sha256')
    p.add_argument('--profile-output', type=Path)
    for flag in ('manifest-sha256', 'measurement-sha256', 'review-sha256',
                 'completed-query-directory', 'historical-root'):
        p.add_argument('--'+flag)
    for flag in ('target', 'measurement', 'review', 'output-directory'):
        p.add_argument('--'+flag, type=Path)
    args = p.parse_args(argv)
    path = Path(__file__).resolve().with_name('assemble_resumable.py')
    raw = pinned(path, args.assembler_sha256)
    spec = importlib.util.spec_from_file_location('assemble_resumable', path)
    module = importlib.util.module_from_spec(spec)
    if 'assemble_resumable' in sys.modules:
        raise ValueError('assembler already imported; use a fresh source-selected process')
    sys.modules['assemble_resumable'] = module
    exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    legacy = (args.manifest_sha256, args.measurement_sha256, args.review_sha256,
              args.completed_query_directory, args.historical_root, args.target,
              args.measurement, args.review, args.output_directory)
    if args.selected_restart is not None:
        if any(value is not None for value in legacy):
            raise ValueError('selected receiving construction cannot mix legacy profile arguments')
        return module.main(['--selected-restart', str(args.selected_restart),
                            '--selected-restart-sha256', args.selected_restart_sha256 or '',
                            '--out', str(args.profile_output) if args.profile_output is not None else ''])
    if any(value is None for value in legacy) or args.selected_restart_sha256 is not None or args.profile_output is not None:
        raise ValueError('complete legacy profile arguments or one selected construction are required')
    measurement = json.loads(pinned(args.measurement, args.measurement_sha256))
    pinned(args.review, args.review_sha256)
    result = module.write_review(args.target, args.manifest_sha256, measurement,
        historical_root=args.historical_root,
        output_directory=args.output_directory, completed_query_directory=args.completed_query_directory,
        review_record=args.review, review_sha256=args.review_sha256)
    print(json.dumps(dict(status='PROFILE_WRITTEN_NO_RUN_AUTHORITY', files=result), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
