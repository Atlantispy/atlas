"""Plan31 historical-input producer support for explicit baseline and final lines.

The final constructor supplies its frozen selection, exact component pins, actual
identity measurement and reviewed per-source dispositions. This module neither
chooses optional transforms nor manufactures accepted review or measured identity.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

PLAN02_RELATIVE = 'tectonics/optimisation/workbench/plan02/prepared-construction-v2-r3/assemble_resumable.py'
PLAN02_SHA256 = 'c69731f55dcda5dc5984ef0ca15d9f78b8a4f44acb7a1bb652af03cabab72b83'
HISTORICAL_HELPER_SHA256 = 'e0c2879dc1290cabb4e9c86e0bed21113851988ad21fc81f51e88e7b84886f86'
POLICY_SCHEMA = 'atlas.reviewed-runtime-state-transfer.v1'
POLICY_CONSTRAINTS = {
    'transfer': 'unchanged accepted physical state only',
    'history': 'retain original producer and complete historical acceptance',
    'funding': 'no reset and no additional debit',
    'physics': 'identical closed scientific plan graph',
    'numeric_acceptance': 'existing approved accuracy limits unchanged',
    'cached_proofs': 'not reusable across runtime identities',
    'new_intervals': 'actual current runtime validation required',
}

class FinalGenerationRefused(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise FinalGenerationRefused(message)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')

def pin(value):
    require(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
            'explicit lowercase SHA256 required')
    return value

def member(workspace, name):
    require(type(name) is str and name and ':' not in name and '\\' not in name,
            'canonical workspace-relative operand required')
    relative = Path(name)
    require(relative.as_posix() == name and not relative.is_absolute() and '..' not in relative.parts
            and 'bridge' not in [part.casefold() for part in relative.parts],
            'escaped/excluded workspace operand')
    path = Path(workspace) / relative
    require(path.resolve().is_relative_to(Path(workspace).resolve()), 'workspace operand escaped')
    return path

def public_plan02(repo_root):
    """The legacy public component is not this frozen historical-input component."""
    raise FinalGenerationRefused('explicit frozen historical-input component binding required')


def authenticate_plan02(inputs, *, binding):
    """Authenticate the frozen component and its sibling before actual construction."""
    require(type(binding) is dict and set(binding) == {'path', 'sha256'}
            and binding['sha256'] == PLAN02_SHA256 and Path(binding['path']).is_absolute(),
            'explicit frozen historical-input component binding required')
    path = Path(binding['path'])
    raw = inputs.raw(path, PLAN02_SHA256)
    inputs.raw(path.with_name('historical_input_contract.py'), HISTORICAL_HELPER_SHA256)
    name = '_plan31_historical_plan02_c69731f5'
    require(name not in sys.modules, 'selected component module name already occupied')
    spec = importlib.util.spec_from_file_location(name, path)
    component = importlib.util.module_from_spec(spec)
    sys.modules[name] = component
    try:
        exec(compile(raw, str(path), 'exec', dont_inherit=True), component.__dict__)
    except BaseException:
        del sys.modules[name]
        raise
    return component


def validate_source_closure(inputs, *, workspace, native_root, manifest_binding,
                            profile_paths, expected_native_members, inventory):
    """Authenticate all declared files and exact native membership in one selected root."""
    require(type(manifest_binding) is dict and set(manifest_binding) == {'path', 'sha256'},
            'explicit source manifest binding required')
    manifest = inputs.doc(member(workspace, manifest_binding['path']), pin(manifest_binding['sha256']))
    files, data, native = (manifest.get(k) for k in ('files', 'data_only', 'source_hashes'))
    require(all(type(v) is dict and v for v in (files, data, native))
            and not files.keys() & data.keys() and manifest.get('completed_query_store') == 'files',
            'complete disjoint files/data/native maps and files query-store required')
    validate_historical_inputs(inputs, workspace=workspace, manifest=manifest,
                               historical_inputs=HISTORICAL_INPUTS)
    names = [*files, *data]
    require(len({name.casefold() for name in names}) == len(names),
            'case-insensitive closure destination collision')
    require(not set(profile_paths) & set(names), 'generated profile in its upstream source manifest')
    for name, expected in (*files.items(), *data.items()):
        inputs.raw(member(workspace, name), pin(expected))
    source_root = member(workspace, native_root)
    composition_ref = manifest.get('composition')
    require(type(composition_ref) is dict, 'explicit composition binding required')
    composition = inputs.doc(member(workspace, composition_ref['composition_json']),
                             pin(composition_ref['composition_sha256']))
    declared = composition.get('outputs')
    require(type(declared) is dict and len(declared) == expected_native_members,
            'complete native source/data composition required')
    # Reuse the pinned constructor utility's exact-root, no-follow inventory.
    # Native data members are part of the full tree, while source_hashes and the
    # strict runtime source digest contain Python members only.
    paths = inventory(source_root, inputs, declared)
    inputs.inventories.append((source_root, set(declared)))
    require(paths.keys() == declared.keys(), 'complete actual native source/data membership differs')
    for name in paths:
        expected = pin(declared[name])
        mapping = files if name.endswith('.py') else data
        require(mapping.get(native_root + '/' + name) == expected,
                'native source/data member missing from its manifest partition')
    actual = {name: declared[name] for name in paths
              if name.startswith('atlas_tectonics/') and name.endswith('.py')}
    require(actual == native, 'complete actual executable native inventory differs')
    inputs.recheck()
    return manifest, actual, sha(canonical(actual))

def build_policy(inputs, *, workspace, evidence_root, historical, current,
                 reviewed_changes, evidence):
    """Derive closed policy bytes from measured identities and explicit reviewed rows.

    Historical/current are complete caller-selected sides. This is construction;
    actual strict identity capture and implementation acceptance remain required.
    """
    root = member(workspace, evidence_root)
    require(root.is_dir(), 'explicit contained evidence root must exist')
    fields = {'source_hashes', 'native_source_digest', 'source_manifest_path',
              'source_manifest_sha256', 'execution_identity'}
    for label, side in (('historical', historical), ('current', current)):
        require(type(side) is dict and set(side) == fields, 'closed ' + label + ' policy side required')
        mapping = side['source_hashes']
        require(type(mapping) is dict and mapping and all(type(k) is str and k for k in mapping),
                'complete source map required')
        for expected in mapping.values():
            pin(expected)
        require(pin(side['native_source_digest']) == sha(canonical(mapping)), label + ' native digest differs')
        pin(side['execution_identity'])
        inputs.raw(member(root, side['source_manifest_path']), pin(side['source_manifest_sha256']))
    delta = {name for name in set(historical['source_hashes']) | set(current['source_hashes'])
             if historical['source_hashes'].get(name) != current['source_hashes'].get(name)}
    require(type(reviewed_changes) is dict and set(reviewed_changes) == delta,
            'review coverage must equal all changed/added/removed native members')
    require(type(evidence) is dict and evidence, 'explicit bound review evidence required')
    for name, expected in evidence.items():
        inputs.raw(member(root, name), pin(expected))
    for name, row in reviewed_changes.items():
        require(type(row) is dict and set(row) == {'before', 'after', 'reason', 'evidence'}
                and row['before'] == historical['source_hashes'].get(name)
                and row['after'] == current['source_hashes'].get(name)
                and type(row['reason']) is str and row['reason'].strip()
                and type(row['evidence']) is list and row['evidence']
                and all(type(ref) is str and ref in evidence for ref in row['evidence']),
                'unbound or unexplained actual native delta: ' + name)
    policy = {'schema': POLICY_SCHEMA, 'constraints': dict(POLICY_CONSTRAINTS),
              'historical': historical, 'current': current,
              'reviewed_changes': reviewed_changes, 'evidence': evidence}
    inputs.recheck()
    return policy, canonical(policy)

def build_prepared_profile(component, *, bindings, policy_raw):
    """Use the actual accepted pure producer API after emitted sources/manifest exist."""
    require(type(bindings) is dict and 'compatibility_policy_raw' not in bindings,
            'explicit schema-less prepared bindings required')
    return component.build_restart_profile(**bindings, compatibility_policy_raw=policy_raw)

def paired_config(component, *, construction_receipt, derivation, composition,
                  fresh_profile, prepared_profile, fresh_runner, prepared_runner,
                  compatibility_policy, prepared_record):
    """Connect actual final records to the accepted consumer; validate before return."""
    require(type(prepared_record) is dict and prepared_record.get('schema') == 'atlas.prepared-restart-launch.v3',
            'actual emitted prepared-v3 record required')
    config = {'schema': 'atlas.prepared-restart-construction.v3',
              'construction_receipt': construction_receipt, 'derivation': derivation,
              'composition': composition, 'constructor_profile': fresh_profile,
              'prepared_profile': prepared_profile, 'fresh_runner': fresh_runner,
              'prepared_runner': prepared_runner, 'compatibility_policy': compatibility_policy,
              'profile': {key: value for key, value in prepared_record.items() if key != 'schema'}}
    require(component.selected_restart_profile(config) == prepared_record,
            'actual prepared consumer returned a different profile')
    return config


# Fixed line choices; generated identities remain downstream of source emission.
import ast
import os
import subprocess

HISTORICAL_INPUTS = {'path': 'ac/p31-hi-data-r1/HISTORICAL-INPUTS-r1.json',
                     'sha256': '019944bf42007397c3cacb8756ea2e62862afa5170c79e28601d7a914cd86d22'}
LINE_ROOTS = {'baseline': ('ac/p1820c-r4-hi-r2', 'ac/p1820-run-r4-hi-r2'),
              'final': ('ac/n12f-r4', 'ac/n12f-run-r4')}
HISTORICAL_ROOT = 'fidelity-integration-20261005/heat-repair-20261007'
HISTORICAL_NATIVE = HISTORICAL_ROOT + '/native-composed-r7/tectonics/src'
HISTORICAL_MANIFEST = HISTORICAL_ROOT + '/continuation-preparation-r3.json'
HISTORICAL_MANIFEST_PIN = 'f81fd25ca3b68d031b006a0e6eab4d6b278affa86e5d062baeafd748f17ee42c'
HISTORICAL_RECEIPT = HISTORICAL_ROOT + '/heat-original-connected-20261013-r9.json'
HISTORICAL_RECEIPT_PIN = 'ca35700a8106d46eb67c876cd15fb5bf86d6abee7480cc94a23acbef68bb4f0d'
HISTORICAL_NATIVE_DIGEST = '746eea53c8dc9c9c89c8f7db8474e579fd5d2a2b919615b287358ddd4cb29d28'
HISTORICAL_EXECUTION = '6aa7a30cbe577a80d0a4f93d23b22a09525bb509e1e3f8f0f57e6fe09bc9ccad'
HISTORICAL_SEED_PATH = 'ac/n12f-run-r3/runtime-policy.json'
HISTORICAL_SEED_SHA256 = '8f3d2eb2e361bf5e5166a1636c561f2b5b59506ef548864812a0b027e2f318f7'
RUNNER_PINS = {
    'baseline': {'run_fresh_interval': 'e249a04743515d2f6018c351691bf4c599c1909d8f3a61845c931922ab9b0a5f',
                 'run_prepared_restart': '4322cbb80b1f67f61f7029fa7d5e5a8517714a2f8401bbeb5e574a0e1a5c3f75'},
    'final': {'run_fresh_interval': 'a02498406cd15521b92a81a679a0c84e893fbeb93402fe9b10699b93386e56eb',
              'run_prepared_restart': 'f7c6594e761bd722febb93a92cd7cd016c36dd5bc0b3ec1042d68adaef3929ef'}}
PROBE_PINS = {'baseline': '071d087e03b5b9eaf84cef93bc7ea14512a48cbead6aabc5298608eb9998628c',
              'final': 'd7c1fdcd756720eabaf3689fcd2b6e61a94eaf7ea2ab5c0a8fdcbea04f150feb'}
FIXTURE_NAMES = {'i04_differential_fixture', 'i04_differential_modes', 'test_i04_differential_force'}
DRIVER_PINS = {
    'baseline': {'fresh_interval_driver': '6d7202d849e6a4363edadcd5e3415d0ce4a8379677022f1e55e20713bb174897',
                 'prepared_interval_driver': '21b5874cbab82138285582f895aeab27f7cb77db851f9050b0498dc5a5bdbf80'},
    'final': {'fresh_interval_driver': '9bc213811479c4602c29a0a7502e310002c8310d0a36ee2da8730c32de8a8881',
              'prepared_interval_driver': '21b5874cbab82138285582f895aeab27f7cb77db851f9050b0498dc5a5bdbf80'}}
PREPARATION_PIN = 'a5bdfa249d594a65757ab3b48b93690c648dc2b6125e39752ec4ac090a29b55f'
FRESH_PROFILE_FIELDS = {'schema', 'workspace', 'source_manifest', 'native_root', 'import_roots',
    'modules', 'advance_driver', 'output_directory', 'store_directory',
    'completed_query_directory', 'completed_query_limits', 'historical_inputs'}
PREPARED_PROFILE_FIELDS = {'schema', 'workspace', 'source_manifest', 'native_root', 'import_roots',
    'modules', 'preparation', 'compatibility_policy', 'evidence_root', 'historical_root',
    'historical_source_root', 'advance_driver', 'output_directory', 'store_limits',
    'compression', 'completed_query_directory', 'completed_query_limits', 'historical_inputs'}


PROFILE_CONTEXT = None

def configure(*, source_root, runtime_root, profile_maps, source_pins):
    """Bind explicit authenticated selected bytes; never discover or choose sources."""
    global PROFILE_CONTEXT, LINE_ROOTS, RUNNER_PINS, PROBE_PINS, DRIVER_PINS, PREPARATION_PIN
    require(PROFILE_CONTEXT is None, 'profile context already bound')
    require(type(source_root) is str and type(runtime_root) is str
            and source_root.startswith('ac/') and runtime_root.startswith('ac/')
            and len(source_root.split('/')) == len(runtime_root.split('/')) == 2
            and source_root != runtime_root, 'explicit disjoint ac source/runtime roots required')
    for value in (source_root, runtime_root):
        require(all(p and p not in ('.','..') and p.rstrip(' .') == p for p in value.split('/'))
                and not any(c in value for c in '\\:\0'), 'unsafe profile root')
    require(type(profile_maps) is dict and set(profile_maps) == {'fresh','prepared'}
            and all(type(v) is dict for v in profile_maps.values()), 'two explicit profile maps required')
    require(type(source_pins) is dict and set(source_pins) == {'runners','probe','drivers','preparation'},
            'closed selected profile source pins required')
    runners, drivers = source_pins['runners'], source_pins['drivers']
    require(type(runners) is dict and set(runners) == {'run_fresh_interval','run_prepared_restart'}
            and type(drivers) is dict and set(drivers) == {'fresh_interval_driver','prepared_interval_driver'},
            'exact runner/driver pins required')
    for value in (*runners.values(), *drivers.values(), source_pins['probe']):
        pin(value)
    prep = source_pins['preparation']
    require(type(prep) is dict and set(prep) == {'path','sha256'}
            and prep['path'] == source_root+'/helpers/runtime_radial_fixture.py',
            'explicit runtime radial preparation required')
    pin(prep['sha256'])
    for mapping in profile_maps.values():
        require(all(type(n) is str and n.isidentifier() and type(p) is str
                    and p.startswith(source_root+'/') for n,p in mapping.items()), 'unsafe profile member map')
        require('runtime_production_entry' not in mapping, 'production policy is not an extra profile slot')
    PROFILE_CONTEXT = {'maps': {k:dict(v) for k,v in profile_maps.items()}, 'preparation':dict(prep)}
    LINE_ROOTS = {'final': (source_root,runtime_root)}
    RUNNER_PINS = {'final':dict(runners)}
    PROBE_PINS = {'final':source_pins['probe']}
    DRIVER_PINS = {'final':dict(drivers)}
    PREPARATION_PIN = prep['sha256']



def generation_layout(*, line):
    require(PROFILE_CONTEXT is not None and line == 'final', 'explicit configured final line required')
    source,runtime = LINE_ROOTS[line]
    return {'line':line,'source_root':source,'runtime_root':runtime,'native_root':source+'/src',
        'helper_root':source+'/helpers','import_roots':[source+'/helpers'],
        'manifest_path':runtime+'/manifest.json','policy_path':runtime+'/runtime-policy.json',
        'profile_paths':{'fresh':runtime+'/fresh-profile.json','prepared':runtime+'/prepared-profile.json'},
        'historical_inputs':dict(HISTORICAL_INPUTS)}

def checked_layout(layout):
    require(type(layout) is dict, 'explicit selected layout required')
    expected = generation_layout(line=layout.get('line'))
    require(all(layout.get(key) == value for key, value in expected.items()),
            'selected line/layout bindings differ')
    return expected


def validate_historical_inputs(inputs, *, workspace, manifest, historical_inputs):
    """Authenticate only the fixed external catalogue and its disjoint data binding."""
    require(type(historical_inputs) is dict and historical_inputs == HISTORICAL_INPUTS,
            'exact shared historical-input reference required')
    files, data = manifest.get('files'), manifest.get('data_only')
    require(type(files) is dict and type(data) is dict and not files.keys() & data.keys()
            and historical_inputs['path'] not in files
            and data.get(historical_inputs['path']) == historical_inputs['sha256'],
            'historical-input catalogue must be exclusively bound as data_only')
    inputs.raw(member(workspace, historical_inputs['path']), historical_inputs['sha256'])


def literal_modules(raw, *, consumer, constant, count, line):
    """Read the complete literal tuple from this line's authenticated runner."""
    require(line in RUNNER_PINS and consumer in RUNNER_PINS[line]
            and sha(raw) == RUNNER_PINS[line][consumer], 'selected runner changed: ' + consumer)
    tree = ast.parse(raw)
    nodes = [n for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == constant for t in n.targets)]
    require(len(nodes) == 1 and len(nodes[0].targets) == 1, 'unique closed module constant required')
    names = ast.literal_eval(nodes[0].value)
    require(type(names) is tuple and len(names) == count and len(set(names)) == count
            and all(type(n) is str and n.isidentifier() for n in names),
            'selected complete consumer module tuple differs')
    return names


def profile_layout(inputs, *, workspace, payload, parent_fresh_binding, line):
    selected = generation_layout(line=line)
    parent = inputs.doc(Path(parent_fresh_binding['path']),pin(parent_fresh_binding['sha256']))
    fresh_names = literal_modules(payload['helpers/run_fresh_interval.py'],consumer='run_fresh_interval',constant='FRESH_MODULES',count=21,line=line)
    prepared_names = literal_modules(payload['helpers/run_prepared_restart.py'],consumer='run_prepared_restart',constant='REQUIRED_MODULES',count=41,line=line)
    require(parent.get('schema') == 'atlas.fresh-interval-profile.v2'
            and parent.get('workspace') == str(Path(workspace))
            and parent.get('historical_inputs') == HISTORICAL_INPUTS,
            'actual parent fresh-v2 historical frame required')
    maps = PROFILE_CONTEXT['maps']
    require(set(maps['fresh']) == set(fresh_names) and set(maps['prepared']) == set(prepared_names),
            'profile keys differ from exact 21/41 required runner tuples')
    for mapping in maps.values():
        for name,path in mapping.items():
            prefix = selected['source_root']+'/'
            require(path.startswith(prefix) and path[len(prefix):] in payload, 'profile member outside selected payload: '+name)
    require(all(maps['fresh'][n] == maps['prepared'][n] for n in maps['fresh'].keys() & maps['prepared'].keys()),
            'shared profile member aliases differ')
    drivers = {}
    for name,expected in DRIVER_PINS[line].items():
        key = 'helpers/'+name+'.py'
        require(key in payload and sha(payload[key]) == expected, 'selected driver differs: '+name)
        drivers[name] = {'module':name,'path':selected['source_root']+'/'+key,'sha256':expected}
    require(sha(payload['helpers/historical_input_contract.py']) == HISTORICAL_HELPER_SHA256,
            'fixed historical helper differs')
    preparation = dict(PROFILE_CONTEXT['preparation'])
    key = preparation['path'][len(selected['source_root'])+1:]
    require(key in payload and sha(payload[key]) == preparation['sha256'], 'runtime radial preparation differs')
    quota = parent['completed_query_limits']
    require(quota == {'max_entries':2000000,'max_store_bytes':8589934592}, 'fixed files-query limits differ')
    inputs.recheck()
    return dict(selected,workspace=str(Path(workspace)),fresh_modules=dict(maps['fresh']),prepared_modules=dict(maps['prepared']),
        drivers=drivers,preparation=preparation,fresh_output=str(Path(workspace)/selected['runtime_root']/'attempt-r1'),
        fresh_store=str(Path(workspace)/selected['runtime_root']/'store-r1'),fresh_queries=selected['runtime_root']+'/queries-r1',
        prepared_output=str(Path(workspace)/selected['runtime_root']/'prepared-attempt-r1'),
        prepared_queries=selected['runtime_root']+'/prepared-queries-r1',query_limits=dict(quota),evidence_root='.')

def historical_policy_inputs(inputs, *, workspace, seed_policy_binding):
    """Reconcile actual original producer identity, all 230 sources and native settings."""
    require(type(seed_policy_binding) is dict and set(seed_policy_binding) == {'path', 'sha256'}
            and Path(seed_policy_binding['path']).resolve() == member(workspace, HISTORICAL_SEED_PATH).resolve()
            and seed_policy_binding['sha256'] == HISTORICAL_SEED_SHA256,
            'exact common historical policy seed required')
    seed = inputs.doc(Path(seed_policy_binding['path']), HISTORICAL_SEED_SHA256)
    manifest = inputs.doc(member(workspace, HISTORICAL_MANIFEST), HISTORICAL_MANIFEST_PIN)
    receipt = inputs.doc(member(workspace, HISTORICAL_RECEIPT), HISTORICAL_RECEIPT_PIN)
    prefix = 'native-composed-r7/tectonics/src/'
    source_hashes = {name[len(prefix):]: expected for name, expected in manifest['files'].items()
                     if name.startswith(prefix) and name.endswith('.py')}
    require(len(source_hashes) == 230 and sha(canonical(source_hashes)) == HISTORICAL_NATIVE_DIGEST,
            'complete selected historical Python inventory differs')
    for name, expected in source_hashes.items():
        inputs.raw(member(workspace, HISTORICAL_NATIVE + '/' + name), pin(expected))
    endpoint = receipt['completed_endpoint']
    require(receipt['native_source_digest'] == HISTORICAL_NATIVE_DIGEST
            and receipt['preparation_manifest_sha256'] == HISTORICAL_MANIFEST_PIN
            and endpoint['execution_provenance'] == {'execution_identity': HISTORICAL_EXECUTION,
                                                    'execution_mode': 'strict'},
            'original historical producer identity differs')
    require(set(endpoint['store_compression']) == {'codec', 'level', 'shuffle', 'palette', 'categorical', 'use_dict'}
            and endpoint['store_compression'] == {'codec': 'raw', 'level': 1, 'shuffle': 'byte',
                                                'palette': True, 'categorical': 'auto', 'use_dict': False}
            and all(type(v) is int and v > 0 for k, v in endpoint['store_limits'].items()
                    if k != 'decoded_cache_bytes') and endpoint['store_limits']['decoded_cache_bytes'] == 0,
            'explicit original native store/compression settings differ')
    inputs.recheck()
    side = {'source_hashes': source_hashes, 'native_source_digest': HISTORICAL_NATIVE_DIGEST,
            'source_manifest_path': HISTORICAL_MANIFEST, 'source_manifest_sha256': HISTORICAL_MANIFEST_PIN,
            'execution_identity': HISTORICAL_EXECUTION}
    require(seed.get('schema') == POLICY_SCHEMA and seed.get('historical') == side,
            'authenticated common historical seed differs from original producer metadata')
    inputs.recheck()
    return side, dict(endpoint['store_limits']), dict(endpoint['store_compression'])


def current_policy_side(*, measurement, source_hashes, manifest_binding, workspace, layout):
    """Validate this line's actual strict v2 measurement, including the fixed data ref."""
    selected = checked_layout(layout)
    require(type(manifest_binding) is dict and set(manifest_binding) == {'path', 'sha256'}
            and manifest_binding['path'] == selected['manifest_path'], 'exact emitted selected manifest required')
    require(type(source_hashes) is dict and source_hashes, 'complete current source map required')
    for expected in source_hashes.values():
        pin(expected)
    digest = sha(canonical(source_hashes))
    require(type(measurement) is dict and measurement.get('schema') == 'atlas.execution-identity-probe.v2'
            and measurement.get('status') == 'MEASURED_NOT_REVIEWED'
            and measurement.get('fresh_process') is True and measurement.get('policy_written') is False
            and measurement.get('source_manifest_sha256') == pin(manifest_binding['sha256'])
            and measurement.get('native_source_digest') == digest
            and measurement.get('native_root') == selected['native_root']
            and measurement.get('import_roots') == selected['import_roots']
            and measurement.get('historical_inputs') == HISTORICAL_INPUTS
            and measurement.get('backend') == 'scipy'
            and measurement.get('launch_environment') == {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
                'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONHASHSEED': '0'}
            and type(measurement.get('loaded_workspace_sources')) is int
            and measurement['loaded_workspace_sources'] > 0, 'actual strict selected measurement differs')
    interpreter = measurement.get('interpreter')
    require(type(interpreter) is dict and type(interpreter.get('executable')) is str
            and Path(interpreter['executable']).resolve() == (Path(workspace)/'.r44-env/Scripts/python.exe').resolve()
            and interpreter.get('hash_randomization') == 0, 'selected isolated probe interpreter differs')
    provenance = measurement.get('execution_provenance')
    require(type(provenance) is dict and set(provenance) == {'execution_identity', 'execution_mode'}
            and provenance['execution_mode'] == 'strict', 'strict execution provenance required')
    return {'source_hashes': dict(source_hashes), 'native_source_digest': digest,
            'source_manifest_path': selected['manifest_path'], 'source_manifest_sha256': manifest_binding['sha256'],
            'execution_identity': pin(provenance['execution_identity'])}


def capture_final_identity(inputs, *, workspace, manifest_binding, source_hashes, layout):
    """Launch this line's actual pinned store-free v2 probe only after source emission."""
    require(sys.dont_write_bytecode, 'constructor must run with -B')
    selected = checked_layout(layout)
    require(manifest_binding['path'] == selected['manifest_path'], 'selected manifest location differs')
    manifest = inputs.doc(member(workspace, selected['manifest_path']), pin(manifest_binding['sha256']))
    require(manifest['source_hashes'] == source_hashes, 'actual emitted manifest/source map differs')
    validate_historical_inputs(inputs, workspace=workspace, manifest=manifest,
                               historical_inputs=selected['historical_inputs'])
    probe_name = selected['helper_root'] + '/probe_execution_identity.py'
    runner_name = selected['helper_root'] + '/run_prepared_restart.py'
    probe_pin = PROBE_PINS[selected['line']]
    runner_pin = RUNNER_PINS[selected['line']]['run_prepared_restart']
    require(manifest['files'].get(probe_name) == probe_pin
            and manifest['files'].get(runner_name) == runner_pin
            and manifest['files'].get(selected['helper_root'] + '/historical_input_contract.py') == HISTORICAL_HELPER_SHA256,
            'actual selected probe/runner/helper source differs')
    inputs.raw(member(workspace, probe_name), probe_pin)
    inputs.raw(member(workspace, runner_name), runner_pin)
    inputs.raw(member(workspace, selected['helper_root'] + '/historical_input_contract.py'), HISTORICAL_HELPER_SHA256)
    executable = Path(workspace)/'.r44-env/Scripts/python.exe'
    require(Path(sys.executable).resolve() == executable.resolve(), 'selected Atlas constructor interpreter required')
    command = [str(executable), '-B', str(member(workspace, probe_name)), '--workspace', str(workspace),
               '--manifest', selected['manifest_path'], '--manifest-sha256', manifest_binding['sha256'],
               '--native-root', selected['native_root'], '--import-root', selected['helper_root'], '--backend', 'scipy',
               '--historical-inputs', HISTORICAL_INPUTS['path'],
               '--historical-inputs-sha256', HISTORICAL_INPUTS['sha256']]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('PYTHON')}
    env.update(PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    completed = subprocess.run(command, cwd=member(workspace, selected['native_root']), env=env,
                               capture_output=True, text=True, timeout=120, check=False)
    require(completed.returncode == 0, 'actual selected identity probe refused: ' + completed.stderr[-4000:])
    measurement = json.loads(completed.stdout)
    side = current_policy_side(measurement=measurement, source_hashes=source_hashes,
                               manifest_binding=manifest_binding, workspace=workspace, layout=selected)
    inputs.recheck()
    return measurement, side, {'command': command, 'exit_code': completed.returncode,
                               'stdout': completed.stdout, 'stderr': completed.stderr,
                               'worker_dispatched': False, 'scientific_acceptance': False}


def final_profile_documents(inputs, component, *, workspace, layout, manifest_binding,
                            policy_binding, policy_raw, store_limits, compression):
    """Build both real closed profiles from the selected line's emitted source/policy."""
    selected = checked_layout(layout)
    require(layout['workspace'] == str(Path(workspace)) and layout['evidence_root'] == '.',
            'explicit selected profile layout differs')
    require(manifest_binding['path'] == selected['manifest_path']
            and policy_binding['path'] == selected['policy_path'], 'exact selected manifest/policy locations required')
    manifest = inputs.doc(member(workspace, selected['manifest_path']), pin(manifest_binding['sha256']))
    validate_historical_inputs(inputs, workspace=workspace, manifest=manifest,
                               historical_inputs=selected['historical_inputs'])
    require(inputs.raw(member(workspace, selected['policy_path']), pin(policy_binding['sha256'])) == policy_raw,
            'actual emitted policy bytes differ')
    for mapping in (layout['fresh_modules'], layout['prepared_modules']):
        for name, path in mapping.items():
            require(path in manifest['files'], 'consumer source outside selected manifest: ' + name)
            inputs.raw(member(workspace, path), pin(manifest['files'][path]))
    for driver in layout['drivers'].values():
        require(manifest['files'].get(driver['path']) == driver['sha256'], 'actual driver manifest binding differs')
    preparation = layout['preparation']
    require(manifest['files'].get(preparation['path']) == PREPARATION_PIN == preparation['sha256'],
            'actual nested preparation manifest binding differs')
    inputs.raw(member(workspace, preparation['path']), PREPARATION_PIN)
    fresh = {'schema': 'atlas.fresh-interval-profile.v2', 'workspace': str(Path(workspace)),
             'source_manifest': dict(manifest_binding), 'native_root': selected['native_root'],
             'import_roots': list(selected['import_roots']), 'modules': dict(layout['fresh_modules']),
             'advance_driver': dict(layout['drivers']['fresh_interval_driver']),
             'output_directory': layout['fresh_output'], 'store_directory': layout['fresh_store'],
             'completed_query_directory': layout['fresh_queries'],
             'completed_query_limits': dict(layout['query_limits']), 'historical_inputs': dict(HISTORICAL_INPUTS)}
    bindings = dict(workspace=str(Path(workspace)), source_manifest=dict(manifest_binding),
                    native_root=selected['native_root'], import_roots=list(selected['import_roots']),
                    modules=dict(layout['prepared_modules']), preparation=dict(preparation),
                    compatibility_policy=dict(policy_binding), evidence_root='.',
                    historical_root=HISTORICAL_ROOT, historical_source_root=HISTORICAL_NATIVE,
                    historical_inputs=dict(HISTORICAL_INPUTS),
                    advance_driver=dict(layout['drivers']['prepared_interval_driver']),
                    output_directory=layout['prepared_output'], store_limits=dict(store_limits),
                    compression=dict(compression), completed_query_directory=layout['prepared_queries'],
                    completed_query_limits=dict(layout['query_limits']))
    prepared = build_prepared_profile(component, bindings=bindings, policy_raw=policy_raw)
    require(set(fresh) == FRESH_PROFILE_FIELDS and set(prepared) == PREPARED_PROFILE_FIELDS
            and prepared.get('schema') == 'atlas.prepared-restart-launch.v3'
            and prepared.get('historical_inputs') == fresh['historical_inputs']
            and set(fresh['modules']) & set(prepared['modules'])
            and all(fresh['modules'][name] == prepared['modules'][name]
                    for name in fresh['modules'].keys() & prepared['modules'].keys()),
            'actual closed paired profile bindings differ')
    inputs.recheck()
    return fresh, prepared
