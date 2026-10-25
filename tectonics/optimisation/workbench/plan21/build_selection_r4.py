"""Construct the complete public Plan21 source selection in a NEW directory.

The authenticated combined-runtime-r1 selection supplies both src and helpers;
Plan21 replaces two helpers and adds two. No selected source is executed and no
runtime, installed-package, default or scientific authority is granted.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile


PREFIX = 'tectonics/optimisation/workbench/plan21/'
BASE_TOOL = 'tectonics/optimisation/workbench/combined-runtime-r1/build_selection.py'
BASE_TOOL_SHA = '73ab61d09ef970863124419dd30785bb8e80be6768a8f110e8874c468d30fc79'
BASE_MAP = 'tectonics/optimisation/workbench/combined-runtime-r1/SOURCE-MAP.json'
BASE_MAP_SHA = '568079ecb375aea52a9a5e5cdebaa4017b0e07f237d398c8f041f15b8ea2ee0a'
MAP_SHA = '5bfb6e17c3479d57abbe053f2df6764fdee17aa92627c667413accfe31d585b1'
MAP_FILE = 'SOURCE-MAP-r4.json'
SOURCE_PREFIX = PREFIX + 'receiving-r4/'
EXPORT_AST_SHA = '5d5432706c4b68e1e4161c7a18a919e5f690a34e5af20f023427e7c22e8c99c9'
SCHEMA = 'atlas.public.plan21.source-map.r1'
IDENTITY_KIND = 'NEW_PUBLIC_SOURCE_OVERLAY_NOT_RUNTIME_BINDING'
BASE_COUNTS = {'selected_native_files': 240, 'selected_helper_files': 405}
COUNTS = {'selected_native_files': 240, 'selected_helper_files': 407}
FLAGS = ('runtime_admission', 'default_changed', 'scientific_acceptance',
         'interval_authority', 'installed_package_changed')
OVERLAY_FLAGS = ('public_runtime_compatibility', 'runtime_policy_adopted', 's9_selected')
REPLACEMENTS = frozenset({
    'source/helpers/spatial_validation_patch.py',
    'source/helpers/test_d1b_carried_start.py',
})
ADDITIONS = frozenset({'source/helpers/test_s3_lazy_rows.py', 'source/helpers/test_s3_l3_fallback.py'})


def combined(repo):
    """Load only the pinned, standard-library construction tool."""
    path = repo / BASE_TOOL
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_TOOL_SHA:
        raise ValueError('Combined source-construction tool changed')
    spec = importlib.util.spec_from_file_location('plan21_combined_builder', path)
    module = importlib.util.module_from_spec(spec)
    # Execute the bytes just authenticated, rather than reopening the file.
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def check_counts(entries, expected):
    actual = {
        'selected_native_files': sum(m.startswith('source/src/') for m in entries),
        'selected_helper_files': sum(m.startswith('source/helpers/') for m in entries),
    }
    if actual != expected:
        raise ValueError('Complete source selection counts differ')



def verify_export_preflight(raw):
    nodes = [node for node in ast.parse(raw).body
             if isinstance(node, ast.FunctionDef) and node.name == '_export_ref']
    if (len(nodes) != 1 or hashlib.sha256(
            ast.dump(nodes[0], include_attributes=False).encode()).hexdigest() != EXPORT_AST_SHA):
        raise ValueError('S3 exporter preflight source changed')


def overlay_identity(entries, utilities):
    """The overlay's recorded identity uses entry order, unlike full selections."""
    identity = [{'member': e['member'], 'public_sha256': e['public_sha256']}
                for e in entries]
    return utilities.digest((json.dumps(identity, indent=2, ensure_ascii=True) + '\n').encode())


def merge_overlay(repo, mapping, base_entries, payloads, utilities):
    if mapping.get('schema') != SCHEMA or mapping.get('identity_kind') != IDENTITY_KIND:
        raise ValueError('A Plan21 public source overlay is required')
    if (any(mapping.get(k) is not False for k in OVERLAY_FLAGS) or
            any(k in mapping and mapping[k] is not False for k in FLAGS)):
        raise ValueError('Plan21 source construction cannot grant execution authority')
    entries = utilities.entry_index(repo, mapping.get('entries'))
    if entries.keys() != REPLACEMENTS | ADDITIONS:
        raise ValueError('Incomplete or unexpected Plan21 overlay membership')
    if not REPLACEMENTS <= base_entries.keys() or ADDITIONS & base_entries.keys():
        raise ValueError('Combined source selection does not support the Plan21 overlay')
    if mapping.get('public_overlay_identity_sha256') != overlay_identity(mapping['entries'], utilities):
        raise ValueError('Plan21 overlay identity differs')
    selected = dict(base_entries)
    payloads = dict(payloads)
    public_bases = {}
    for member, entry in entries.items():
        if entry['public_path'] != SOURCE_PREFIX + member.removeprefix('source/'):
            raise ValueError('Required Plan21 public source is not selected: ' + member)
        if member in REPLACEMENTS:
            base = base_entries[member]
            if (entry.get('base_public_path') != base['public_path'] or
                    ('base_public_sha256' in entry and
                     entry['base_public_sha256'] != base['public_sha256'])):
                raise ValueError('Plan21 public base differs from combined selection: ' + member)
            # base_sha256 describes private provenance. Public comment changes
            # mean it must not be compared with the authenticated public bytes.
            public_bases[member] = {'public_path': base['public_path'],
                                    'public_sha256': base['public_sha256']}
        elif any(entry.get(k) is not None for k in
                 ('base_public_path', 'base_public_sha256', 'base_sha256')):
            raise ValueError('Added Plan21 member must not claim a base: ' + member)
        raw = utilities.read_source(repo, entry['public_path'])
        if utilities.digest(raw) != entry['public_sha256']:
            raise ValueError('Plan21 selected source changed: ' + member)
        payloads[member.removeprefix('source/')] = raw
        selected[member] = entry
    binding = mapping.get('export_preflight_binding')
    if binding != dict(function='_export_ref', ast_sha256=EXPORT_AST_SHA,
                       rule='SHA256(ast.dump(FunctionDef, include_attributes=False).encode())'):
        raise ValueError('S3 exporter preflight binding differs')
    verify_export_preflight(payloads['helpers/record_views.py'])
    check_counts(selected, COUNTS)
    return payloads, utilities.generation(selected.values()), public_bases


def materialise(repo, destination):
    repo, destination = Path(repo).absolute(), Path(destination).absolute()
    base = combined(repo)
    utilities = base.shared(repo)
    # Keep lexical paths until all ancestors have been checked. Resolving first
    # would hide a linked repository or destination supplied by the caller.
    for path in (repo, destination):
        utilities.inside(Path(path.anchor), path.relative_to(path.anchor).as_posix())
    utilities.read_source(repo, BASE_TOOL)
    utilities.read_source(repo, base.SHARED)
    utilities.refuse_existing(destination)
    base_raw = utilities.read_source(repo, BASE_MAP)
    if utilities.digest(base_raw) != BASE_MAP_SHA:
        raise ValueError('Combined source map differs from reviewed bytes')
    base_mapping = utilities.read_map(base_raw)
    payloads = base.validate_map(repo, base_mapping, utilities)
    base_entries = utilities.entry_index(repo, base_mapping['entries'])
    check_counts(base_entries, BASE_COUNTS)
    overlay_raw = utilities.read_source(repo, PREFIX + MAP_FILE)
    if utilities.digest(overlay_raw) != MAP_SHA:
        raise ValueError('Plan21 source map differs from reviewed bytes')
    mapping = utilities.read_map(overlay_raw)
    payloads, selection, public_bases = merge_overlay(
        repo, mapping, base_entries, payloads, utilities)
    source_maps = [
        {'path': BASE_MAP, 'sha256': BASE_MAP_SHA},
        {'path': PREFIX + MAP_FILE, 'sha256': MAP_SHA},
        *base_mapping['source_maps'],
    ]
    manifest = dict(
        schema='atlas.public.plan21.materialised-source.r1',
        identity_kind='NEW_PUBLIC_SOURCE_SELECTION_NOT_RUNTIME_ADMISSION',
        source_map_sha256=MAP_SHA, base_source_map_sha256=BASE_MAP_SHA,
        base_selection_sha256=base_mapping['public_selection_sha256'],
        overlay_identity_sha256=mapping['public_overlay_identity_sha256'],
        selection_sha256=selection, selected_members=len(payloads),
        source_maps=source_maps, replaced_public_sources=public_bases,
        files={name: utilities.digest(data) for name, data in sorted(payloads.items())},
        **COUNTS, **dict.fromkeys(FLAGS + OVERLAY_FLAGS, False))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.plan21-selection-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'source'
        stage.mkdir()
        for member, raw in payloads.items():
            target = utilities.inside(stage, member)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        (stage / 'SOURCE-MANIFEST.json').write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True) + '\n', encoding='utf-8', newline='\n')
        utilities.refuse_existing(destination)
        stage.rename(destination)
    return dict(status='PASS', files=len(payloads), selection_sha256=selection)



def upgrade_selected_payloads(repo, files, payloads, utilities):
    """Apply current L3 and S3 to the authenticated complete Plan39/S1A parent.

    Historical builders and maps remain unchanged. Plan39 selects a complete
    source map, rather than retaining the earlier Plan21/22 overlay rows.
    """
    parent_pin = 'b7887aef4e2fae64c6170306277c5a15b7e2e276b2588aa00aa4e1f3545f1c6b'
    historical_pin = '715fbf95dadb0264f1b9500d3932394ad825ced131ea11605d003b8fe44ad10f'
    parent_raw = utilities.read_source(repo, 'tectonics/optimisation/workbench/plan39/SOURCE-MAP.json')
    historical_raw = utilities.read_source(repo, PREFIX + 'SOURCE-MAP.json')
    if utilities.digest(parent_raw) != parent_pin or utilities.digest(historical_raw) != historical_pin:
        raise ValueError('Receiving predecessor source map changed')
    parent_entries = utilities.entry_index(repo, utilities.read_map(parent_raw)['entries'])
    old_rows = {row: parent_entries['source/' + row]['public_sha256'] for row in (
        'helpers/spatial_validation_patch.py', 'helpers/test_d1b_carried_start.py',
        'helpers/record_views.py', 'helpers/mesh_tables.py')}
    additions = {'helpers/test_s3_lazy_rows.py', 'helpers/test_s3_l3_fallback.py',
                 'helpers/test_l3_carried_pages.py'}
    if set(files) != set(payloads) or additions & set(files):
        raise ValueError('Receiving parent membership differs')
    if any(utilities.digest(payloads[row]) != pin for row, pin in files.items()):
        raise ValueError('Parent source bytes differ from its manifest')
    if any(files.get(row) != pin for row, pin in old_rows.items()):
        raise ValueError('Plan39 receiving predecessor differs')
    l3_pin = '0f6fa03a6af98df2d3446868520a965a2c41d046c2b8bada6228a843683e5930'
    l3_raw = utilities.read_source(repo, PREFIX + 'L3-SOURCE-MAP-r3.json')
    if utilities.digest(l3_raw) != l3_pin:
        raise ValueError('Current L3 receiving source map changed')
    l3 = utilities.read_map(l3_raw)
    if (l3.get('schema') != 'atlas.public.plan21.receiving-l3-overlay.r1'
            or l3.get('identity_kind') != IDENTITY_KIND
            or l3.get('parent_source_map_sha256') != parent_pin
            or l3.get('source_port_sha256') != 'fb2636dbd1f70dd6042f65a1efe235fd6249e6337a3aba4fe4b67f1acab59230'
            or any(l3.get(k) is not False for k in ('selected','enablement','runtime_admission',
                    'default_changed','scientific_acceptance','interval_authority'))):
        raise ValueError('Current L3 receiving contract differs')
    l3_entries = utilities.entry_index(repo, l3.get('entries'))
    l3_members = {'source/helpers/record_views.py', 'source/helpers/mesh_tables.py',
                  'source/helpers/test_l3_carried_pages.py'}
    if set(l3_entries) != l3_members:
        raise ValueError('Current L3 receiving membership differs')
    mapping_raw = utilities.read_source(repo, PREFIX + MAP_FILE)
    if utilities.digest(mapping_raw) != MAP_SHA:
        raise ValueError('S3 successor source map changed')
    mapping = utilities.read_map(mapping_raw)
    if (mapping.get('schema') != SCHEMA or mapping.get('identity_kind') != IDENTITY_KIND
            or any(mapping.get(k) is not False for k in OVERLAY_FLAGS)
            or any(k in mapping and mapping[k] is not False for k in FLAGS)):
        raise ValueError('S3 successor schema or authority differs')
    entries = utilities.entry_index(repo, mapping.get('entries'))
    if (set(entries) != REPLACEMENTS | ADDITIONS
            or mapping.get('public_overlay_identity_sha256') != overlay_identity(mapping['entries'], utilities)):
        raise ValueError('S3 successor membership or identity differs')
    upgraded, selected, changes = dict(payloads), dict(files), {}
    for source_entries, source_prefix in ((l3_entries, PREFIX+'receiving-l3-r3/'), (entries, SOURCE_PREFIX)):
        for member, entry in source_entries.items():
            row = member.removeprefix('source/')
            expected_path = ('tectonics/optimisation/workbench/plan22/source/helpers/mesh_tables.py'
                             if source_entries is l3_entries and row == 'helpers/mesh_tables.py'
                             else source_prefix + row)
            if entry['public_path'] != expected_path:
                raise ValueError('Receiving package path differs: ' + row)
            if source_entries is l3_entries and entry.get('before_public_sha256') != files.get(row):
                raise ValueError('L3 receiving predecessor differs: ' + row)
            content = utilities.read_source(repo, entry['public_path'])
            if utilities.digest(content) != entry['public_sha256']:
                raise ValueError('Receiving payload changed: ' + row)
            changes[row] = dict(before=files.get(row), after=entry['public_sha256'])
            upgraded[row], selected[row] = content, entry['public_sha256']
    verify_export_preflight(upgraded['helpers/record_views.py'])
    if set(selected) != set(files) | additions or set(changes) != set(old_rows) | additions:
        raise ValueError('Receiving upgrade changed unrelated membership')
    return upgraded, selected, dict(
        historical_source_map_sha256=historical_pin, parent_source_map_sha256=parent_pin,
        l3_source_map_sha256=l3_pin, source_map_sha256=MAP_SHA,
        overlay_identity_sha256=mapping['public_overlay_identity_sha256'], changed_rows=changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = materialise(args.repo, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, 'Plan21 source construction refused: ' + str(error) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
