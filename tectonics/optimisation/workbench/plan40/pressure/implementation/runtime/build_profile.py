"""Construct an explicit pressure successor of an existing private fresh profile.

This is a bounded adaptation of Plan11 build_profile.derive: its vendored Inputs,
composition, inventory, path and canonical-encoding guards are reused unchanged.
The original derive hard-codes Plan11's eight-helper delta and cannot authorise a
different successor. No globals or expected identities in that builder are reset.
This constructor adds one native module, replaces the three pressure modules and
carries the two native replacements already selected by the predecessor public
map. Existing private helper bytes and external code/data references are retained.
It never imports Atlas, changes a default, starts a worker or grants interval GO.
All machine paths are explicit private contract values, not source constants.
"""
from __future__ import annotations

import argparse
import ast
import copy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path


SCHEMA = 'atlas.private.plan40.pressure-runtime-selection.r1'
PRESSURE = frozenset(('integration_pressure_coupling.py', 'integration_pressure_walls.py',
                      'integration_spatial_pressure.py'))
INHERITED = frozenset(('integration_differential_geometry.py', 'integration_sphere_quadrature.py'))
ADDED = 'pressure_midpoint_values.py'
SELECTED = {
    'integration_pressure_coupling.py': 'fe3e5865bb13215dae73c3c1a7b2133cb6991cae04668968ef0a7f4b3a6e18f9',
    'integration_pressure_walls.py': 'c755e8c75bfd0014020c8cc3cafbc607106a856dd64e3abd56c4c2af74f29e77',
    'integration_spatial_pressure.py': 'bb53a348c3d94933ce01d216c4ff7b6af887f3244a366a1edb41009b2ea187ac',
    ADDED: '6e81907f874e2f81f9d855cf22317b23e7b5067d1c76a3e5a8f3a12b530d6613',
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def read_contract(path, expected):
    raw = Path(path).read_bytes()
    require(digest(raw) == expected, 'explicit selection contract pin differs')
    value = json.loads(raw)
    require(set(value) == {'schema', 'builder', 'utility', 'entry', 'binding_factory', 'public_inputs', 'workspace', 'repo', 'public_map',
                           'predecessor_public_map', 'base', 'base_runtime', 'predecessor',
                           'target', 'runtime', 'evidence', 'bootstrap'} and value['schema'] == SCHEMA,
            'closed explicit pressure runtime selection required')
    row = value['utility']
    source = Path(row['path'])
    code = source.read_bytes()
    require(digest(code) == row['sha256'], 'vendored derivation guards differ from their selected identity')
    spec = importlib.util.spec_from_file_location('_pressure_profile_guards', source)
    utility = importlib.util.module_from_spec(spec)
    exec(compile(code, str(source), 'exec', dont_inherit=True), utility.__dict__)
    utility.ordinary(source)
    require(Path(value['builder']['path']) == Path(__file__).resolve(), 'different constructor refused')
    return value, utility, raw


def derive(contract_path, contract_pin):
    """Derive every successor byte; imports only the exact standard-library utility."""
    c, u, contract_raw = read_contract(contract_path, contract_pin)
    inputs = u.Inputs()
    require(inputs.doc(Path(contract_path), contract_pin) == c, 'selection changed during construction')
    for row in (c['builder'], c['utility'], c['bootstrap'], c['entry'], c['binding_factory'], c['public_inputs']):
        inputs.raw(Path(row['path']), row['sha256'])
    t, repo, base = (u.ordinary(Path(c[k]), directory=True) for k in ('workspace', 'repo', 'base'))
    target, runtime, evidence = (Path(c[k]) for k in ('target', 'runtime', 'evidence'))
    require(target.is_relative_to(t / 'ac') and runtime.is_relative_to(t / 'ac') and target != runtime,
            'fresh owned roots must be distinct descendants of the explicit workspace/ac')
    require(not u.exists(target) and not u.exists(runtime), 'preserve an existing successor root')
    u.ordinary(target.parent, directory=True)
    u.ordinary(runtime.parent, directory=True)
    u.ordinary(evidence, directory=True)
    require(not evidence.is_relative_to(repo) and not evidence.is_relative_to(target) and
            not evidence.is_relative_to(runtime), 'private construction evidence must be outside sources and runtime roots')
    predecessor = c['predecessor']
    require(set(predecessor) == {'composition', 'reviewed_inputs', 'manifest', 'profile', 'derivation'},
            'complete predecessor metadata required')
    rows = {name: (Path(row['path']), row['sha256']) for name, row in predecessor.items()}
    require(rows['composition'][0] == base / 'composition.json' and
            all(rows[name][0].parent == Path(c['base_runtime']) for name in ('manifest', 'profile', 'derivation')),
            'predecessor metadata escaped its exact roots')
    parent, reviewed, native, helpers = u.composition(inputs, base, rows['composition'][1],
                                                     *rows['reviewed_inputs'])
    require((len(native), len(helpers)) == (239, 398), 'selected predecessor inventory differs')
    public = inputs.doc(repo / c['public_map']['path'], c['public_map']['sha256'])
    old_public = inputs.doc(repo / c['predecessor_public_map']['path'], c['predecessor_public_map']['sha256'])
    require(public['predecessor_source_map_sha256'] == c['predecessor_public_map']['sha256'] and
            public['predecessor_public_selection_sha256'] == old_public['public_selection_sha256'] and
            public['selected_variant'] == 'CORE_PLUS_G4' and
            public['selected_groups'] == ['G1', 'G2', 'G3', 'G4', 'G7', 'G10'],
            'selected public successor/variant differs')

    def public_rows(document, count):
        entries = document['entries']
        mapping = {row['member']: row for row in entries}
        require(len(entries) == len(mapping) == count, 'public member coverage/uniqueness differs')
        identities = [{'member': row['member'], 'public_sha256': row['public_sha256']}
                      for row in sorted(entries, key=lambda row: row['member'])]
        raw = (json.dumps(identities, indent=2, ensure_ascii=True) + '\n').encode()
        require(digest(raw) == document['public_selection_sha256'], 'public selection identity differs')
        return mapping

    selected, prior_public = public_rows(public, 638), public_rows(old_public, 637)
    pressure_members = {'source/src/atlas_tectonics/' + name for name in PRESSURE}
    added_member = 'source/src/atlas_tectonics/' + ADDED
    require(set(selected) == set(prior_public) | {added_member} and
            {name for name in prior_public if prior_public[name] != selected[name]} == pressure_members,
            'undeclared public successor member change')
    before = {**{'src/' + name: pin for name, pin in native.items()},
              **{'helpers/' + name: pin for name, pin in helpers.items()}}
    payload, bindings, changed = {}, {}, set()
    for member, row in sorted(selected.items()):
        require(member.startswith('source/'), 'source selection member prefix differs')
        name = member[len('source/'):]
        public_path = u.member(repo, row['public_path'])
        public_raw = inputs.raw(public_path, row['public_sha256'])
        original = row['original_sha256']
        if before.get(name) == original:
            actual_path = u.member(base, name)
            actual = inputs.raw(actual_path, original)
        else:
            require(name.startswith('src/atlas_tectonics/') and
                    Path(name).name in PRESSURE | INHERITED | {ADDED}, 'undeclared private source delta: ' + name)
            require(row['public_sha256'] == original, 'selected native change must have exact accepted bytes')
            actual_path, actual = public_path, public_raw
            changed.add(name)
        require(digest(actual) == original, 'private/public original identity differs: ' + name)
        if Path(name).name in SELECTED and name.startswith('src/atlas_tectonics/'):
            require(original == SELECTED[Path(name).name], 'accepted pressure source differs: ' + name)
        ast.parse(actual) if name.endswith('.py') else None
        payload[name] = actual
        bindings[member] = dict(public_path=row['public_path'], public_sha256=row['public_sha256'],
                               runtime_source=str(actual_path), runtime_sha256=original,
                               public_transformations=row['transformations'])
    expected_changes = {'src/atlas_tectonics/' + name for name in PRESSURE | INHERITED | {ADDED}}
    require(changed == expected_changes and set(payload) == set(before) | {'src/atlas_tectonics/' + ADDED},
            'private source change/addition coverage differs')
    new_native = {name[4:]: digest(raw) for name, raw in payload.items() if name.startswith('src/')}
    new_helpers = {name[8:]: digest(raw) for name, raw in payload.items() if name.startswith('helpers/')}
    require((len(new_native), len(new_helpers)) == (240, 398) and new_helpers == helpers,
            'whole native/helper successor inventory differs')
    old, profile, prior_derived = (inputs.doc(*rows[name]) for name in ('manifest', 'profile', 'derivation'))
    require(prior_derived['composition_sha256'] == rows['composition'][1] and
            prior_derived['manifest_sha256'] == rows['manifest'][1] and
            prior_derived['profile_sha256'] == rows['profile'][1] and
            prior_derived['reviewed_inputs'] == c['predecessor']['reviewed_inputs'], 'predecessor derivation differs')
    rel = lambda path: path.relative_to(t).as_posix()
    roots = profile['import_roots']
    require(set(old) == {'files', 'source_hashes', 'data_only', 'completed_query_store', 'composition'} and
            old['completed_query_store'] == parent['completed_query_store'] == 'files' and
            old['composition'] == dict(root=rel(base), composition_json=rel(base / 'composition.json'),
                composition_sha256=rows['composition'][1], frozen=False, import_root_order=roots),
            'predecessor manifest/composition differs')
    require(profile['schema'] == 'atlas.fresh-interval-profile.v1' and profile['workspace'] == str(t) and
            profile['native_root'] == rel(base / 'src') and len(roots) == 2 and roots[0] == rel(base / 'helpers') and
            len(profile['modules']) == 21 and profile['source_manifest'] ==
            dict(path=rel(rows['manifest'][0]), sha256=rows['manifest'][1]) and
            old['source_hashes'] == {name: pin for name, pin in native.items() if name.endswith('.py')},
            'predecessor executable profile differs')
    owned_code = {rel(base / name): pin for name, pin in before.items() if name.endswith('.py')}
    owned_data = {rel(base / name): pin for name, pin in before.items() if not name.endswith('.py')}
    owned_data[rel(base / 'composition.json')] = rows['composition'][1]
    external_code = {name: pin for name, pin in old['files'].items() if name not in owned_code}
    external_data = {name: pin for name, pin in old['data_only'].items() if name not in owned_data}
    require((len(external_code), len(external_data)) == (14, 105) and
            old['files'] == {**external_code, **owned_code} and old['data_only'] == {**external_data, **owned_data} and
            not set(old['files']) & set(old['data_only']), 'predecessor code/data closure differs')
    for name, pin in {**old['files'], **old['data_only']}.items():
        require('bridge' not in Path(name).parts, 'excluded bridge path')
        inputs.verify(u.member(t, name), pin)
    generation = dict(selection=public['public_selection_sha256'], source_map=c['public_map'],
                      changes={name: digest(payload[name]) for name in sorted(changed)},
                      runtime_original_bindings=bindings)
    require('plan40_pressure' not in parent['staged'], 'preserve an existing pressure successor record')
    next_reviewed = copy.deepcopy(reviewed)
    next_reviewed.update(target=target.name, target_root=str(target), outputs=new_native,
                         staged=dict(parent['staged'], plan40_pressure=generation))
    for path, pin in inputs.pins.items():
        require(path not in next_reviewed['files'] or next_reviewed['files'][path] == pin,
                'historical reviewed input conflict: ' + path)
        next_reviewed['files'][path] = pin
    reviewed_path = evidence / 'reviewed-inputs.json'
    reviewed_raw = u.canonical(next_reviewed)
    composition = copy.deepcopy(parent)
    composition.update(root=str(target), outputs=new_native, helpers=new_helpers,
                       reviewed_inputs=str(reviewed_path), reviewed_inputs_sha256=digest(reviewed_raw),
                       staged=next_reviewed['staged'])
    composition_raw = u.canonical(composition)
    translate = lambda name: rel(target) + name[len(rel(base)):] if name.startswith(rel(base) + '/') else name
    new_roots = [translate(name) for name in roots]
    files = {**external_code, **{rel(target / name): digest(raw) for name, raw in payload.items() if name.endswith('.py')}}
    data = {**external_data, **{rel(target / name): digest(raw) for name, raw in payload.items() if not name.endswith('.py')},
            rel(target / 'composition.json'): digest(composition_raw)}
    require(len(files) == len(old['files']) + 1 and len(data) == len(old['data_only']) and
            not set(files) & set(data), 'successor code/data membership differs')
    manifest = dict(old, files=files, data_only=data,
                    source_hashes={name: pin for name, pin in new_native.items() if name.endswith('.py')},
                    composition=dict(root=rel(target), composition_json=rel(target / 'composition.json'),
                                     composition_sha256=digest(composition_raw), frozen=False, import_root_order=new_roots))
    manifest_raw = u.canonical(manifest)
    successor = copy.deepcopy(profile)
    successor.update(native_root=rel(target / 'src'), import_roots=new_roots,
                     modules={name: translate(path) for name, path in profile['modules'].items()},
                     advance_driver=dict(profile['advance_driver'], path=translate(profile['advance_driver']['path'])),
                     source_manifest=dict(path=rel(runtime / 'manifest.json'), sha256=digest(manifest_raw)),
                     output_directory=str(runtime / 'attempt-r1'), store_directory=str(runtime / 'store-r1'),
                     completed_query_directory=rel(runtime / 'queries-r1'))
    require(set(successor) == set(profile) and len(successor['modules']) == 21 and
            all(name in files for name in (*successor['modules'].values(), successor['advance_driver']['path'])) and
            files[successor['advance_driver']['path']] == successor['advance_driver']['sha256'] and
            successor['completed_query_limits'] == profile['completed_query_limits'],
            'successor profile schema/import/query contract differs')
    for field in ('output_directory', 'store_directory', 'completed_query_directory'):
        path = Path(successor[field])
        require(not u.exists(path if path.is_absolute() else t / path), 'runtime output already exists: ' + str(path))
    profile_raw = u.canonical(successor)
    source = Path(c['bootstrap']['path'])
    code = inputs.raw(source, c['bootstrap']['sha256'])
    spec = importlib.util.spec_from_file_location('_pressure_bootstrap_template', source)
    template = importlib.util.module_from_spec(spec)
    exec(compile(code, str(source), 'exec', dont_inherit=True), template.__dict__)
    bootstrap = template.render(t, target)
    ast.parse(bootstrap)
    inputs.recheck()
    record = dict(schema='atlas.private.plan40.pressure-profile-derivation.r1', status='PREPARED_NOT_QUALIFIED',
                  predecessor=predecessor, source_selection=c['public_map'],
                  public_selection_sha256=public['public_selection_sha256'],
                  composition_sha256=digest(composition_raw), manifest_sha256=digest(manifest_raw),
                  profile_sha256=digest(profile_raw), reviewed_inputs=dict(path=str(reviewed_path), sha256=digest(reviewed_raw)),
                  bootstrap=dict(path=str(evidence / 'bootstrap_native.py'), sha256=digest(bootstrap)),
                  native_outputs=240, helper_outputs=398, preserved_private_members=632,
                  inherited_selected_native=sorted(INHERITED), pressure_replacements=sorted(PRESSURE), added_native=ADDED,
                  external_code_files=14, external_data_files=105,
                  runtime_original_bindings=bindings, constructor=c['builder'], utility=c['utility'],
                  runtime_entry=c['entry'], binding_factory=c['binding_factory'], public_inputs=c['public_inputs'],
                  source_inputs=inputs.pins,
                  runner_module_lists_changed=False, default_changed=False, native_library_changed=False,
                  execution_authority=False, interval_authority=False, holds_released=False,
                  scientific_acceptance=False, historical_receipts_changed=False)
    outputs = {target / name: raw for name, raw in payload.items()}
    outputs.update({target / 'composition.json': composition_raw, reviewed_path: reviewed_raw,
                    runtime / 'manifest.json': manifest_raw, runtime / 'fresh-profile.json': profile_raw,
                    runtime / 'derivation.json': u.canonical(record), evidence / 'bootstrap_native.py': bootstrap})
    return inputs, outputs, record, contract_raw


def emit(mode, selection, selection_sha256, plan_sha256=None):
    require(mode in ('plan', 'apply'), 'explicit construction phase required')
    inputs, outputs, record, contract_raw = derive(selection, selection_sha256)
    c = json.loads(contract_raw)
    plan = Path(c['evidence']) / 'PLAN.json'
    planned = {str(path): dict(sha256=digest(raw), bytes=len(raw)) for path, raw in sorted(outputs.items())}
    plan_raw = json.dumps(dict(schema='atlas.private.plan40.pressure-runtime-plan.r1',
        selection_sha256=selection_sha256, outputs=planned), sort_keys=True, separators=(',', ':')).encode()
    inputs.recheck()
    try:
        if mode == 'plan':
            require(not plan.exists(), 'preserve an existing construction plan')
            with plan.open('xb') as stream:
                stream.write(plan_raw)
                stream.flush()
                os.fsync(stream.fileno())
        else:
            require(plan_sha256 is not None and digest(plan.read_bytes()) == plan_sha256 and
                    plan.read_bytes() == plan_raw, 'exact freshly rederived construction plan required')
            target, runtime = Path(c['target']), Path(c['runtime'])
            for root in (target, runtime):
                require(not root.exists(), 'preserve existing output root')
            for path in outputs:
                require(not path.exists(), 'preserve existing output file: ' + str(path))
            # No existing consumer points here. Install the complete source directory
            # before publishing its profile; no partially copied module can be selected.
            for root in (target, runtime):
                staged = root.with_name(root.name + '.constructing')
                require(not staged.exists(), 'preserve an unfinished constructor root')
                staged.mkdir()
                for path, raw in outputs.items():
                    if path.is_relative_to(root):
                        destination = staged / path.relative_to(root)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with destination.open('xb') as stream:
                            stream.write(raw)
                            stream.flush()
                            os.fsync(stream.fileno())
                inputs.recheck()
                os.replace(staged, root)
            for path, raw in outputs.items():
                if not path.is_relative_to(target) and not path.is_relative_to(runtime):
                    with path.open('xb') as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
            require(all(path.read_bytes() == raw for path, raw in outputs.items()), 'written successor bytes differ')
    finally:
        inputs.recheck()
    return dict(status='PREPARED_NOT_QUALIFIED', mode=mode, plan_sha256=digest(plan_raw),
                          profile_sha256=record['profile_sha256'], manifest_sha256=record['manifest_sha256'],
                          composition_sha256=record['composition_sha256'], source_members=638,
                          execution_authority=False, holds_released=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('plan', 'apply'))
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--selection-sha256', required=True)
    parser.add_argument('--plan-sha256')
    args = parser.parse_args()
    print(json.dumps(emit(args.mode, args.selection, args.selection_sha256, args.plan_sha256), sort_keys=True))


if __name__ == '__main__':
    main()
