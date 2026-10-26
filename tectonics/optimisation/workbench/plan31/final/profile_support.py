"""Plan31 final producer support, with explicit selected inputs and no CLI/run authority.

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
PLAN02_SHA256 = '509936760484459ce1f41aca15965d33dab5e2be26a2eae18df63bf5c7d44f60'
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
    """Return the single explicit mapped public dependency; never discover a fallback."""
    root = Path(repo_root)
    require(root.is_absolute(), 'explicit absolute selected repository required')
    return {'path': str(root/PLAN02_RELATIVE), 'sha256': PLAN02_SHA256}


def authenticate_plan02(inputs, *, binding):
    """Load the complete accepted component from the explicitly supplied source binding."""
    require(type(binding) is dict and set(binding) == {'path', 'sha256'}
            and binding['sha256'] == PLAN02_SHA256 and Path(binding['path']).is_absolute(),
            'explicit accepted Plan02 source binding required')
    path = Path(binding['path'])
    raw = inputs.raw(path, PLAN02_SHA256)
    name = '_plan31_accepted_plan02_50993676'
    require(name not in sys.modules, 'accepted component module name already occupied')
    spec = importlib.util.spec_from_file_location(name, path)
    component = importlib.util.module_from_spec(spec)
    sys.modules[name] = component
    try:
        exec(compile(raw, str(path), 'exec'), component.__dict__)
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
    actual = {name: declared[name] for name in paths if name.endswith('.py')}
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
    require(type(prepared_record) is dict and prepared_record.get('schema') == 'atlas.prepared-restart-launch.v2',
            'actual emitted prepared-v2 record required')
    config = {'schema': 'atlas.prepared-restart-construction.v2',
              'construction_receipt': construction_receipt, 'derivation': derivation,
              'composition': composition, 'constructor_profile': fresh_profile,
              'prepared_profile': prepared_profile, 'fresh_runner': fresh_runner,
              'prepared_runner': prepared_runner, 'compatibility_policy': compatibility_policy,
              'profile': {key: value for key, value in prepared_record.items() if key != 'schema'}}
    require(component.selected_restart_profile(config) == prepared_record,
            'actual prepared consumer returned a different profile')
    return config


# Final namespace and explicit consumer choices. Generated hashes stay downstream.
import ast
import os
import subprocess

FINAL_NATIVE = 'ac/n12f-r1/src'
FINAL_HELPERS = 'ac/n12f-r1/helpers'
FINAL_RUNTIME = 'ac/n12f-run-r1'
FINAL_MANIFEST = FINAL_RUNTIME + '/manifest.json'
FINAL_POLICY = FINAL_RUNTIME + '/runtime-policy.json'
FINAL_PROFILE_PATHS = {'fresh': FINAL_RUNTIME + '/fresh-profile.json',
                       'prepared': FINAL_RUNTIME + '/prepared-profile.json'}
FINAL_EVIDENCE_ROOT = '.'
HISTORICAL_ROOT = 'fidelity-integration-20261005/heat-repair-20261007'
HISTORICAL_NATIVE = HISTORICAL_ROOT + '/native-composed-r7/tectonics/src'
HISTORICAL_MANIFEST = HISTORICAL_ROOT + '/continuation-preparation-r3.json'
HISTORICAL_MANIFEST_PIN = 'f81fd25ca3b68d031b006a0e6eab4d6b278affa86e5d062baeafd748f17ee42c'
HISTORICAL_RECEIPT = HISTORICAL_ROOT + '/heat-original-connected-20261013-r9.json'
HISTORICAL_RECEIPT_PIN = 'ca35700a8106d46eb67c876cd15fb5bf86d6abee7480cc94a23acbef68bb4f0d'
HISTORICAL_NATIVE_DIGEST = '746eea53c8dc9c9c89c8f7db8474e579fd5d2a2b919615b287358ddd4cb29d28'
HISTORICAL_EXECUTION = '6aa7a30cbe577a80d0a4f93d23b22a09525bb509e1e3f8f0f57e6fe09bc9ccad'
RUNNER_PINS = {'run_fresh_interval': '8efc3a8cb76195cff5d4c637291b1d1eeb5b89122ea36b0bb9bca2c092d67466',
               'run_prepared_restart': '051008ad29fc56d42393c33b7dfcde622a39b5e9cce03a4900b91934ee066ce9'}
PROBE_PIN = '5470acc64e3ded77784ef2b18662f885f95a36e1dad24d7bd9902af898a097bd'
FIXTURE_NAMES = {'i04_differential_fixture', 'i04_differential_modes', 'test_i04_differential_force'}
DRIVER_PINS = {'fresh_interval_driver': 'a32a1ea4e224d2ad5de116624abdae98019a2dd447ec419b6647b7f7326af14e',
               'prepared_interval_driver': '21b5874cbab82138285582f895aeab27f7cb77db851f9050b0498dc5a5bdbf80'}
PREPARATION_PIN = 'a5bdfa249d594a65757ab3b48b93690c648dc2b6125e39752ec4ac090a29b55f'


def literal_modules(raw, *, consumer, constant, count):
    """Read exactly the authenticated selected consumer's complete module tuple."""
    require(sha(raw) == RUNNER_PINS[consumer], 'selected final runner changed: ' + consumer)
    tree = ast.parse(raw)
    nodes = [n for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == constant for t in n.targets)]
    require(len(nodes) == 1 and len(nodes[0].targets) == 1, 'unique closed module constant required')
    names = ast.literal_eval(nodes[0].value)
    require(type(names) is tuple and len(names) == count and len(set(names)) == count
            and all(type(n) is str and n.isidentifier() for n in names),
            'selected complete consumer module tuple differs')
    return names


def profile_layout(inputs, *, workspace, payload, parent_fresh_binding):
    """Derive exact source bindings without emitting or qualifying a final profile.

    `payload` is the final constructor's already reconciled complete byte map.
    Each selected runner is authenticated before interpreting its module constant.
    """
    parent = inputs.doc(Path(parent_fresh_binding['path']), pin(parent_fresh_binding['sha256']))
    fresh_names = literal_modules(payload['helpers/run_fresh_interval.py'],
        consumer='run_fresh_interval', constant='FRESH_MODULES', count=21)
    prepared_names = literal_modules(payload['helpers/run_prepared_restart.py'],
        consumer='run_prepared_restart', constant='REQUIRED_MODULES', count=41)
    require(parent['schema'] == 'atlas.fresh-interval-profile.v1'
            and set(parent['modules']) == set(fresh_names), 'actual parent fresh consumer map differs')
    def path_for(name):
        area = 'src/atlas_tectonics/_fixtures/tests' if name in FIXTURE_NAMES else 'helpers'
        key = area + '/' + name + '.py'
        require(key in payload and type(payload[key]) is bytes, 'selected consumer source missing: ' + name)
        return 'ac/n12f-r1/' + key
    fresh = {name: path_for(name) for name in fresh_names}
    prepared = {name: path_for(name) for name in prepared_names}
    require(set(fresh.values()) & set(prepared.values()) == {fresh[n] for n in fresh.keys() & prepared.keys()},
            'shared consumer names alias different paths')
    drivers = {}
    for name, expected in DRIVER_PINS.items():
        key = 'helpers/' + name + '.py'
        require(sha(payload[key]) == expected, 'actual selected driver differs: ' + name)
        drivers[name] = {'module': name, 'path': path_for(name), 'sha256': expected}
    preparation = {'path': path_for('i04_differential_fixture'), 'sha256': PREPARATION_PIN}
    require(sha(payload['src/atlas_tectonics/_fixtures/tests/i04_differential_fixture.py']) == PREPARATION_PIN,
            'selected preparation source differs')
    query_limits = parent['completed_query_limits']
    require(query_limits == {'max_entries': 2000000, 'max_store_bytes': 8589934592},
            'explicit selected files-query quota differs')
    inputs.recheck()
    return {'workspace': str(Path(workspace)), 'native_root': FINAL_NATIVE,
            'import_roots': [FINAL_HELPERS], 'fresh_modules': fresh, 'prepared_modules': prepared,
            'drivers': drivers, 'preparation': preparation,
            'fresh_output': str(Path(workspace)/FINAL_RUNTIME/'attempt-r1'),
            'fresh_store': str(Path(workspace)/FINAL_RUNTIME/'store-r1'),
            'fresh_queries': FINAL_RUNTIME + '/queries-r1',
            'prepared_output': str(Path(workspace)/FINAL_RUNTIME/'prepared-attempt-r1'),
            'prepared_queries': FINAL_RUNTIME + '/prepared-queries-r1',
            'query_limits': dict(query_limits), 'evidence_root': FINAL_EVIDENCE_ROOT}


def historical_policy_inputs(inputs, *, workspace):
    """Reconcile actual original producer identity, all 230 sources and native settings."""
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
    return side, dict(endpoint['store_limits']), dict(endpoint['store_compression'])


def current_policy_side(*, measurement, source_hashes, manifest_binding, workspace):
    """Validate an actual constructor-launched strict probe, never a self-asserted control pin."""
    require(type(manifest_binding) is dict and set(manifest_binding) == {'path', 'sha256'}
            and manifest_binding['path'] == FINAL_MANIFEST, 'exact emitted final manifest required')
    digest = sha(canonical(source_hashes))
    require(measurement.get('schema') == 'atlas.execution-identity-probe.v1'
            and measurement.get('status') == 'MEASURED_NOT_REVIEWED'
            and measurement.get('fresh_process') is True and measurement.get('policy_written') is False
            and measurement.get('source_manifest_sha256') == pin(manifest_binding['sha256'])
            and measurement.get('native_source_digest') == digest
            and measurement.get('native_root') == FINAL_NATIVE
            and measurement.get('import_roots') == [FINAL_HELPERS]
            and measurement.get('backend') == 'scipy'
            and measurement.get('launch_environment') == {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
                'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONHASHSEED': '0'}
            and type(measurement.get('loaded_workspace_sources')) is int
            and measurement['loaded_workspace_sources'] > 0, 'actual strict final measurement differs')
    interpreter = measurement['interpreter']
    require(Path(interpreter['executable']).resolve() == (Path(workspace)/'.r44-env/Scripts/python.exe').resolve()
            and interpreter['hash_randomization'] == 0, 'selected isolated probe interpreter differs')
    provenance = measurement.get('execution_provenance')
    require(type(provenance) is dict and set(provenance) == {'execution_identity', 'execution_mode'}
            and provenance['execution_mode'] == 'strict', 'strict execution provenance required')
    return {'source_hashes': dict(source_hashes), 'native_source_digest': digest,
            'source_manifest_path': FINAL_MANIFEST, 'source_manifest_sha256': manifest_binding['sha256'],
            'execution_identity': pin(provenance['execution_identity'])}


def capture_final_identity(inputs, *, workspace, manifest_binding, source_hashes):
    """Launch the actual pinned final probe after source emission; no worker/store is dispatched."""
    require(sys.dont_write_bytecode, 'constructor must run with -B')
    manifest = inputs.doc(member(workspace, FINAL_MANIFEST), pin(manifest_binding['sha256']))
    require(manifest_binding['path'] == FINAL_MANIFEST and manifest['source_hashes'] == source_hashes,
            'actual emitted final manifest/source map differs')
    probe_name = FINAL_HELPERS + '/probe_execution_identity.py'
    runner_name = FINAL_HELPERS + '/run_prepared_restart.py'
    require(manifest['files'].get(probe_name) == PROBE_PIN
            and manifest['files'].get(runner_name) == RUNNER_PINS['run_prepared_restart'],
            'actual final probe/runner source differs')
    inputs.raw(member(workspace, probe_name), PROBE_PIN)
    inputs.raw(member(workspace, runner_name), RUNNER_PINS['run_prepared_restart'])
    executable = Path(workspace)/'.r44-env/Scripts/python.exe'
    require(Path(sys.executable).resolve() == executable.resolve(), 'selected Atlas constructor interpreter required')
    command = [str(executable), '-B', str(member(workspace, probe_name)), '--workspace', str(workspace),
               '--manifest', FINAL_MANIFEST, '--manifest-sha256', manifest_binding['sha256'],
               '--native-root', FINAL_NATIVE, '--import-root', FINAL_HELPERS, '--backend', 'scipy']
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('PYTHON')}
    env.update(PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    completed = subprocess.run(command, cwd=member(workspace, FINAL_NATIVE), env=env,
                               capture_output=True, text=True, timeout=120, check=False)
    require(completed.returncode == 0, 'actual final identity probe refused: ' + completed.stderr[-4000:])
    measurement = json.loads(completed.stdout)
    side = current_policy_side(measurement=measurement, source_hashes=source_hashes,
                               manifest_binding=manifest_binding, workspace=workspace)
    inputs.recheck()
    return measurement, side, {'command': command, 'exit_code': completed.returncode,
                               'stdout': completed.stdout, 'stderr': completed.stderr,
                               'worker_dispatched': False, 'scientific_acceptance': False}


def final_profile_documents(inputs, component, *, workspace, layout, manifest_binding,
                            policy_binding, policy_raw, store_limits, compression):
    """Connect emitted final sources to the accepted real fresh/prepared profile producers."""
    require(layout['workspace'] == str(Path(workspace)) and layout['native_root'] == FINAL_NATIVE
            and layout['import_roots'] == [FINAL_HELPERS] and layout['evidence_root'] == '.',
            'explicit selected final layout differs')
    require(manifest_binding['path'] == FINAL_MANIFEST and policy_binding['path'] == FINAL_POLICY,
            'exact final manifest/policy locations required')
    manifest = inputs.doc(member(workspace, FINAL_MANIFEST), pin(manifest_binding['sha256']))
    require(inputs.raw(member(workspace, FINAL_POLICY), pin(policy_binding['sha256'])) == policy_raw,
            'actual emitted policy bytes differ')
    for mapping in (layout['fresh_modules'], layout['prepared_modules']):
        for name, path in mapping.items():
            require(path in manifest['files'], 'consumer source outside final manifest: ' + name)
            inputs.raw(member(workspace, path), pin(manifest['files'][path]))
    for driver in layout['drivers'].values():
        require(manifest['files'].get(driver['path']) == driver['sha256'], 'actual driver manifest binding differs')
    fresh = {'schema': 'atlas.fresh-interval-profile.v1', 'workspace': str(Path(workspace)),
             'source_manifest': dict(manifest_binding), 'native_root': FINAL_NATIVE,
             'import_roots': [FINAL_HELPERS], 'modules': dict(layout['fresh_modules']),
             'advance_driver': dict(layout['drivers']['fresh_interval_driver']),
             'output_directory': layout['fresh_output'], 'store_directory': layout['fresh_store'],
             'completed_query_directory': layout['fresh_queries'],
             'completed_query_limits': dict(layout['query_limits'])}
    bindings = dict(workspace=str(Path(workspace)), source_manifest=dict(manifest_binding),
                    native_root=FINAL_NATIVE, import_roots=[FINAL_HELPERS],
                    modules=dict(layout['prepared_modules']), preparation=dict(layout['preparation']),
                    compatibility_policy=dict(policy_binding), evidence_root='.',
                    historical_root=HISTORICAL_ROOT, historical_source_root=HISTORICAL_NATIVE,
                    advance_driver=dict(layout['drivers']['prepared_interval_driver']),
                    output_directory=layout['prepared_output'], store_limits=dict(store_limits),
                    compression=dict(compression), completed_query_directory=layout['prepared_queries'],
                    completed_query_limits=dict(layout['query_limits']))
    prepared = build_prepared_profile(component, bindings=bindings, policy_raw=policy_raw)
    require(len(fresh) == 11 and len(prepared) == 17 and set(fresh['modules']) & set(prepared['modules'])
            and all(fresh['modules'][name] == prepared['modules'][name]
                    for name in fresh['modules'].keys() & prepared['modules'].keys()),
            'actual closed paired profile bindings differ')
    inputs.recheck()
    return fresh, prepared
