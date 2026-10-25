"""Materialise the explicit S1A repair over the public Plan39 source selection.

Only a new source directory is written. Defaults, installed packages and execution
authority are unchanged. SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import types

PREFIX = 'tectonics/optimisation/workbench/plan30/s1a/'
MAP_SHA = '878ae56c72fcb47cea97f5d74cb42b737a1680dfe0e2e3ec8f1217d54650bf45'
BASE_TOOL = 'tectonics/optimisation/workbench/plan39/build_selection.py'
BASE_TOOL_SHA = 'c993edceedfd3002fa50655a799de16519f8d960e9717b232c8e16f4516bd892'
FLAGS = ('runtime_admission', 'default_changed', 'scientific_acceptance', 'interval_authority',
         'selected', 'enablement')


def pinned(raw, expected, label):
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Pinned source changed: ' + label)
    return raw


def module(path, raw, name):
    result = types.ModuleType(name)
    result.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), result.__dict__)
    return result


def materialise(repo, destination):
    repo, destination = Path(repo).absolute(), Path(destination).absolute()
    base = module(repo / BASE_TOOL, pinned((repo / BASE_TOOL).read_bytes(), BASE_TOOL_SHA, BASE_TOOL),
                  's1a_plan39_builder')
    utilities = base.shared(repo)
    for path in (repo, destination):
        utilities.inside(Path(path.anchor), path.relative_to(path.anchor).as_posix())
    utilities.refuse_existing(destination)
    map_path = PREFIX + 'SOURCE-MAP.json'
    mapping = utilities.read_map(pinned(utilities.read_source(repo, map_path), MAP_SHA, map_path))
    if (mapping.get('schema') != 'atlas.public.plan30.s1a.source-overlay.r3'
            or any(mapping.get(key) is not False for key in FLAGS)
            or mapping.get('base_builder') != dict(path=BASE_TOOL, sha256=BASE_TOOL_SHA)
            or mapping.get('base_source_map') != dict(path=base.PREFIX + 'SOURCE-MAP.json', sha256=base.MAP_SHA)):
        raise ValueError('S1A parent, schema or authority differs')
    port_path = PREFIX + 'port_s1a.py'
    port = module(repo / port_path, pinned(utilities.read_source(repo, port_path), mapping['port_sha256'], port_path),
                  's1a_public_port')
    entries = utilities.entry_index(repo, mapping['entries'])
    if set(entries) != {'source/' + row for row in port.ROWS}:
        raise ValueError('S1A overlay membership differs')
    expected_rows = {row: dict(kind=k, before=b, after=a, diff=d, diff_sha256=h)
                     for row, (k, b, a, d, h) in port.ROWS.items()}
    if mapping.get('rows') != expected_rows or mapping.get('dependencies') != port.DEPENDENCIES:
        raise ValueError('S1A row or dependency contract differs')
    for member, entry in entries.items():
        row = member.removeprefix('source/')
        if entry['public_path'] != PREFIX + member or entry['public_sha256'] != port.ROWS[row][2]:
            raise ValueError('S1A source mapping differs: ' + member)
        pinned(utilities.read_source(repo, entry['public_path']), entry['public_sha256'], member)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.s1a-source-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'source'
        base.materialise(repo, stage)
        manifest = utilities.read_map(utilities.read_source(stage, 'SOURCE-MANIFEST.json'))
        outputs = port.derive(stage / 'helpers')
        files = dict(manifest['files'])
        for row, raw in outputs.items():
            utilities.inside(stage, row).write_bytes(raw)
            files[row] = hashlib.sha256(raw).hexdigest()
        if len(files) != 694:
            raise ValueError('S1A materialised membership differs')
        result = dict(schema='atlas.public.plan30.s1a.materialised-source.r3',
            status='INTEGRATED_SOURCE_COMPONENT_NOT_QUALIFIED', source_map_sha256=MAP_SHA,
            base_source_map_sha256=base.MAP_SHA, base_selection_sha256=manifest['selection_sha256'],
            selection_sha256=utilities.generation({'member': 'source/' + name, 'public_sha256': pin}
                                                  for name, pin in files.items()),
            source_members=len(files), files=files, **dict.fromkeys(FLAGS, False))
        (stage / 'SOURCE-MANIFEST.json').write_text(json.dumps(result, indent=2) + '\n',
                                                   encoding='utf-8', newline='\n')
        utilities.refuse_existing(destination)
        stage.rename(destination)
    return {key: value for key, value in result.items() if key != 'files'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = materialise(args.repo, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, 'S1A source construction refused: ' + str(error) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
