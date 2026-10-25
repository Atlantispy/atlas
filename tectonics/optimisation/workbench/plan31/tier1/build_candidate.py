"""Construct the authenticated S1A selection with corrected Tier 1 query reporting.

Only a new source directory is written. No Atlas module or scientific workload
is executed. SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import types

PREFIX = 'tectonics/optimisation/workbench/plan31/tier1/'
MAP_SHA = '1591b434c4bdba6159e1c4405df7b6936e95e4f0df01abdd493868700ba315ac'
BASE_TOOL = 'tectonics/optimisation/workbench/plan30/s1a/build_candidate.py'
BASE_TOOL_SHA = '7618b5cf6d6f3210d36a882bf34429aba0318a9cb0f8ba32af5fc4b1f9640b59'
BASE_MAP = 'tectonics/optimisation/workbench/plan30/s1a/SOURCE-MAP.json'
BASE_MAP_SHA = '878ae56c72fcb47cea97f5d74cb42b737a1680dfe0e2e3ec8f1217d54650bf45'
BASE_SELECTION_SHA = '8a754a838852aaead5c50b1b106fb71785dc4e0dec51b69f042c8993378298e8'
FLAGS = ('runtime_admission', 'default_changed', 'scientific_acceptance',
         'interval_authority', 'selected', 'enablement')
MEMBERS = ('src/atlas_tectonics/integration_endpoint_checkpoints.py',
           'helpers/run_fresh_interval.py', 'helpers/run_prepared_restart.py')


def pinned(raw, expected, label):
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Pinned source changed: ' + label)
    return raw


def module(path, raw, name):
    result = types.ModuleType(name)
    result.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), result.__dict__)
    return result


def load(repo):
    base = module(repo / BASE_TOOL, pinned((repo / BASE_TOOL).read_bytes(),
                  BASE_TOOL_SHA, BASE_TOOL), 'tier1_s1a_builder')
    combined = module(repo / base.BASE_TOOL, pinned((repo / base.BASE_TOOL).read_bytes(),
                      base.BASE_TOOL_SHA, base.BASE_TOOL), 'tier1_plan39_builder')
    utilities = combined.shared(repo)
    utilities.inside(Path(repo.anchor), repo.relative_to(repo.anchor).as_posix())
    pinned(utilities.read_source(repo, BASE_MAP), BASE_MAP_SHA, BASE_MAP)
    map_path = PREFIX + 'SOURCE-MAP.json'
    mapping = utilities.read_map(pinned(utilities.read_source(repo, map_path), MAP_SHA, map_path))
    if (mapping.get('schema') != 'atlas.public.plan31.tier1.source-transform.r2'
            or mapping.get('base_builder') != dict(path=BASE_TOOL, sha256=BASE_TOOL_SHA)
            or mapping.get('base_source_map') != dict(path=BASE_MAP, sha256=BASE_MAP_SHA)
            or mapping.get('base_selection_sha256') != BASE_SELECTION_SHA
            or any(mapping.get(key) is not False for key in FLAGS)
            or tuple(row['member'] for row in mapping.get('rows', [])) != MEMBERS):
        raise ValueError('Tier 1 source contract, membership or authority differs')
    modules = []
    for filename in ('apply_t1.py', 'query_store_prerequisite.py'):
        path = PREFIX + filename
        raw = pinned(utilities.read_source(repo, path), mapping['transforms'][filename], path)
        modules.append(module(repo / path, raw, 'tier1_' + filename.removesuffix('.py')))
    return base, utilities, mapping, *modules


def derive(raws, mapping, tier, prerequisite):
    if set(raws) != set(MEMBERS):
        raise ValueError('Exactly the three Tier 1 receiving inputs are required')
    for row in mapping['rows']:
        pinned(raws[row['member']], row['public_base_sha256'], row['member'])
    owner, fresh, restart = (raws[name] for name in MEMBERS)
    crlf = restart.count(b'\r\n')
    if crlf not in (0, restart.count(b'\n')) or restart.count(b'\r') != crlf:
        raise ValueError('Mixed restart line endings')
    newline = '\r\n' if crlf else '\n'
    restart = prerequisite.restart(restart.decode('utf-8').replace('\r\n', '\n'),
                                   fresh.decode('utf-8').replace('\r\n', '\n'))
    restart = restart.replace('\n', newline).encode('utf-8')
    outputs = {
        MEMBERS[0]: tier.edit(owner, tier.OWNER_EDITS, MEMBERS[0]),
        MEMBERS[1]: tier.edit(fresh, tier.RUNNER_EDITS, MEMBERS[1]),
        MEMBERS[2]: tier.edit(restart, tier.RUNNER_EDITS, MEMBERS[2]),
    }
    for row in mapping['rows']:
        pinned(outputs[row['member']], row['public_output_sha256'], row['member'])
    definitions = tier.segments(outputs[MEMBERS[1]])
    if len(definitions) != 4 or tier.segments(outputs[MEMBERS[2]]) != definitions:
        raise ValueError('Fresh and restart query definitions differ')
    return outputs


def materialise(repo, destination):
    repo, destination = Path(repo).absolute(), Path(destination).absolute()
    base, utilities, mapping, tier, prerequisite = load(repo)
    utilities.inside(Path(destination.anchor), destination.relative_to(destination.anchor).as_posix())
    utilities.refuse_existing(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.tier1-source-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'source'
        base.materialise(repo, stage)
        prior = utilities.read_map(utilities.read_source(stage, 'SOURCE-MANIFEST.json'))
        if (prior.get('schema') != 'atlas.public.plan30.s1a.materialised-source.r3'
                or prior.get('selection_sha256') != BASE_SELECTION_SHA
                or prior.get('source_map_sha256') != BASE_MAP_SHA
                or len(prior.get('files', {})) != 694
                or any(prior.get(key) is not False for key in FLAGS)):
            raise ValueError('Authenticated S1A parent manifest differs')
        raws = {member: utilities.read_source(stage, member) for member in MEMBERS}
        outputs = derive(raws, mapping, tier, prerequisite)
        files = dict(prior['files'])
        for member, raw in outputs.items():
            utilities.inside(stage, member).write_bytes(raw)
            files[member] = hashlib.sha256(raw).hexdigest()
        result = dict(schema='atlas.public.plan31.tier1.materialised-source.r2',
            status='INTEGRATED_SOURCE_COMPONENT_NOT_QUALIFIED', source_members=len(files),
            source_map_sha256=MAP_SHA, base_source_map_sha256=BASE_MAP_SHA,
            base_selection_sha256=BASE_SELECTION_SHA,
            selection_sha256=utilities.generation({'member': 'source/' + name, 'public_sha256': pin}
                                                  for name, pin in files.items()),
            files=files, **dict.fromkeys(FLAGS, False))
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
        parser.exit(1, 'Tier 1 source construction refused: ' + str(error) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
