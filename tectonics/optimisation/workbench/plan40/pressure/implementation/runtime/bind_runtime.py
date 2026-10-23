"""Bind the public pressure selection to an exact compatible private predecessor.

Plan and apply use only explicit local roots and complete source pins. They do
not import Atlas, launch workers, change defaults or grant held scientific work.
The result is an actual fresh profile consumed by the existing runner/worker
contracts, with one explicit pinned runtime_entry binding for library callers.
"""
import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
PACKAGE = 'tectonics/optimisation/workbench/plan40/pressure/implementation/runtime'
SOURCE_NAMES = {'builder': 'build_profile.py', 'guards': 'profile_guards.py',
                'entry': 'runtime_entry.py', 'bootstrap': 'bootstrap_template.py', 'binder': 'bind_runtime.py'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def checked(path, expected):
    require(type(expected) is str and len(expected) == 64 and
            all(char in '0123456789abcdef' for char in expected), 'complete lowercase source pin required')
    raw = Path(path).read_bytes()
    require(sha256(raw).hexdigest() == expected, 'public construction source differs: ' + str(path))
    return raw


def load(path, expected, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(checked(path, expected), str(path), 'exec', dont_inherit=True), module.__dict__)
    return module


def bind(args):
    public_path = Path(args.selection)
    selected = json.loads(checked(public_path, args.selection_sha256))
    require(set(selected) == {'schema', 'identity_kind', 'sources', 'source_map', 'predecessor_map',
                              'predecessor', 'runtime_contract', 'original_guard_source_sha256',
                              'original_bootstrap_source_sha256'} and
            selected['schema'] == 'atlas.public.plan40.pressure-runtime-inputs.r1' and
            set(selected['sources']) == set(SOURCE_NAMES), 'closed published construction selection required')
    for name, filename in SOURCE_NAMES.items():
        require(set(selected['sources'][name]) == {'path', 'sha256'} and
                selected['sources'][name]['path'] == filename, 'different selected construction source: ' + name)
    u = load(HERE / 'profile_guards.py', selected['sources']['guards']['sha256'], '_pressure_public_guards')
    inputs = u.Inputs()
    require(u.ordinary(public_path) == HERE / 'selection.json' and
            inputs.doc(public_path, args.selection_sha256) == selected, 'public input selection path/content differs')
    repo = u.ordinary(Path(args.repo), directory=True)
    require(HERE == repo / PACKAGE, 'run the actual published constructor from its repository location')
    refs = {}
    for name, row in selected['sources'].items():
        source = u.member(HERE, row['path'])
        inputs.raw(source, row['sha256'])
        refs[name] = dict(path=str(source), sha256=row['sha256'])
    require(selected['runtime_contract'] == dict(native_members=240, helper_members=398,
            profile_helpers=21, external_code_files=14, external_data_files=105,
            default_changed=False, interval_authority=False, holds_released=False),
            'published runtime inventory/authority contract differs')
    workspace, base, old_runtime = (u.ordinary(Path(getattr(args, name)), directory=True)
                                    for name in ('workspace', 'base', 'base_runtime'))
    require(base.is_relative_to(workspace / 'ac') and old_runtime.is_relative_to(workspace / 'ac'),
            'compatible predecessor roots must be inside the explicit workspace/ac')
    predecessor = selected['predecessor']
    require(set(predecessor) == {'composition', 'reviewed_inputs', 'profile', 'manifest', 'derivation'},
            'complete predecessor pins required')
    composition = inputs.doc(base / 'composition.json', predecessor['composition'])
    require(composition['root'] == str(base) and composition['reviewed_inputs_sha256'] == predecessor['reviewed_inputs'],
            'predecessor root/reviewed identity differs')
    parent_refs = {
        'composition': dict(path=str(base / 'composition.json'), sha256=predecessor['composition']),
        'reviewed_inputs': dict(path=composition['reviewed_inputs'], sha256=predecessor['reviewed_inputs']),
        **{name: dict(path=str(old_runtime / filename), sha256=predecessor[name])
           for name, filename in (('profile', 'fresh-profile.json'), ('manifest', 'manifest.json'), ('derivation', 'derivation.json'))},
    }
    target, runtime, evidence = (Path(getattr(args, name)) for name in ('target', 'runtime', 'evidence'))
    for path in (target, runtime, evidence):
        require(path.is_absolute() and path == path.resolve(), 'explicit canonical destination required')
    require(target != runtime and target.is_relative_to(workspace / 'ac') and runtime.is_relative_to(workspace / 'ac'),
            'distinct fresh contained source/runtime roots required')
    require(not evidence.is_relative_to(repo) and not evidence.is_relative_to(target) and
            not evidence.is_relative_to(runtime), 'private evidence must stay outside source/runtime roots')
    require(not target.exists() and not runtime.exists(), 'preserve existing runtime/source roots')
    if not evidence.exists():
        u.ordinary(evidence.parent, directory=True)
        evidence.mkdir()
    u.ordinary(evidence, directory=True)
    contract = dict(schema='atlas.private.plan40.pressure-runtime-selection.r1', builder=refs['builder'],
        utility=refs['guards'], entry=refs['entry'], binding_factory=refs['binder'],
        public_inputs=dict(path=str(public_path), sha256=args.selection_sha256), workspace=str(workspace),
        repo=str(repo), public_map=selected['source_map'], predecessor_public_map=selected['predecessor_map'],
        base=str(base), base_runtime=str(old_runtime), predecessor=parent_refs, target=str(target),
        runtime=str(runtime), evidence=str(evidence), bootstrap=refs['bootstrap'])
    contract_raw = u.canonical(contract)
    contract_path = evidence / 'construction-selection.json'
    if args.mode == 'plan':
        require(not contract_path.exists(), 'preserve an earlier construction selection')
        with contract_path.open('xb') as stream:
            stream.write(contract_raw)
    else:
        require(contract_path.read_bytes() == contract_raw, 'apply must use its exact planned local bindings')
    builder = load(Path(refs['builder']['path']), refs['builder']['sha256'], '_pressure_public_builder')
    result = builder.emit(args.mode, contract_path, sha256(contract_raw).hexdigest(), args.plan_sha256)
    if args.mode == 'apply':
        binding = dict(schema='atlas.private.plan40.pressure-runtime-binding.r1',
            profile=dict(path=str(runtime / 'fresh-profile.json'), sha256=result['profile_sha256']),
            composition=dict(path=str(target / 'composition.json'), sha256=result['composition_sha256']),
            bootstrap=dict(path=str(evidence / 'bootstrap_native.py'),
                           sha256=sha256((evidence / 'bootstrap_native.py').read_bytes()).hexdigest()),
            entry=refs['entry'], source_selection=selected['source_map'])
        binding_path = evidence / 'runtime-binding.json'
        with binding_path.open('xb') as stream:
            stream.write(u.canonical(binding))
        result['runtime_binding'] = dict(path=str(binding_path), sha256=sha256(binding_path.read_bytes()).hexdigest())
    inputs.recheck()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('plan', 'apply'))
    for name in ('selection', 'repo', 'workspace', 'base', 'base-runtime', 'target', 'runtime', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--selection-sha256', required=True)
    parser.add_argument('--plan-sha256')
    args = parser.parse_args()
    print(json.dumps(bind(args), sort_keys=True))


if __name__ == '__main__':
    main()
