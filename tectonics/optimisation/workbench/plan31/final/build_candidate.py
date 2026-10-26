"""Compose accepted source APIs for B3, Tier1 and paired receiving; no runtime admission."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
MAP_SHA = '416ce0835e98a991a76e4c8715f590ccdb33359ffc0e14092451b02f6964a292'
FLAGS = ('runtime_admission', 'default_changed', 'scientific_acceptance', 'interval_authority', 'selected', 'enablement')
COMPONENTS = {'b': {'path': 'tectonics/optimisation/workbench/plan21/b/build_candidate.py', 'sha256': 'c344d6b76566b158c1362d30e93ce5c062fbdbb27ee620ed0e6e0dda2015a796'}, 'tier1': {'path': 'tectonics/optimisation/workbench/plan31/tier1/build_candidate.py', 'sha256': '8d93c1ba72646b218f76e18df394115442258a1715341da5056b17d4811a961c'}, 'receiving': {'path': 'tectonics/optimisation/workbench/plan26/build_candidate.py', 'sha256': '0939a2f56dca66543b8b3c7a4ff403351b8750ce86d5a0f4d175f87dfc925fdc'}}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned(raw, expected, role):
    require(digest(raw) == expected, 'source pin differs: '+role)
    return raw


def module(repo, role, binding):
    path = repo/binding['path']
    raw = pinned(path.read_bytes(), binding['sha256'], role)
    spec = importlib.util.spec_from_file_location('_plan31_final_'+role, path)
    value = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), 'exec'), value.__dict__)
    return value


def contract(repo):
    repo = Path(repo).absolute()
    b = module(repo, 'B', COMPONENTS['b'])
    _, utilities, _, _, _ = b.contract(repo, 'b3')
    utilities.inside(Path(repo.anchor), repo.relative_to(repo.anchor).as_posix())
    mapping = utilities.read_map(pinned(utilities.read_source(HERE, 'SOURCE-MAP.json'), MAP_SHA, 'Plan31 map'))
    require(mapping['schema'] == 'atlas.public.plan31.final.source-composition.r1'
            and mapping['components'] == COMPONENTS and mapping['parent_arm'] == 'b3'
            and mapping['selected_source_members'] == 697
            and mapping['selected_native_files'] == 287 and mapping['selected_helper_files'] == 410
            and all(mapping.get(flag) is False for flag in FLAGS)
            and mapping['private_A1_selected'] is False and mapping['N9_width_selected'] is False
            and mapping['condition5_selected'] is False and mapping['IV_permitted'] is False,
            'closed source-only composition/authority contract differs')
    for binding in mapping['component_maps'].values():
        pinned(utilities.read_source(repo, binding['path']), binding['sha256'], binding['path'])
    for name, pin in mapping['emitter_api'].items():
        pinned(utilities.read_source(HERE, name), pin, name)
    tier1 = module(repo, 'Tier1', COMPONENTS['tier1'])
    receiving = module(repo, 'receiving', COMPONENTS['receiving'])
    return b, tier1, receiving, utilities, mapping


def verify_inventory(root, files, utilities):
    """Walk only the explicit output tree, refusing links before descending."""
    root = Path(root)
    utilities.inside(Path(root.anchor), root.relative_to(root.anchor).as_posix())
    pending, actual = [root], {}
    while pending:
        folder = pending.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                path = Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                require(not entry.is_symlink() and not getattr(info, 'st_file_attributes', 0) & 0x400,
                        'linked output member refused')
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    name = path.relative_to(root).as_posix()
                    if name != 'SOURCE-MANIFEST.json':
                        actual[name] = digest(utilities.read_source(root, name))
                else:
                    raise ValueError('non-regular output member')
    require(actual == files, 'complete output inventory differs')
    require(len({name.casefold() for name in files}) == len(files), 'casefold member collision')
    return actual


def materialise(repo, destination):
    repo, destination = Path(repo).absolute(), Path(destination).absolute()
    out = destination.resolve()
    for source in (repo, HERE):
        source = source.resolve()
        require(out != source and not out.is_relative_to(source) and not source.is_relative_to(out),
                'output overlaps read-only source')
    b, tier1, receiving, utilities, mapping = contract(repo)
    utilities.inside(Path(destination.anchor), destination.relative_to(destination.anchor).as_posix())
    utilities.refuse_existing(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.p31f-', dir=destination.parent) as temporary:
        stage = Path(temporary)/'source'
        b.materialise(repo, stage, arm='b3')
        prior = utilities.read_map(utilities.read_source(stage, 'SOURCE-MANIFEST.json'))
        require(prior['schema'] == 'atlas.public.plan21.b.materialised-source.r3'
                and prior['arm'] == 'b3' and prior['source_map_sha256'] == b.MAP_SHA
                and len(prior['files']) == 697 and all(prior.get(flag) is False for flag in FLAGS),
                'complete authenticated B3 predecessor differs')
        files, changes = dict(prior['files']), dict(prior['changed_rows'])
        verify_inventory(stage, files, utilities)
        _, _, tier_map, transform, prerequisite = tier1.load(repo)
        tier_outputs = tier1.derive({name: utilities.read_source(stage, name) for name in tier1.MEMBERS},
                                    tier_map, transform, prerequisite)
        for name, raw in tier_outputs.items():
            changes.setdefault(name, {'before': files[name]})['after'] = digest(raw)
            utilities.inside(stage, name).write_bytes(raw)
            files[name] = digest(raw)
        _, _, reader_map, applier = receiving.load(repo)
        reader_outputs = receiving.derive({name: utilities.read_source(stage, name) for name in receiving.MEMBERS},
                                           reader_map, utilities, applier)
        for name, raw in reader_outputs.items():
            changes.setdefault(name, {'before': files[name]})['after'] = digest(raw)
            utilities.inside(stage, name).write_bytes(raw)
            files[name] = digest(raw)
        require(len(changes) == mapping['changed_row_count_from_s1a'] == 15
                and len(files) == 697 and sum(name.startswith('src/') for name in files) == 287
                and sum(name.startswith('helpers/') for name in files) == 410
                and all(files[name] == pin for name, pin in mapping['native_runtime_outputs'].items()),
                'declared source rows/coverage/output pins differ')
        verify_inventory(stage, files, utilities)
        result = {'schema': 'atlas.public.plan31.final.materialised-source.r1',
            'status': 'INTEGRATED_SOURCE_CANDIDATE_NOT_QUALIFIED', 'source_map_sha256': MAP_SHA,
            'source_members': 697, 'native_members': 287, 'helper_members': 410,
            'parent_source_map_sha256': prior['source_map_sha256'],
            'selection_sha256': utilities.generation({'member': 'source/'+name, 'public_sha256': pin}
                                                     for name, pin in files.items()),
            'files': files, 'changed_rows_from_s1a': changes,
            'private_A1_selected': False, 'N9_width_selected': False, 'condition5_selected': False,
            'IV_permitted': False, 'runtime_policy_adopted': False, **dict.fromkeys(FLAGS, False)}
        (stage/'SOURCE-MANIFEST.json').write_text(json.dumps(result, sort_keys=True, indent=2)+'\n',
                                                encoding='utf-8', newline='\n')
        utilities.refuse_existing(destination)
        stage.rename(destination)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    record = materialise(args.repo, args.out)
    print(json.dumps({key: value for key, value in record.items() if key not in ('files', 'changed_rows_from_s1a')}, sort_keys=True))


if __name__ == '__main__':
    main()
