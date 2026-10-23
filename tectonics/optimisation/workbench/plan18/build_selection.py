"""Materialise the explicit Plan18 public source selection into a new directory.

Source construction grants no runtime, interval, default or scientific authority.
No selected Python source is imported or executed.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import tempfile


PARENT = 'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json'
PARENT_SHA = 'ce77c8f2922e0d8780e241ba9204e775388fa093935968eaee7c577606baaccc'
PREFIX = 'tectonics/optimisation/workbench/plan18/'
SCHEMA = 'atlas.public.plan18.source-selection.r1'
IDENTITY_KIND = 'NEW_PUBLIC_SOURCE_SELECTION_NOT_RUNTIME_ADMISSION'
COUNTS = {'selected_native_files': 239, 'selected_helper_files': 402}
FLAGS = ('runtime_admission', 'default_changed', 'scientific_acceptance', 'interval_authority')
REPLACEMENTS = frozenset({
    'source/src/atlas_tectonics/integration_component_volume_auto.py',
    'source/helpers/content_cache.py',
    'source/helpers/partition_routing_patch.py',
    'source/helpers/test_content_cache.py',
    'source/helpers/test_r1_views.py',
    'source/helpers/test_r1a_export_booking.py',
})
ADDITIONS = frozenset({
    'source/helpers/test_compact_header_retention.py',
    'source/helpers/test_owner_carrier_booking.py',
    'source/helpers/test_retained_handle_check.py',
    'source/helpers/test_spatial_allocation_order.py',
})


def digest(data):
    return hashlib.sha256(data).hexdigest()


def generation(entries):
    identity = sorted(({'member': e['member'], 'public_sha256': e['public_sha256']}
                       for e in entries), key=lambda e: e['member'])
    return digest((json.dumps(identity, indent=2, ensure_ascii=True) + '\n').encode('utf-8'))


def inside(root, relative):
    """Resolve canonical repository-relative names without following links/reparse points."""
    if not isinstance(relative, str) or not relative:
        raise ValueError('Invalid relative source path')
    parts = relative.split('/')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                *(f'LPT{i}' for i in range(1, 10))}
    if any(not p or p in ('.', '..') or p.endswith((' ', '.')) or
           any(c in p for c in '\\:*?"<>|\0') or
           p.split('.')[0].upper() in reserved for p in parts):
        raise ValueError('Invalid relative source path: ' + relative)
    path = root
    for part in parts:
        path = path / part
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked or reparse source path: ' + relative)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Source escapes repository: ' + relative)
    return path


def read_source(repo, relative):
    path = inside(repo, relative)
    if not path.is_file():
        raise ValueError('Source is not a regular file: ' + relative)
    return path.read_bytes()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate map key: ' + key)
        result[key] = value
    return result


def read_map(data):
    mapping = json.loads(data, object_pairs_hook=unique_object)
    if not isinstance(mapping, dict):
        raise ValueError('Source map must be an object')
    return mapping


def entry_index(repo, entries):
    if not isinstance(entries, list):
        raise ValueError('Source map entries must be a list')
    result = {}
    destinations = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Source map entry must be an object')
        member = entry.get('member')
        inside(repo, member)
        parts = PurePosixPath(member).parts
        if parts[:2] not in (('source', 'helpers'), ('source', 'src')) or len(parts) < 3:
            raise ValueError('Unsupported selected member: ' + member)
        if member.casefold() in destinations:
            raise ValueError('Duplicate source destination: ' + member)
        destinations.add(member.casefold())
        inside(repo, entry.get('public_path'))
        sha = entry.get('public_sha256')
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('Invalid public source digest: ' + member)
        result[member] = entry
    return result


def validate_map(repo, mapping):
    if mapping.get('schema') != SCHEMA or mapping.get('identity_kind') != IDENTITY_KIND:
        raise ValueError('A Plan18 public source selection is required')
    if any(mapping.get(key) is not False for key in FLAGS):
        raise ValueError('Source construction cannot grant runtime, default, interval or scientific authority')
    if mapping.get('predecessor_map') != PARENT or mapping.get('predecessor_source_map_sha256') != PARENT_SHA:
        raise ValueError('Selected predecessor pin changed')
    parent_bytes = read_source(repo, PARENT)
    if digest(parent_bytes) != PARENT_SHA:
        raise ValueError('Selected predecessor map changed')
    parent = entry_index(repo, read_map(parent_bytes).get('entries'))
    entries = entry_index(repo, mapping.get('entries'))
    if not REPLACEMENTS <= parent.keys() or ADDITIONS & parent.keys():
        raise ValueError('Predecessor does not support the required Plan18 changes')
    if entries.keys() != parent.keys() | ADDITIONS:
        raise ValueError('Incomplete or unexpected source membership')
    counts = {'selected_native_files': sum(m.startswith('source/src/') for m in entries),
              'selected_helper_files': sum(m.startswith('source/helpers/') for m in entries)}
    if counts != COUNTS or any(type(mapping.get(k)) is not int or mapping[k] != v
                               for k, v in COUNTS.items()):
        raise ValueError('Selected source counts do not match Plan18')
    if mapping.get('public_selection_sha256') != generation(mapping['entries']):
        raise ValueError('Selected source identity mismatch')
    payloads = []
    for member, entry in entries.items():
        if member in REPLACEMENTS | ADDITIONS:
            if entry['public_path'] != PREFIX + member:
                raise ValueError('Required Plan18 implementation is not selected: ' + member)
        elif entry != parent[member]:
            raise ValueError('Unrelated selected source changed: ' + member)
        data = read_source(repo, entry['public_path'])
        if digest(data) != entry['public_sha256']:
            raise ValueError('Selected source drift: ' + entry['public_path'])
        payloads.append((PurePosixPath(member).relative_to('source').as_posix(), data))
    return payloads


def refuse_existing(path):
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise FileExistsError(path)


def materialise(repo: Path, destination: Path):
    """Validate once, then copy those exact bytes and publish a new source directory."""
    repo = repo.resolve(strict=True)
    destination = destination.absolute()
    refuse_existing(destination)
    map_bytes = read_source(repo, PREFIX + 'SOURCE-MAP.json')
    mapping = read_map(map_bytes)
    payloads = validate_map(repo, mapping)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.plan18-selection-', dir=destination.parent) as staging:
        stage = Path(staging) / 'source'
        stage.mkdir()
        for relative, data in payloads:
            output = inside(stage, relative)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        manifest = dict(schema='atlas.public.plan18.materialised-source.r1',
                        selection_sha256=mapping['public_selection_sha256'],
                        source_map_sha256=digest(map_bytes),
                        files={name: digest(data) for name, data in payloads},
                        **dict.fromkeys(FLAGS, False))
        (stage / 'SOURCE-MANIFEST.json').write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True) + '\n', encoding='utf-8', newline='\n')
        refuse_existing(destination)
        stage.rename(destination)
    return dict(status='PASS', source_tree=str(destination), files=len(payloads),
                selection_sha256=mapping['public_selection_sha256'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = materialise(args.repo, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Plan18 source construction refused: {error}\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
