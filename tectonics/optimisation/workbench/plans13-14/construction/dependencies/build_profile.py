"""Derive Plan11's source-only runtime metadata from exact r12 and r13 outputs.

Never imports Atlas or starts a workload. Execution needs a coordinator-cleared
source-construction bundle; existing runtime/output roots are never overwritten.
"""
from __future__ import annotations

import argparse
import copy
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import stat


W = Path('C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace')
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
HERE = W / 'work/plan11/integration-r1'
SELF = HERE / 'build_profile.py'
ADAPTER = HERE / 'assemble_plan11.py'
CONTRACT = HERE / 'assembly-selection-r1.json'
BASE = T / 'ac/p10-out/composed-r12'
TARGET = T / 'ac/p11-out/composed-r13'
OUTPUT = T / 'ac/p11-runtime-r1'
BASE_ENGINE = W / 'work/plan04/review-fixes-r1/plan09/retry-r2/assemble_r3_plan09_review_r2.py'
BASE_ENGINE_SHA = 'fa69d551af9f28b5f929e5d49323fce0b391843a9905867d2a437b88b887a04e'
STAGE = T / 'ac/p04r1/stage-record-review-r2.json'
STAGE_SHA = '9af89204f3bf520024bbfd9a7ed12b5041317b73d07584086c6e05b6834f2cc9'
PREDECESSOR = {
    'composition': (BASE / 'composition.json',
                    'ea39f0916b68a9d6e49ff32a450a7dc820dd641ca9c4dcb056278e6eb32e76c3'),
    'reviewed_inputs': (W / 'work/plan10/e2/reviewed-inputs.json',
                        '043de83ab1aae49a0e80feda5c196f7ab7c942cc5ac9462f750757f1feedf081'),
    'profile': (T / 'ac/p10-runtime-r1/fresh-profile.json',
                '86e38d44ec5a1782d585318f0c884c087f830a954f70f80720f231f301015d4c'),
    'manifest': (T / 'ac/p10-runtime-r1/manifest.json',
                 '30d40c9df7b836d7accb2d099eb05d0391c730bf822429d4643c565968087e1f'),
    'derivation': (T / 'ac/p10-runtime-r1/derivation.json',
                   '047a309e0b511cd90af631f86887f74b7e2314554992c23a13a8cca7f8ff346a'),
}
INHERITED = {
    'composition': (T / 'ac/p04r1-out/composed-r11/composition.json',
                    '6de582017c294b74dd8a5d1ccb8ea632e625679d60a863d923fe4dbc53daa7a6'),
    'reviewed_inputs': (W / 'work/plan04/review-fixes-r1/plan09/retry-r2/actual-inputs-r2.json',
                        '55c71255fa417792c49b463dd204c95ed90c7a8eb24284f8fa482993c2e35fcd'),
}
REPLACED = frozenset(('launch_fresh_interval.py', 'reopen_fresh_restart.py', 'fresh_interval_driver.py',
                      'prepared_interval_driver.py'))
ADDED = frozenset(('reader_overlap_gate.py', 'overlap_reader.py', 'overlap_cohort.py', 'overlap_metrics.py'))
HELPERS = REPLACED | ADDED
SELECTION_SCHEMA = 'atlas.private.plan11-overlap-selection.r1'
COMPOSITION_FIELDS = {'codec_policy', 'completed_query_store', 'frozen', 'helpers', 'outputs',
                      'reviewed_inputs', 'reviewed_inputs_sha256', 'root', 'root_rule', 'schema', 'staged', 'stages'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def pin(value):
    require(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
            'exact lowercase SHA-256 required')
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def exists(path):
    return os.path.lexists(path)


def ordinary(path, *, directory=False):
    path = Path(path)
    require(path.is_absolute() and path == path.resolve(), 'canonical absolute path required: ' + str(path))
    for item in (path, *path.parents):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'linked/reparse path refused: ' + str(item))
    require(path.is_dir() if directory else path.is_file(), 'ordinary path required: ' + str(path))
    return path


def member(root, name):
    require(type(name) is str and name and '\\' not in name and ':' not in name, 'noncanonical member: ' + str(name))
    parts = PurePosixPath(name).parts
    require(not PurePosixPath(name).is_absolute() and '/'.join(parts) == name and
            all(p not in ('.', '..') and p.rstrip(' .') == p for p in parts), 'member escape/alias refused: ' + name)
    path = ordinary(root / name)
    require(path.is_relative_to(root), 'member escaped its explicit root: ' + name)
    return path


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


class Inputs:
    def __init__(self):
        self.pins = {}
        self.inventories = []

    def raw(self, path, expected):
        path = ordinary(path)
        before = path.stat()
        data = path.read_bytes()
        after = ordinary(path).stat()
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'source changed during read: ' + str(path))
        actual = digest(data)
        require(actual == pin(expected), 'source differs from its explicit pin: ' + str(path))
        require(self.pins.get(str(path), actual) == actual, 'source changed between reads: ' + str(path))
        self.pins[str(path)] = actual
        return data

    def doc(self, path, expected):
        return json.loads(self.raw(path, expected), object_pairs_hook=unique,
                          parse_constant=lambda text: require(False, 'nonfinite JSON: ' + text))

    def verify(self, path, expected):
        known = self.pins.get(str(path))
        if known is None:
            self.raw(path, expected)
        else:
            require(known == pin(expected), 'conflicting source binding: ' + str(path))

    def recheck(self):
        for path, expected in tuple(self.pins.items()):
            self.raw(path, expected)
        for root, names in self.inventories:
            require(set(inventory(root)) == names, 'composition membership changed: ' + str(root))


def inventory(root, inputs=None, expected=None):
    """Traverse only an explicit src/helpers root; read bytes only under declared pins."""
    ordinary(root, directory=True)
    names = {}
    folded = set()
    for folder, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            ordinary(Path(folder) / name, directory=True)
        for name in files:
            path = ordinary(Path(folder) / name)
            key = path.relative_to(root).as_posix()
            require(key.casefold() not in folded, 'case-alias inventory collision: ' + key)
            folded.add(key.casefold())
            if inputs is None:
                names[key] = None
            else:
                require(type(expected) is dict and key in expected, 'unrecorded composition member: ' + key)
                names[key] = digest(inputs.raw(path, expected[key]))
    if expected is not None:
        require(set(names) == set(expected), 'missing or extra composition members: ' + str(root))
    return names


def reference(path, value):
    return {'path': str(path), 'sha256': value}


def references(rows):
    return {name: reference(path, value) for name, (path, value) in rows.items()}


def selection(inputs, path, value):
    require(Path(__file__).resolve() == SELF and ordinary(path) == CONTRACT, 'exact owned builder/selection paths required')
    contract = inputs.doc(path, pin(value))
    fields = {'schema', 'selection', 'adapter', 'profile_builder', 'base_assembler', 'predecessor',
              'inherited', 'stage', 'target', 'runtime', 'helpers'}
    require(type(contract) is dict and set(contract) == fields and contract['schema'] == SELECTION_SCHEMA,
            'closed Plan11 overlap selection required')
    require(type(contract['selection']) is str and bool(contract['selection'].strip()), 'explicit selection required')
    require(contract['target'] == str(TARGET) and contract['runtime'] == str(OUTPUT) and
            contract['base_assembler'] == reference(BASE_ENGINE, BASE_ENGINE_SHA) and
            contract['predecessor'] == references(PREDECESSOR) and contract['inherited'] == references(INHERITED) and
            contract['stage'] == reference(STAGE, STAGE_SHA), 'different selected engine/baseline/targets refused')
    for key, source in (('adapter', ADAPTER), ('profile_builder', SELF)):
        row = contract[key]
        require(type(row) is dict and set(row) == {'path', 'sha256'} and row['path'] == str(source),
                'exact selected ' + key + ' required')
        inputs.raw(source, pin(row['sha256']))
    rows = contract['helpers']
    require(type(rows) is dict and set(rows) == HELPERS, 'exactly eight selected helper rows required')
    for name, row in rows.items():
        source = HERE / 'helpers' / name
        require(type(row) is dict and set(row) == {'path', 'sha256'} and row['path'] == str(source),
                'different selected helper path: ' + name)
        inputs.raw(source, pin(row['sha256']))
    for source, expected in (BASE_ENGINE, BASE_ENGINE_SHA), (STAGE, STAGE_SHA):
        inputs.raw(source, expected)
    for group in (PREDECESSOR, INHERITED):
        for source, expected in group.values():
            inputs.raw(source, expected)
    selected = {'contract': reference(CONTRACT, value), 'selection': contract,
                'scope': 'eight selected helper inputs over r12; no native output changes; source construction only'}
    return contract, selected, dict(inputs.pins)


def relative(path):
    return path.relative_to(T).as_posix()


def translated(name):
    for part in ('src', 'helpers'):
        old, new = relative(BASE / part), relative(TARGET / part)
        if name == old or name.startswith(old + '/'):
            return new + name[len(old):]
    return name


def composition(inputs, root, value, reviewed_path, reviewed_pin):
    doc = inputs.doc(root / 'composition.json', pin(value))
    require(type(doc) is dict and set(doc) == COMPOSITION_FIELDS and
            doc['schema'] == 'atlas.private.resumable-composition.r3' and doc['root'] == str(root) and
            doc['frozen'] is False and doc['completed_query_store'] == 'files', 'composition contract differs')
    require({p.name for p in root.iterdir()} == {'src', 'helpers', 'composition.json'}, 'unexpected composition-root entries')
    require(doc['reviewed_inputs'] == str(reviewed_path) and doc['reviewed_inputs_sha256'] == reviewed_pin,
            'composition reviewed-input binding differs')
    reviewed = inputs.doc(reviewed_path, pin(reviewed_pin))
    native = inventory(root / 'src', inputs, doc['outputs'])
    helpers = inventory(root / 'helpers', inputs, doc['helpers'])
    inputs.inventories.extend(((root / 'src', set(native)), (root / 'helpers', set(helpers))))
    require(reviewed['outputs'] == native and {name: row['sha256'] for name, row in reviewed['helpers'].items()} == helpers and
            reviewed['staged'] == doc['staged'] and reviewed['stages'] == doc['stages'] and
            reviewed['target_root'] == str(root) and reviewed['target'] == root.name,
            'reviewed record differs from actual composition')
    return doc, reviewed, native, helpers


def derive(contract_path, contract_pin, composition_pin, reviewed_path, reviewed_pin):
    inputs = Inputs()
    contract, selected, assembly_sources = selection(inputs, contract_path, contract_pin)
    baseline, prior, native, helpers = composition(inputs, BASE, PREDECESSOR['composition'][1],
                                                  *PREDECESSOR['reviewed_inputs'])
    reviewed_path = ordinary(reviewed_path)
    require(reviewed_path.is_relative_to(HERE) and not reviewed_path.is_relative_to(HERE / 'helpers') and
            reviewed_path != CONTRACT, 'new reviewed inputs must be an owned evidence file outside helper sources')
    successor, reviewed, new_native, new_helpers = composition(inputs, TARGET, pin(composition_pin),
                                                              reviewed_path, pin(reviewed_pin))
    require(len(native) == 239 and len(helpers) == 385 and not ADDED & set(helpers), 'selected r12 inventory differs')
    changes = {name: row['sha256'] for name, row in contract['helpers'].items()}
    require(all(changes[name] != helpers[name] for name in REPLACED), 'declared replacement did not change')
    require(new_native == native and new_helpers == {**helpers, **changes} and len(new_helpers) == 389,
            'undeclared native/helper change, addition or omission')
    expected_rows = copy.deepcopy(prior['helpers'])
    expected_rows.update(contract['helpers'])
    require(reviewed['helpers'] == expected_rows, 'successor helper source rows differ from selected r12 plus eight')
    expected_inputs = dict(prior['files'])
    for name, expected in assembly_sources.items():
        require(name not in expected_inputs or expected_inputs[name] == expected,
                'selected assembly input conflicts with r12: ' + name)
        expected_inputs[name] = expected
    require(reviewed['files'] == expected_inputs, 'successor reviewed source/audit closure differs')
    require(successor['staged'] == dict(baseline['staged'], plan11=selected) and
            successor['stages'] == baseline['stages'] and successor['codec_policy'] == baseline['codec_policy'] and
            successor['root_rule'] == baseline['root_rule'], 'staged selection/numerical/policy boundary changed')
    old = inputs.doc(*PREDECESSOR['manifest'])
    profile = inputs.doc(*PREDECESSOR['profile'])
    derivation = inputs.doc(*PREDECESSOR['derivation'])
    require(derivation['status'] == 'PREPARED_SOURCE_ONLY' and
            derivation['composition_sha256'] == PREDECESSOR['composition'][1] and
            derivation['manifest_sha256'] == PREDECESSOR['manifest'][1] and
            derivation['profile_sha256'] == PREDECESSOR['profile'][1], 'r12 derivation identity differs')
    require(set(old) == {'files', 'source_hashes', 'data_only', 'completed_query_store', 'composition'},
            'base manifest schema differs')
    roots = [relative(BASE / 'helpers'), 'fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests']
    require(old['composition'] == dict(root=relative(BASE), composition_json=relative(BASE / 'composition.json'),
            composition_sha256=PREDECESSOR['composition'][1], frozen=False, import_root_order=roots) and
            old['completed_query_store'] == 'files', 'r12 manifest composition binding differs')
    require(profile['schema'] == 'atlas.fresh-interval-profile.v1' and
            profile['source_manifest'] == dict(path=relative(PREDECESSOR['manifest'][0]), sha256=PREDECESSOR['manifest'][1]) and
            profile['native_root'] == relative(BASE / 'src') and profile['import_roots'] == roots and
            profile['workspace'] == str(T) and type(profile['modules']) is dict and len(profile['modules']) == 20,
            'r12 profile binding/schema differs')
    native_py = {name: value for name, value in native.items() if name.endswith('.py')}
    require(old['source_hashes'] == native_py, 'native source inventory differs')
    owned_code = {**{relative(BASE / 'src' / name): value for name, value in native.items() if name.endswith('.py')},
                  **{relative(BASE / 'helpers' / name): value for name, value in helpers.items() if name.endswith('.py')}}
    external_code = {name: value for name, value in old['files'].items() if name not in owned_code}
    require(len(external_code) == 14 and old['files'] == {**external_code, **owned_code}, 'r12 code closure differs')
    owned_data = {**{relative(BASE / 'src' / name): value for name, value in native.items() if not name.endswith('.py')},
                  **{relative(BASE / 'helpers' / name): value for name, value in helpers.items() if not name.endswith('.py')},
                  relative(BASE / 'composition.json'): PREDECESSOR['composition'][1]}
    external_data = {name: value for name, value in old['data_only'].items() if name not in owned_data}
    require(len(external_data) == 104 and old['data_only'] == {**external_data, **owned_data} and
            not set(old['files']) & set(old['data_only']), 'r12 data closure differs')
    for name, expected in {**old['files'], **old['data_only']}.items():
        inputs.verify(member(T, name), expected)
    new_owned_code = {**{relative(TARGET / 'src' / name): value for name, value in new_native.items() if name.endswith('.py')},
                      **{relative(TARGET / 'helpers' / name): value for name, value in new_helpers.items() if name.endswith('.py')}}
    new_owned_data = {**{relative(TARGET / 'src' / name): value for name, value in new_native.items() if not name.endswith('.py')},
                      **{relative(TARGET / 'helpers' / name): value for name, value in new_helpers.items() if not name.endswith('.py')},
                      relative(TARGET / 'composition.json'): pin(composition_pin)}
    require(not set(external_code) & set(new_owned_code) and not set(external_data) & set(new_owned_data),
            'translated closure collided with external references')
    files, data = {**external_code, **new_owned_code}, {**external_data, **new_owned_data}
    require(len(files) == len(old['files']) + 4 and len(data) == len(old['data_only']) and not set(files) & set(data),
            'new code/data membership differs')
    for name, expected in {**files, **data}.items():
        inputs.verify(member(T, name), expected)
    result = copy.deepcopy(old)
    new_roots = [translated(name) for name in roots]
    result.update(files=files, data_only=data, source_hashes=native_py,
                  composition=dict(root=relative(TARGET), composition_json=relative(TARGET / 'composition.json'),
                                   composition_sha256=pin(composition_pin), frozen=False, import_root_order=new_roots))
    manifest_raw = canonical(result)
    new_profile = copy.deepcopy(profile)
    new_profile.update(native_root=translated(profile['native_root']), import_roots=new_roots,
        modules={name: translated(path) for name, path in profile['modules'].items()},
        advance_driver={**profile['advance_driver'], 'path': translated(profile['advance_driver']['path']),
                        'sha256': new_helpers['fresh_interval_driver.py']},
        source_manifest=dict(path=relative(OUTPUT / 'manifest.json'), sha256=digest(manifest_raw)),
        output_directory=str(OUTPUT / 'attempt-overlap-r1'), store_directory=str(OUTPUT / 'store-overlap-r1'),
        completed_query_directory=relative(OUTPUT / 'queries-overlap-r1'))
    require(set(new_profile) == set(profile) and len(new_profile['modules']) == 20 and
            new_profile['completed_query_limits'] == profile['completed_query_limits'], 'profile schema/query contract changed')
    for name in (*new_profile['modules'].values(), new_profile['advance_driver']['path']):
        require(name in files, 'profile imports outside pinned closure: ' + name)
    require(files[new_profile['advance_driver']['path']] == new_profile['advance_driver']['sha256'],
            'driver pin differs from actual successor')
    for field in ('output_directory', 'store_directory', 'completed_query_directory'):
        name = Path(new_profile[field])
        require(not exists(name if name.is_absolute() else T / name), 'runtime destination already exists: ' + str(name))
    profile_raw = canonical(new_profile)
    inputs.recheck()
    record = dict(schema='atlas.private.plan11.profile-derivation.r1', status='PREPARED_SOURCE_ONLY',
        root_eligibility='PENDING_SEPARATE_ELIGIBLE_LINEAGE_CLEARANCE_AND_SUCCESS', scientific_acceptance=False,
        interval_authority=False, holds_released=False, baseline=references(PREDECESSOR),
        plan11_selection=selected, composition_sha256=pin(composition_pin), reviewed_inputs=reference(reviewed_path, reviewed_pin),
        manifest_sha256=digest(manifest_raw), profile_sha256=digest(profile_raw),
        replaced_helpers={name: changes[name] for name in sorted(REPLACED)},
        added_helpers={name: changes[name] for name in sorted(ADDED)}, native_outputs=len(new_native), helper_outputs=len(new_helpers),
        external_code=len(external_code), external_data=len(external_data), source_inputs=inputs.pins,
        scope='serial independent reader admission and fixed SERIAL ALE comparable arms only; no execution grant',
        later_profile_rule='Any profile/source change requires its own authenticated eligible lineage; no old receipt repin.')
    return inputs, {'manifest.json': manifest_raw, 'fresh-profile.json': profile_raw,
                    'derivation.json': (json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan11-contract', type=Path, required=True)
    parser.add_argument('--plan11-contract-sha256', required=True)
    parser.add_argument('--composition-sha256', required=True)
    parser.add_argument('--reviewed-inputs', type=Path, required=True)
    parser.add_argument('--reviewed-inputs-sha256', required=True)
    args = parser.parse_args()
    require(not exists(OUTPUT), 'runtime output exists; preserve it')
    ordinary(OUTPUT.parent, directory=True)
    inputs, rows = derive(args.plan11_contract, args.plan11_contract_sha256, args.composition_sha256,
                          args.reviewed_inputs, args.reviewed_inputs_sha256)
    require(not exists(OUTPUT), 'runtime output appeared during derivation')
    OUTPUT.mkdir()
    for name, data in rows.items():
        with (OUTPUT / name).open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    inputs.recheck()
    require({p.name for p in OUTPUT.iterdir()} == set(rows), 'unexpected runtime output appeared')
    require(all((OUTPUT / name).read_bytes() == data for name, data in rows.items()), 'written metadata bytes differ')
    print(json.dumps(dict(passed=True, status='PREPARED_SOURCE_ONLY', output=str(OUTPUT),
                         files={name: digest(data) for name, data in rows.items()}, scientific_acceptance=False,
                         holds_released=False, root_eligibility='PENDING_SEPARATE_ELIGIBLE_LINEAGE_CLEARANCE_AND_SUCCESS'),
                     sort_keys=True))


if __name__ == '__main__':
    main()
