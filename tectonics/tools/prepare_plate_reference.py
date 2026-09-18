#!/usr/bin/env python3
"""Explicit, pinned public-data acquisition and complete 3C-R1 reference checks.

No installer, credentials, Git operation, generator tuning, historical migration
or network access without --download. Existing source bytes are never overwritten.
The output directory should be dedicated to this dataset; failed acquisition does
not publish a partial directory. Dependencies are those already declared by Atlas.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.request import urlopen
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'src'))

# An incremental delivery omits unchanged baseline files by design. Diagnose a
# standalone overlay BEFORE package imports, rather than exposing a traceback or
# attempting to invent/download replacement modules. -B alone does not forbid
# reading pre-existing local bytecode, so use the verification runner's policy.
try:
    package = ROOT/'src'/'atlas_tectonics'
    required = ('__init__.py', '_validation.py', 'plate_reference_dataset.py',
                'plate_reference_acceptance.py', 'geometry.py', 'resources.py')
    if any(not (package/name).is_file() for name in required):
        raise ImportError('Incomplete Atlas checkout: apply the update over its baseline, '
                          'or use the complete self-contained delivery; no replacement modules are needed')
    if any(p.is_symlink() for p in (package, *package.parents)):
        raise ValueError('linked local source directories are refused')
    if next(package.rglob('*.pyc'), None) is not None:
        raise ValueError('local bytecode exists; use a clean source-only checkout')
    from atlas_tectonics.plate_reference_dataset import (source_manifest,verify_source_bytes,
        load_pb2002,ReferenceDataError,PB2002_FILES)
    from atlas_tectonics.plate_reference_acceptance import reference_dataset_report
except (ImportError, OSError, ValueError) as exc:
    if __name__ != '__main__':
        raise
    print(json.dumps({'status':'BLOCKED_REFERENCE_ACCEPTANCE','error':str(exc),
        'full_dataset_tested':False,'geological_model_accepted':False}),file=sys.stderr)
    raise SystemExit(2)


def acquire(destination: Path, *, opener=urlopen):
    """Fetch only the registered public source bytes; stage then publish all-or-none."""
    destination=destination.absolute()
    if destination.exists():raise FileExistsError('dataset already exists; use --verify-only, never overwrite')
    if not destination.parent.is_dir():raise ReferenceDataError('create the dataset parent directory explicitly')
    if any(p.is_symlink() for p in (destination,*destination.parents)):
        raise ReferenceDataError('linked dataset paths are refused')
    # A unique claim prevents two local acquisitions racing the publication path.
    claim=destination.with_name(destination.name+'.preparing')
    fd=os.open(claim,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    staging=Path(tempfile.mkdtemp(prefix='.pb2002-',dir=destination.parent))
    try:
        for source in source_manifest()['files']:
            with opener(source['url'],timeout=30) as stream:
                final=urlparse(stream.geturl())
                if final.scheme!='https' or final.hostname!='raw.githubusercontent.com':
                    raise ReferenceDataError('unexpected data-download redirect')
                raw=stream.read(source['bytes']+1)
            verify_source_bytes(source['path'],raw)
            path=staging/source['path'];path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(raw)
        dataset=load_pb2002(staging)
        (staging/'SOURCE_MANIFEST.json').write_text(json.dumps(dataset.provenance(),indent=2)+'\n',encoding='utf-8')
        if destination.exists():raise FileExistsError('destination appeared during preparation')
        staging.rename(destination)
    finally:
        if staging.exists():shutil.rmtree(staging)
        claim.unlink(missing_ok=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--download',action='store_true',help='explicitly download pinned public PB2002 files')
    group.add_argument('--verify-only',action='store_true',help='offline; fail if any source is missing or changed')
    parser.add_argument('--data',type=Path,default=ROOT/'reference_data'/'pb2002')
    args=parser.parse_args(argv)
    if args.download:
        # Only the known default container directory is created as a convenience.
        if args.data==ROOT/'reference_data'/'pb2002':args.data.parent.mkdir(exist_ok=True)
        acquire(args.data)
    report=reference_dataset_report(load_pb2002(args.data))
    print(json.dumps(report,indent=2,allow_nan=False))
    return 0 if report['status']=='PASS_COMPLETE_REFERENCE_CHECKS' else 1


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,ImportError) as exc:
        print(json.dumps({'status':'BLOCKED_REFERENCE_ACCEPTANCE','error':str(exc),
            'full_dataset_tested':False,'geological_model_accepted':False}),file=sys.stderr)
        raise SystemExit(2)
