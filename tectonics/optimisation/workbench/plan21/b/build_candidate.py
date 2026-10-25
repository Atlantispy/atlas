"""Build an explicit B/current-L3/S3 arm over the complete Plan39/S1A parent.

Source construction alone grants no execution, selection or enablement authority.
Existing output directories and linked paths are refused.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
BASE_TOOL = 'tectonics/optimisation/workbench/plan30/s1a/build_candidate.py'
BASE_TOOL_SHA = '7618b5cf6d6f3210d36a882bf34429aba0318a9cb0f8ba32af5fc4b1f9640b59'
BASE_MAP = 'tectonics/optimisation/workbench/plan30/s1a/SOURCE-MAP.json'
BASE_MAP_SHA = '878ae56c72fcb47cea97f5d74cb42b737a1680dfe0e2e3ec8f1217d54650bf45'
MAP_SHA = '2212cd1f96b52b463635259e3afdb5c6868a3727e768e1fd371589c43d9fe2e6'
S3_UPGRADE = {'tool': {'path': 'tectonics/optimisation/workbench/plan21/build_selection_r4.py', 'sha256': '595e026cf0a67664b654a651aec273cc607969cc3ac0874b547b13ff5970348b'}, 'historical_source_map': {'path': 'tectonics/optimisation/workbench/plan21/SOURCE-MAP.json', 'sha256': '715fbf95dadb0264f1b9500d3932394ad825ced131ea11605d003b8fe44ad10f'}, 'source_map': {'path': 'tectonics/optimisation/workbench/plan21/SOURCE-MAP-r4.json', 'sha256': '5bfb6e17c3479d57abbe053f2df6764fdee17aa92627c667413accfe31d585b1'}, 'parent_source_members': 694, 'result_source_members': 697, 'parent_source_map': {'path': 'tectonics/optimisation/workbench/plan39/SOURCE-MAP.json', 'sha256': 'b7887aef4e2fae64c6170306277c5a15b7e2e276b2588aa00aa4e1f3545f1c6b'}, 'l3_source_map': {'path': 'tectonics/optimisation/workbench/plan21/L3-SOURCE-MAP-r3.json', 'sha256': '0f6fa03a6af98df2d3446868520a965a2c41d046c2b8bada6228a843683e5930'}, 'parent_counts': {'src': 287, 'helpers': 407}, 'result_counts': {'src': 287, 'helpers': 410}}
UPGRADE_ROWS = frozenset((
    'helpers/record_views.py', 'helpers/mesh_tables.py', 'helpers/test_l3_carried_pages.py',
    'helpers/spatial_validation_patch.py', 'helpers/test_d1b_carried_start.py',
    'helpers/test_s3_lazy_rows.py', 'helpers/test_s3_l3_fallback.py',
))
UPGRADE_ADDITIONS = frozenset((
    'helpers/test_l3_carried_pages.py', 'helpers/test_s3_lazy_rows.py',
    'helpers/test_s3_l3_fallback.py',
))
FLAGS = ('runtime_admission', 'default_changed', 'scientific_acceptance',
         'interval_authority', 'selected', 'enablement')
BEFORE = {
    'helpers/interval_store_set.py': '9b00661d4a14c1b8181689f3823e6b1b1cb8c448cff3b2e31056095670cdc192',
    'helpers/test_interval_store_set.py': '10c47f2932bda169fd841165bb5fd1b0a471f0e96ea2e33cc351eb593880d92a',
    'helpers/storage_codec_integration_patch.py': '39d71ed0ec7c0ba3f2d65169b3642308e57cc0a8436b27d330cf18d3e6bfbe0f',
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned(raw, expected, label):
    if digest(raw) != expected:
        raise ValueError('Pinned source changed: ' + label)
    return raw


def parent(repo):
    import types
    raw = pinned((repo / BASE_TOOL).read_bytes(), BASE_TOOL_SHA, BASE_TOOL)
    module = types.ModuleType('b_s1a_builder')
    module.__file__ = str(repo / BASE_TOOL)
    exec(compile(raw, module.__file__, 'exec'), module.__dict__)
    plan39 = module.module(repo / module.BASE_TOOL,
        module.pinned((repo / module.BASE_TOOL).read_bytes(), module.BASE_TOOL_SHA, module.BASE_TOOL),
        'b_plan39_builder')
    return module, plan39.shared(repo)


def contract(repo, arm):
    if arm not in ('b1b2', 'b3'):
        raise ValueError('An explicit B arm is required')
    base, utilities = parent(repo)
    for root in (repo, HERE):
        utilities.inside(Path(root.anchor), root.relative_to(root.anchor).as_posix())
    pinned(utilities.read_source(repo, BASE_MAP), BASE_MAP_SHA, BASE_MAP)
    mapping = utilities.read_map(pinned(utilities.read_source(HERE, 'SOURCE-MAP.json'),
                                        MAP_SHA, 'B source map'))
    if (mapping.get('schema') != 'atlas.public.plan21.b.source-overlay.r3'
            or mapping.get('identity_kind') != 'NEW_PUBLIC_SOURCE_OVERLAY_NOT_RUNTIME_ADMISSION'
            or any(mapping.get(flag) is not False for flag in FLAGS)
            or mapping.get('base_builder') != dict(path=BASE_TOOL, sha256=BASE_TOOL_SHA)
            or mapping.get('base_source_map') != dict(path=BASE_MAP, sha256=BASE_MAP_SHA)
            or mapping.get('source_members') != 697
            or mapping.get('parent_source_members') != 694
            or mapping.get('s3_upgrade') != S3_UPGRADE
            or set(mapping.get('arms', {})) != {'b1b2', 'b3'}):
        raise ValueError('B parent, membership or authority contract differs')
    rows = mapping['arms'][arm].get('rows')
    if not isinstance(rows, dict) or set(rows) != set(BEFORE):
        raise ValueError('B overlay must replace exactly its three rows')
    payloads = {}
    for row, before in BEFORE.items():
        entry = rows[row]
        if not isinstance(entry, dict) or entry.get('before') != before:
            raise ValueError('B input identity differs: ' + row)
        expected_path = ('source/' + arm + '/' + row if row.endswith('/interval_store_set.py')
                         else 'source/common/' + row)
        if entry.get('package_path') != expected_path:
            raise ValueError('B package member differs: ' + row)
        raw = pinned(utilities.read_source(HERE, expected_path), entry.get('after'), row)
        compile(raw, expected_path, 'exec')
        payloads[row] = raw
    tool = S3_UPGRADE['tool']
    raw = pinned(utilities.read_source(repo, tool['path']), tool['sha256'], 'S3 upgrade tool')
    for key in ('parent_source_map', 'historical_source_map', 'l3_source_map', 'source_map'):
        binding = S3_UPGRADE[key]
        pinned(utilities.read_source(repo, binding['path']), binding['sha256'], 'S3 ' + key)
    s3 = base.module(repo / tool['path'], raw, 'b_authenticated_s3_upgrade')
    if (not callable(getattr(s3, 'upgrade_selected_payloads', None))
            or s3.MAP_SHA != S3_UPGRADE['source_map']['sha256']):
        raise ValueError('S3 upgrade API contract differs')
    return base, utilities, rows, payloads, s3


def upgrade_parent(repo, files, payloads, utilities, s3):
    """Authenticate the exact complete Plan39/S1A parent and constrain L3/S3."""
    if len(files) != 694 or set(files) != set(payloads):
        raise ValueError('Historical S1A parent membership differs')
    parent_binding = S3_UPGRADE['parent_source_map']
    parent_map = utilities.read_map(pinned(utilities.read_source(repo, parent_binding['path']),
                                          parent_binding['sha256'], 'complete Plan39 map'))
    expected = {member.removeprefix('source/'): entry['public_sha256']
                for member, entry in utilities.entry_index(repo, parent_map['entries']).items()}
    s1a_map = utilities.read_map(pinned(utilities.read_source(repo, BASE_MAP), BASE_MAP_SHA,
                                       'complete S1A overlay'))
    expected.update({row: entry['after'] for row, entry in s1a_map['rows'].items()})
    if files != expected:
        raise ValueError('Complete Plan39/S1A parent differs')
    parent_counts = dict(src=sum(row.startswith('src/') for row in files),
                         helpers=sum(row.startswith('helpers/') for row in files))
    if parent_counts != S3_UPGRADE['parent_counts']:
        raise ValueError('Complete Plan39/S1A parent category counts differ')
    for row, pin in files.items():
        pinned(payloads[row], pin, 'historical receiving ' + row)
    upgraded, selected, receipt = s3.upgrade_selected_payloads(repo, files, payloads, utilities)
    if (len(selected) != 697 or set(selected) != set(files) | UPGRADE_ADDITIONS
            or set(upgraded) != set(selected)
            or set(receipt.get('changed_rows', {})) != UPGRADE_ROWS
            or receipt.get('historical_source_map_sha256') != S3_UPGRADE['historical_source_map']['sha256']
            or receipt.get('source_map_sha256') != S3_UPGRADE['source_map']['sha256']
            or receipt.get('parent_source_map_sha256') != S3_UPGRADE['parent_source_map']['sha256']
            or receipt.get('l3_source_map_sha256') != S3_UPGRADE['l3_source_map']['sha256']):
        raise ValueError('S3 upgrade membership or receipt differs')
    for row in set(files) - UPGRADE_ROWS:
        if selected[row] != files[row] or upgraded[row] != payloads[row]:
            raise ValueError('S3 upgrade changed unrelated parent source: ' + row)
    result_counts = dict(src=sum(row.startswith('src/') for row in selected),
                         helpers=sum(row.startswith('helpers/') for row in selected))
    if result_counts != S3_UPGRADE['result_counts']:
        raise ValueError('L3/S3 result category counts differ')
    for row, pin in selected.items():
        pinned(upgraded[row], pin, 'upgraded receiving ' + row)
    for row in UPGRADE_ROWS:
        if receipt['changed_rows'][row] != dict(before=files.get(row), after=selected[row]):
            raise ValueError('S3 upgrade changed-row receipt differs: ' + row)
    return upgraded, selected, receipt


def materialise(repo, destination, *, arm):
    repo, destination = Path(repo).absolute(), Path(destination).absolute()
    base, utilities, rows, b_payloads, s3 = contract(repo, arm)
    utilities.refuse_existing(destination)
    utilities.inside(Path(destination.anchor), destination.relative_to(destination.anchor).as_posix())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.b-source-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'source'
        base.materialise(repo, stage)
        original = utilities.read_map(utilities.read_source(stage, 'SOURCE-MANIFEST.json'))
        if (original.get('schema') != 'atlas.public.plan30.s1a.materialised-source.r3'
                or original.get('source_map_sha256') != BASE_MAP_SHA
                or any(original.get(flag) is not False for flag in FLAGS)
                or len(original.get('files', {})) != 694):
            raise ValueError('Materialised S1A parent differs')
        parent_files = dict(original['files'])
        parent_payloads = {row: utilities.read_source(stage, row) for row in parent_files}
        upgraded, files, s3_receipt = upgrade_parent(repo, parent_files, parent_payloads, utilities, s3)
        for row in UPGRADE_ROWS:
            target = utilities.inside(stage, row)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(upgraded[row])
        for row, raw in b_payloads.items():
            if files.get(row) != rows[row]['before']:
                raise ValueError('B manifest input differs: ' + row)
            target = utilities.inside(stage, row)
            pinned(utilities.read_source(stage, row), rows[row]['before'], 'receiving ' + row)
            target.write_bytes(raw)
            files[row] = rows[row]['after']
        for row, pin in files.items():
            pinned(utilities.read_source(stage, row), pin, 'receiving ' + row)
        if len(files) != 697 or set(files) != set(parent_files) | UPGRADE_ADDITIONS:
            raise ValueError('B/S3 changed unexpected parent membership')
        changes = dict(s3_receipt['changed_rows'])
        changes.update({row: dict(before=rows[row]['before'], after=rows[row]['after']) for row in rows})
        if set(changes) != UPGRADE_ROWS | set(BEFORE):
            raise ValueError('B/S3 changed-row membership differs')
        result = dict(schema='atlas.public.plan21.b.materialised-source.r3',
            status='INTEGRATED_SOURCE_COMPONENT_NOT_QUALIFIED', arm=arm,
            source_map_sha256=MAP_SHA, base_source_map_sha256=BASE_MAP_SHA,
            historical_s3_source_map_sha256=S3_UPGRADE['historical_source_map']['sha256'],
            s3_source_map_sha256=S3_UPGRADE['source_map']['sha256'],
            parent_source_map_sha256=S3_UPGRADE['parent_source_map']['sha256'],
            l3_source_map_sha256=S3_UPGRADE['l3_source_map']['sha256'],
            s3_upgrade_tool_sha256=S3_UPGRADE['tool']['sha256'], s3_receipt=s3_receipt,
            base_selection_sha256=original['selection_sha256'], parent_source_members=len(parent_files),
            source_members=len(files), selected_native_files=287, selected_helper_files=410,
            selection_sha256=utilities.generation({'member': 'source/' + row, 'public_sha256': pin}
                                                  for row, pin in files.items()),
            changed_rows=changes,
            changed_membership=dict(added=sorted(UPGRADE_ADDITIONS), removed=[],
                                    replaced=sorted((UPGRADE_ROWS - UPGRADE_ADDITIONS) | set(BEFORE))),
            changed_byte_rows=sorted(row for row, change in changes.items() if change['before'] != change['after']),
            files=files, **dict.fromkeys(FLAGS, False),
            installed_package_changed=False, public_runtime_compatibility=False,
            runtime_policy_adopted=False, s9_selected=False)
        (stage / 'SOURCE-MANIFEST.json').write_text(json.dumps(result, indent=2) + '\n',
                                                   encoding='utf-8', newline='\n')
        utilities.refuse_existing(destination)
        stage.rename(destination)
    return {key: value for key, value in result.items() if key != 'files'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--arm', required=True, choices=('b1b2', 'b3'))
    args = parser.parse_args()
    try:
        result = materialise(args.repo, args.output, arm=args.arm)
    except (OSError, ValueError) as error:
        parser.exit(1, 'B source construction refused: ' + str(error) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
