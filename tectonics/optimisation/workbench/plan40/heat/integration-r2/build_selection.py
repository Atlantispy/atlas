"""Build the explicitly selected heat receiving generation without altering a predecessor.

This creates source files, not a runtime admission, checkpoint migration or run.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile


HERE = Path(__file__).resolve().parent
PARENT = 'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json'
PARENT_SHA = 'ce77c8f2922e0d8780e241ba9204e775388fa093935968eaee7c577606baaccc'
PREFIX = 'tectonics/optimisation/workbench/plan40/heat/'
DIRECT = {
    'private_heat_certification_kernel_r1.py': 'implementation-r1/certificate/source/helpers/private_heat_certification_kernel_r1.py',
    'private_heat_compiled_dot_r1.py': 'implementation-r1/certificate/source/helpers/private_heat_compiled_dot_r1.py',
    'private_heat_certification_resources_r1.py': 'integration-r2/source/helpers/private_heat_certification_resources_r1.py',
    'private_heat_decimal_inventory_r1.py': 'integration-r2/source/helpers/private_heat_decimal_inventory_r1.py',
    'private_heat_geometry_inventory_r1.py': 'integration-r2/source/helpers/private_heat_geometry_inventory_r1.py',
    'private_heat_geometry_inventory_r3.py': 'integration-r2/source/helpers/private_heat_geometry_inventory_r3.py',
    'private_heat_low_solver_kernel_r2.py': 'integration-r2/source/helpers/private_heat_low_solver_kernel_r2.py',
    'private_heat_low_solver_kernel_r5.py': 'integration-r2/source/helpers/private_heat_low_solver_kernel_r5.py',
    'private_heat_low_ledger_inventory_r1.py': 'integration-r2/source/helpers/private_heat_low_ledger_inventory_r1.py',
    'private_heat_functionals_parallel_r1.py': 'integration-r2/source/helpers/private_heat_functionals_parallel_r1.py',
    'private_heat_forward_kernel_r13.py': 'integration-r2/source/helpers/private_heat_forward_kernel_r13.py',
    'private_heat_stage_lifetime_r3.py': 'integration-r2/source/helpers/private_heat_stage_lifetime_r3.py',
}
C8 = (
    'private_heat_interval_assembly_kernel_plan40b_c8_r1.py',
    'private_heat_interval_inventory_plan40b_c8_r1.py',
    'private_heat_interval_assessment_plan40b_c8_r1.py',
)
DOWNSTREAM = (
    'private_heat_checkpoint_consumer_r10.py',
    'private_heat_joined_consumer_r6.py',
    'private_heat_restored_binding_r10.py',
    'private_heat_restored_binding_ram_context_r1.py',
    'private_heat_restored_binding_ram_recovery_r1.py',
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inside(root, relative):
    name = PurePosixPath(relative)
    if name.is_absolute() or not name.parts or any(p in ('..', '.') or ':' in p or '\\' in p for p in name.parts):
        raise ValueError('Invalid relative source path: ' + relative)
    path = root.joinpath(*name.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Source escapes repository: ' + relative)
    return path


def generation(entries):
    identity = [(e['member'], e['public_sha256']) for e in entries]
    return digest(json.dumps(identity, separators=(',', ':'), ensure_ascii=True).encode())


def make_map(repo, *, include_downstream):
    """Author a NEW map; predecessor source hashes and receipts remain unchanged."""
    parent_bytes = inside(repo, PARENT).read_bytes()
    if digest(parent_bytes) != PARENT_SHA:
        raise ValueError('Selected predecessor map changed')
    parent = json.loads(parent_bytes)
    overrides = dict(DIRECT)
    if include_downstream:
        overrides.update({n: 'integration-r2/source/helpers/' + n for n in DOWNSTREAM})
    entries = []
    found = set()
    for old in parent['entries']:
        original = inside(repo, old['public_path']).read_bytes()
        if digest(original) != old['public_sha256']:
            raise ValueError('Predecessor source drift: ' + old['public_path'])
        entry = dict(old)
        name = PurePosixPath(old['member']).name
        if name in overrides:
            if name in found:
                raise ValueError('Ambiguous selected member: ' + name)
            found.add(name)
            path = PREFIX + overrides[name]
            entry.update(public_path=path, public_sha256=digest(inside(repo, path).read_bytes()),
                         predecessor_public_path=old['public_path'], predecessor_public_sha256=old['public_sha256'],
                         transformations=['Explicit new heat receiving source; historical identity is provenance only'])
        entries.append(entry)
    if found != set(overrides):
        raise ValueError('Missing override members: ' + repr(set(overrides) - found))
    for name in C8:
        path = PREFIX + 'implementation-r1/solve-finish/' + name
        entries.append(dict(member='source/helpers/' + name, public_path=path,
                            public_sha256=digest(inside(repo, path).read_bytes()),
                            source='<ACCEPTED_PUBLIC_C8_SOURCE>', selected_composition_member=True,
                            transformations=[]))
    entries.sort(key=lambda e: e['member'])
    return dict(schema='atlas.plan40b.receiving-source-map/v1',
                identity_kind='NEW_PUBLIC_SOURCE_BINDING_NOT_HISTORICAL_AUTHENTICATION',
                predecessor_map=PARENT, predecessor_source_map_sha256=PARENT_SHA,
                public_selection_sha256=generation(entries),
                receiving_bindings_complete=include_downstream,
                selected_candidates=['C3', 'C8'], excluded_candidates={'C13': 'Measured regression; not adopted'},
                runtime_admission=False, checkpoint_migration=False, scientific_acceptance=False,
                entries=entries)


def validate_map(repo, mapping):
    if mapping.get('schema') != 'atlas.plan40b.receiving-source-map/v1' or not mapping.get('receiving_bindings_complete'):
        raise ValueError('A complete receiving selection is required')
    if mapping.get('selected_candidates') != ['C3', 'C8'] or any(
        mapping.get(key) is not False for key in ('runtime_admission', 'checkpoint_migration', 'scientific_acceptance')
    ):
        raise ValueError('Source construction cannot grant runtime or scientific acceptance')
    parent_bytes = inside(repo, PARENT).read_bytes()
    if digest(parent_bytes) != PARENT_SHA or mapping.get('predecessor_source_map_sha256') != PARENT_SHA:
        raise ValueError('Selected predecessor map changed')
    parent_entries = {e['member']: e for e in json.loads(parent_bytes)['entries']}
    entries = mapping['entries']
    expected = set(parent_entries) | {'source/helpers/' + name for name in C8}
    if {e['member'] for e in entries} != expected:
        raise ValueError('Incomplete or unexpected source membership')
    if mapping['public_selection_sha256'] != generation(entries):
        raise ValueError('Selected source identity mismatch')
    seen = set()
    payloads = []
    for entry in entries:
        member = PurePosixPath(entry['member'])
        if member.parts[:2] not in (('source', 'helpers'), ('source', 'src')):
            raise ValueError('Unsupported selected member: ' + str(member))
        relative = member.relative_to('source').as_posix()
        inside(repo, relative)  # validate path syntax before any output is created
        if relative in seen:
            raise ValueError('Duplicate destination: ' + relative)
        seen.add(relative)
        selected_path = DIRECT.get(member.name)
        if member.name in DOWNSTREAM:
            selected_path = 'integration-r2/source/helpers/' + member.name
        if member.name in C8:
            selected_path = 'implementation-r1/solve-finish/' + member.name
        if selected_path is not None and entry['public_path'] != PREFIX + selected_path:
            raise ValueError('Required receiving implementation is not selected: ' + str(member))
        if member.name not in set(DIRECT) | set(DOWNSTREAM) | set(C8):
            old = parent_entries[entry['member']]
            if any(entry[key] != old[key] for key in ('public_path', 'public_sha256')):
                raise ValueError('Unrelated selected source changed: ' + str(member))
        data = inside(repo, entry['public_path']).read_bytes()
        if digest(data) != entry['public_sha256']:
            raise ValueError('Selected source drift: ' + entry['public_path'])
        payloads.append((relative, data))
    return payloads


def materialise(repo: Path, destination: Path):
    """Create one new complete layout; refuse existing outputs and source drift."""
    repo = repo.resolve()
    destination = destination.absolute()
    map_bytes = (HERE / 'SOURCE-MAP.json').read_bytes()
    mapping = json.loads(map_bytes)
    payloads = validate_map(repo, mapping)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.heat-selection-', dir=destination.parent) as staging:
        stage = Path(staging) / 'source'
        stage.mkdir()
        for relative, data in payloads:
            output = inside(stage, relative)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        receipt = dict(schema='atlas.plan40b.materialised-source/v1',
                       selection_sha256=mapping['public_selection_sha256'],
                       source_map_sha256=digest(map_bytes),
                       files={name: digest(data) for name, data in payloads},
                       runtime_admission=False, checkpoint_migration=False)
        (stage / 'SOURCE-MANIFEST.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8', newline='\n')
        stage.rename(destination)
    return dict(status='PASS', source_tree=str(destination), files=len(payloads),
                selection_sha256=mapping['public_selection_sha256'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--output', type=Path)
    action.add_argument('--write-map', action='store_true')
    parser.add_argument('--direct-only', action='store_true', help='Author intermediate map before downstream propagation')
    args = parser.parse_args()
    if args.write_map:
        mapping = make_map(args.repo.resolve(), include_downstream=not args.direct_only)
        (HERE / 'SOURCE-MAP.json').write_text(json.dumps(mapping, indent=2, ensure_ascii=True) + '\n', encoding='utf-8', newline='\n')
        result = dict(status='PASS', files=len(mapping['entries']), selection_sha256=mapping['public_selection_sha256'],
                      receiving_bindings_complete=mapping['receiving_bindings_complete'])
    else:
        if args.direct_only:
            parser.error('--direct-only applies only to --write-map')
        result = materialise(args.repo, args.output)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
