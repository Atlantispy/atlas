"""Construct the complete public Plan21 source selection in a NEW directory.

The authenticated combined-runtime-r1 selection supplies both src and helpers;
Plan21 replaces two helpers and adds one. No selected source is executed and no
runtime, installed-package, default or scientific authority is granted.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
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
MAP_SHA = '715fbf95dadb0264f1b9500d3932394ad825ced131ea11605d003b8fe44ad10f'
SCHEMA = 'atlas.public.plan21.source-map.r1'
IDENTITY_KIND = 'NEW_PUBLIC_SOURCE_OVERLAY_NOT_RUNTIME_BINDING'
BASE_COUNTS = {'selected_native_files': 240, 'selected_helper_files': 405}
COUNTS = {'selected_native_files': 240, 'selected_helper_files': 406}
FLAGS = ('runtime_admission', 'default_changed', 'scientific_acceptance',
         'interval_authority', 'installed_package_changed')
OVERLAY_FLAGS = ('public_runtime_compatibility', 'runtime_policy_adopted', 's9_selected')
REPLACEMENTS = frozenset({
    'source/helpers/spatial_validation_patch.py',
    'source/helpers/test_d1b_carried_start.py',
})
ADDITIONS = frozenset({'source/helpers/test_s3_lazy_rows.py'})


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
        if entry['public_path'] != PREFIX + member:
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
    overlay_raw = utilities.read_source(repo, PREFIX + 'SOURCE-MAP.json')
    if utilities.digest(overlay_raw) != MAP_SHA:
        raise ValueError('Plan21 source map differs from reviewed bytes')
    mapping = utilities.read_map(overlay_raw)
    payloads, selection, public_bases = merge_overlay(
        repo, mapping, base_entries, payloads, utilities)
    source_maps = [
        {'path': BASE_MAP, 'sha256': BASE_MAP_SHA},
        {'path': PREFIX + 'SOURCE-MAP.json', 'sha256': MAP_SHA},
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
