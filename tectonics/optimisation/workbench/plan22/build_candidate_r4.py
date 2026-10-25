"""Build a complete public Plan22 L3 candidate in a NEW directory.

The unchanged legacy Plan21 builder supplies its complete 646-member public selection.
The accepted current port-r3 reader/test and existing published mesh yield 647 source files, with every other
member retained. This differs from the private D10 parent p20c-r4: construction
of this public candidate grants no runtime admission or L3 enablement.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import types


PREFIX = 'tectonics/optimisation/workbench/plan22/'
BASE_TOOL = 'tectonics/optimisation/workbench/plan21/build_selection.py'
BASE_TOOL_SHA = '704d73ad5caa35ea8630cd0db918d03243ff8d7a11f85f709f7e4e89428b877d'
MAP_FILE = 'SOURCE-MAP-r4.json'
MAP_SHA = 'b90e5eecc707cc9b5ee6370e57604fc81b2a02c56cfd0119aab22413aa5304bb'  # Exact current SOURCE-MAP-r4.json; candidate authority remains false.
FROZEN = True  # Owner-frozen inputs; implementation acceptance remains separate.
SCHEMA = 'atlas.public.plan22.source-map.r1'
IDENTITY_KIND = 'NEW_PUBLIC_SOURCE_OVERLAY_NOT_RUNTIME_BINDING'
BASE_COUNTS = {'selected_native_files': 240, 'selected_helper_files': 406}
COUNTS = {'selected_native_files': 240, 'selected_helper_files': 407}
FLAGS = ('selected', 'enablement', 'runtime_admission', 'default_changed',
         'scientific_acceptance', 'interval_authority', 'installed_package_changed',
         'public_runtime_compatibility', 'runtime_policy_adopted', 's9_selected')
PUBLIC_PATHS = {'source/helpers/record_views.py': 'tectonics/optimisation/workbench/plan21/receiving-l3-r3/helpers/record_views.py', 'source/helpers/mesh_tables.py': 'tectonics/optimisation/workbench/plan22/source/helpers/mesh_tables.py', 'source/helpers/test_l3_carried_pages.py': 'tectonics/optimisation/workbench/plan21/receiving-l3-r3/helpers/test_l3_carried_pages.py'}
REPLACEMENTS = frozenset({'source/helpers/record_views.py', 'source/helpers/mesh_tables.py'})
ADDITIONS = frozenset({'source/helpers/test_l3_carried_pages.py'})


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def pinned(raw, pin, name):
    require(isinstance(pin, str) and len(pin) == 64
            and all(c in '0123456789abcdef' for c in pin), 'Reviewed SHA256 required: ' + name)
    require(hashlib.sha256(raw).hexdigest() == pin, 'Pinned input changed: ' + name)
    return raw


def load_base(repo):
    path = repo / BASE_TOOL
    raw = pinned(path.read_bytes(), BASE_TOOL_SHA, BASE_TOOL)
    module = types.ModuleType('plan22_pinned_plan21_builder')
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def materialise(repo, destination):
    require(FROZEN is True, 'The corrected public source map is not frozen')
    require(isinstance(MAP_SHA, str) and len(MAP_SHA) == 64
            and all(c in '0123456789abcdef' for c in MAP_SHA), 'Reviewed Plan22 map pin required')
    repo, destination = Path(repo).absolute(), Path(destination).absolute()
    base = load_base(repo)
    combined = base.combined(repo)
    utilities = combined.shared(repo)
    for path in (repo, destination):
        utilities.inside(Path(path.anchor), path.relative_to(path.anchor).as_posix())
    utilities.refuse_existing(destination)
    tools = ((BASE_TOOL, BASE_TOOL_SHA), (base.BASE_TOOL, base.BASE_TOOL_SHA),
             (combined.SHARED, combined.SHARED_SHA))
    for path, pin in tools:
        pinned(utilities.read_source(repo, path), pin, path)
    parent_entries = {}
    for path, pin in ((base.BASE_MAP, base.BASE_MAP_SHA),
                      (base.PREFIX + 'SOURCE-MAP.json', base.MAP_SHA)):
        mapping = utilities.read_map(pinned(utilities.read_source(repo, path), pin, path))
        parent_entries.update(utilities.entry_index(repo, mapping.get('entries')))
    base.check_counts(parent_entries, BASE_COUNTS)
    map_path = PREFIX + 'SOURCE-MAP-r4.json'
    mapping = utilities.read_map(pinned(utilities.read_source(repo, map_path), MAP_SHA, map_path))
    require(mapping.get('schema') == SCHEMA and mapping.get('identity_kind') == IDENTITY_KIND,
            'A corrected Plan22 public candidate source map is required')
    require(all(mapping.get(key) is False for key in FLAGS), 'Candidate map grants authority')
    entries = utilities.entry_index(repo, mapping.get('entries'))
    require(entries.keys() == REPLACEMENTS | ADDITIONS, 'Unexpected Plan22 overlay membership')
    require(REPLACEMENTS <= parent_entries.keys() and not ADDITIONS & parent_entries.keys(),
            'Public parent does not support the Plan22 overlay')
    require(mapping.get('public_overlay_identity_sha256') == base.overlay_identity(mapping['entries'], utilities),
            'Plan22 overlay identity differs')
    payloads, public_bases = {}, {}
    for member, entry in entries.items():
        require(entry['public_path'] == PUBLIC_PATHS[member] and entry.get('selected_composition_member') is False,
                'Unexpected candidate source path or selection: ' + member)
        if member in REPLACEMENTS:
            prior = parent_entries[member]
            require(entry.get('public_base') == prior['public_path']
                    and entry.get('public_base_sha256') == prior['public_sha256'],
                    'Current public base differs: ' + member)
            public_bases[member] = {'public_path': prior['public_path'], 'public_sha256': prior['public_sha256']}
        else:
            require(entry.get('public_base') is None and entry.get('public_base_sha256') is None,
                    'Added member claims a public base: ' + member)
        payloads[member.removeprefix('source/')] = pinned(
            utilities.read_source(repo, entry['public_path']), entry['public_sha256'], member)
    selected = dict(parent_entries, **entries)
    base.check_counts(selected, COUNTS)
    expected = {m.removeprefix('source/'): e['public_sha256'] for m, e in parent_entries.items()}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.plan22-candidate-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'source'
        base.materialise(repo, stage)
        prior_manifest = utilities.read_map(utilities.read_source(stage, 'SOURCE-MANIFEST.json'))
        require(prior_manifest.get('files') == expected
                and prior_manifest.get('selection_sha256') == utilities.generation(parent_entries.values())
                and all(prior_manifest.get(key) is False for key in base.FLAGS + base.OVERLAY_FLAGS),
                'Materialised public parent closure or authority differs')
        for member, pin in expected.items():
            pinned(utilities.read_source(stage, member), pin, member)
        for member, raw in payloads.items():
            target = utilities.inside(stage, member)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        files = {m.removeprefix('source/'): e['public_sha256'] for m, e in sorted(selected.items())}
        manifest = dict(schema='atlas.public.plan22.materialised-candidate.r1',
            status='PREPARED_SOURCE_NOT_QUALIFIED',
            identity_kind='NEW_PUBLIC_SOURCE_CANDIDATE_NOT_RUNTIME_ADMISSION',
            source_map_sha256=MAP_SHA, base_selection_sha256=prior_manifest['selection_sha256'],
            selection_sha256=utilities.generation(selected.values()), source_members=len(files),
            overlay_identity_sha256=mapping['public_overlay_identity_sha256'],
            source_maps=[{'path': map_path, 'sha256': MAP_SHA}, *prior_manifest['source_maps']],
            source_tools=[{'path': path, 'sha256': pin} for path, pin in tools],
            replaced_public_sources=public_bases, files=files, **COUNTS, **dict.fromkeys(FLAGS, False))
        (stage / 'SOURCE-MANIFEST.json').write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True) + '\n', encoding='utf-8', newline='\n')
        utilities.refuse_existing(destination)
        stage.rename(destination)
    return dict(status='PREPARED_SOURCE_NOT_QUALIFIED', files=len(files),
                selection_sha256=manifest['selection_sha256'], **dict.fromkeys(FLAGS, False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = materialise(args.repo, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, 'Plan22 candidate construction refused: ' + str(error) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
