"""Construct the explicit Plan26 source component over the pinned Tier1 parent.

Only a new source tree is written. No Atlas module or scientific workload is
imported. SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
import tempfile
import types

HERE = Path(__file__).resolve().parent
MAP_SHA = '99457ac140c986bfa71edf8cc1254a9bba822a6f3d641261cc3728475e3336bd'
BASE_TOOL = 'tectonics/optimisation/workbench/plan31/tier1/build_candidate.py'
BASE_TOOL_SHA = '8d93c1ba72646b218f76e18df394115442258a1715341da5056b17d4811a961c'
BASE_MAP = 'tectonics/optimisation/workbench/plan31/tier1/SOURCE-MAP.json'
BASE_MAP_SHA = '1591b434c4bdba6159e1c4405df7b6936e95e4f0df01abdd493868700ba315ac'
BASE_SELECTION_SHA = '653f7b7f18049e1a33530927c8b366e8b21199be3f1dd22282efd9662e63e431'
FLAGS = ('runtime_admission', 'default_changed', 'scientific_acceptance',
         'interval_authority', 'selected', 'enablement')
MEMBERS = ('helpers/reopen_prepared_restart.py', 'helpers/reopen_fresh_restart.py',
           'helpers/run_prepared_restart.py')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned(raw, expected, label):
    if digest(raw) != expected:
        raise ValueError('Pinned source changed: ' + label)
    return raw


def module(path, raw, name):
    result = types.ModuleType(name)
    result.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), result.__dict__)
    return result


def load(repo):
    parent = module(repo / BASE_TOOL, pinned((repo / BASE_TOOL).read_bytes(), BASE_TOOL_SHA, BASE_TOOL),
                    'plan26_tier1_parent')
    _, utilities, _, _, _ = parent.load(repo)
    utilities.inside(Path(repo.anchor), repo.relative_to(repo.anchor).as_posix())
    mapping = utilities.read_map(pinned(utilities.read_source(HERE, 'SOURCE-MAP.json'), MAP_SHA, 'SOURCE-MAP.json'))
    if (mapping.get('schema') != 'atlas.public.plan26.source-transform.r1'
            or mapping.get('base_builder') != dict(path=BASE_TOOL, sha256=BASE_TOOL_SHA)
            or mapping.get('base_source_map') != dict(path=BASE_MAP, sha256=BASE_MAP_SHA)
            or mapping.get('base_selection_sha256') != BASE_SELECTION_SHA
            or tuple(row['member'] for row in mapping.get('rows', [])) != MEMBERS
            or mapping.get('selected_source_members') != 694
            or any(mapping.get(key) is not False for key in FLAGS)):
        raise ValueError('Plan26 source membership, parent or authority differs')
    dependency = mapping['strict_diff_applier']
    raw = pinned(utilities.read_source(repo, dependency['path']), dependency['sha256'], dependency['path'])
    applier = module(repo / dependency['path'], raw, 'plan26_existing_strict_diff')
    return parent, utilities, mapping, applier


def validate_parent(record, mapping, utilities):
    files = record.get('files')
    if (record.get('schema') != 'atlas.public.plan31.tier1.materialised-source.r2'
            or record.get('status') != 'INTEGRATED_SOURCE_COMPONENT_NOT_QUALIFIED'
            or record.get('source_map_sha256') != BASE_MAP_SHA
            or record.get('selection_sha256') != BASE_SELECTION_SHA
            or type(files) is not dict or len(files) != 694
            or utilities.generation({'member': 'source/' + name, 'public_sha256': pin}
                                    for name, pin in files.items()) != BASE_SELECTION_SHA
            or any(record.get(key) is not False for key in FLAGS)):
        raise ValueError('Authenticated 694-member Tier1 parent differs')
    for row in mapping['rows']:
        if files.get(row['member']) != row['public_base_sha256']:
            raise ValueError('Parent receiving input differs: ' + row['member'])
    return files


def derive(raws, mapping, utilities, applier):
    if set(raws) != set(MEMBERS):
        raise ValueError('Exactly three Plan26 receiving members required')
    outputs = {}
    for row in mapping['rows']:
        name = row['member']
        raw = pinned(raws[name], row['public_base_sha256'], name)
        patch = pinned(utilities.read_source(HERE, row['diff']), row['diff_sha256'], row['diff'])
        payload = pinned(utilities.read_source(HERE, row['payload']), row['public_output_sha256'], row['payload'])
        if b'\r' in raw or b'\r' in payload:
            raise ValueError('Public port requires the declared LF source identities')
        if applier.apply_diff(raw, patch, name) != payload:
            raise ValueError('Strict diff and packaged Plan26 output differ: ' + name)
        outputs[name] = payload
    return outputs


def materialise(repo, parent_root, destination):
    repo, parent_root, destination = Path(repo).absolute(), Path(parent_root).absolute(), Path(destination).absolute()
    canonical_output = destination.resolve()
    for source in (repo, parent_root, HERE):
        canonical_source = source.resolve()
        if (canonical_output == canonical_source
                or canonical_output.is_relative_to(canonical_source)
                or canonical_source.is_relative_to(canonical_output)):
            raise ValueError('Output overlaps read-only source: ' + str(source))
    _parent, utilities, mapping, applier = load(repo)
    utilities.inside(Path(destination.anchor), destination.relative_to(destination.anchor).as_posix())
    utilities.refuse_existing(destination)
    utilities.inside(Path(parent_root.anchor), parent_root.relative_to(parent_root.anchor).as_posix())
    prior = utilities.read_map(utilities.read_source(parent_root, 'SOURCE-MANIFEST.json'))
    before = validate_parent(prior, mapping, utilities)
    actual_parent = {}
    for path in parent_root.rglob('*'):
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked parent source member')
        if path.is_file() and path != parent_root / 'SOURCE-MANIFEST.json':
            name = path.relative_to(parent_root).as_posix()
            actual_parent[name] = digest(utilities.read_source(parent_root, name))
    if actual_parent != before:
        raise ValueError('Parent file inventory or loaded source bytes differ')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.plan26-source-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'source'
        shutil.copytree(parent_root, stage)
        raws = {member: utilities.read_source(stage, member) for member in MEMBERS}
        outputs = derive(raws, mapping, utilities, applier)
        files = dict(before)
        for name, raw in outputs.items():
            utilities.inside(stage, name).write_bytes(raw)
            files[name] = digest(raw)
        actual = {p.relative_to(stage).as_posix(): digest(p.read_bytes()) for p in stage.rglob('*')
                  if p.is_file() and p != stage / 'SOURCE-MANIFEST.json'}
        if (actual != files or len(files) != 694 or
                any(files[name] != pin for name, pin in before.items() if name not in MEMBERS)):
            raise ValueError('Plan26 output differs beyond its three declared members')
        result = dict(schema='atlas.public.plan26.materialised-source.r1',
            status='INTEGRATED_SOURCE_COMPONENT_NOT_QUALIFIED', source_members=694,
            source_map_sha256=MAP_SHA, base_source_map_sha256=BASE_MAP_SHA,
            base_selection_sha256=BASE_SELECTION_SHA,
            selection_sha256=utilities.generation({'member': 'source/' + name, 'public_sha256': pin}
                                                 for name, pin in files.items()),
            changed_members=list(MEMBERS), unchanged_members=691, files=files,
            **dict.fromkeys(FLAGS, False))
        (stage / 'SOURCE-MANIFEST.json').write_text(json.dumps(result, indent=2) + '\n',
                                                   encoding='utf8', newline='\n')
        utilities.refuse_existing(destination)
        stage.rename(destination)
    return {key: value for key, value in result.items() if key != 'files'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = materialise(args.repo, args.parent, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, 'Plan26 source construction refused: ' + str(error) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
