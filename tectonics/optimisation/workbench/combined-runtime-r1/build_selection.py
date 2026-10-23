"""Build a complete, pinned combined source layout without executing Atlas.

This source-only route neither changes installed/default packages nor authenticates
historical results. Existing output directories and linked paths are refused.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
PREFIX = 'tectonics/optimisation/workbench/combined-runtime-r1/'
SHARED = 'tectonics/optimisation/workbench/plan18/build_selection.py'
SHARED_SHA = 'b537ce1c4da0be0fa2120fd2569a82c8af69c2e6a4ec8d3dc84ba519fe96c96b'
SCHEMA = 'atlas.public.combined-runtime.source-selection.r1'
MAP_SHA = '93ddf7a0fdc2c58d4f45e73d6f2615d37879411bc443534582c10f5d8c4ea2c2'
FLAGS = ('runtime_admission', 'default_changed', 'scientific_acceptance', 'interval_authority')


def shared(repo):
    path = repo / SHARED
    if hashlib.sha256(path.read_bytes()).hexdigest() != SHARED_SHA:
        raise ValueError('Shared source-construction tool changed')
    spec = importlib.util.spec_from_file_location('combined_source_utilities', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_map(repo, mapping, utilities):
    if mapping.get('schema') != SCHEMA or any(mapping.get(k) is not False for k in FLAGS):
        raise ValueError('Combined source selection cannot grant execution authority')
    entries = utilities.entry_index(repo, mapping.get('entries'))
    if (len(entries) != mapping.get('selected_members') or
            mapping.get('public_selection_sha256') != utilities.generation(mapping['entries'])):
        raise ValueError('Combined source membership or generation differs')
    for source in mapping['source_maps']:
        if utilities.digest(utilities.read_source(repo, source['path'])) != source['sha256']:
            raise ValueError('Historical source map changed')
    payloads = {}
    for member, row in entries.items():
        raw = utilities.read_source(repo, row['public_path'])
        if utilities.digest(raw) != row['public_sha256']:
            raise ValueError('Selected source changed: ' + member)
        payloads[member.removeprefix('source/')] = raw
    return payloads


def materialise(repo, destination):
    repo, destination = Path(repo).resolve(strict=True), Path(destination).absolute()
    utilities = shared(repo)
    utilities.refuse_existing(destination)
    # Validate all existing ancestors before creating a directory: do not write
    # through a symlink/junction supplied as the destination parent.
    utilities.inside(Path(destination.anchor), destination.relative_to(destination.anchor).as_posix())
    raw = utilities.read_source(repo, PREFIX + 'SOURCE-MAP.json')
    if utilities.digest(raw) != MAP_SHA:
        raise ValueError('Combined source map differs from reviewed bytes')
    mapping = utilities.read_map(raw)
    payloads = validate_map(repo, mapping, utilities)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.combined-selection-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'source'
        stage.mkdir()
        for member, data in payloads.items():
            target = utilities.inside(stage, member)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        manifest = dict(schema='atlas.public.combined-runtime.materialised-source.r1',
            source_map_sha256=MAP_SHA, selection_sha256=mapping['public_selection_sha256'],
            files={name: utilities.digest(data) for name, data in payloads.items()},
            **dict.fromkeys(FLAGS, False))
        (stage / 'SOURCE-MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n',
                                                   encoding='utf-8', newline='\n')
        utilities.refuse_existing(destination)
        stage.rename(destination)
    return dict(status='PASS', files=len(payloads), selection_sha256=mapping['public_selection_sha256'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = materialise(args.repo, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, 'Combined source construction refused: ' + str(error) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
