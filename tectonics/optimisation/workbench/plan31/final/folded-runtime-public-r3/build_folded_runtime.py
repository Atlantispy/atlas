"""Derive a separately bound runtime from an authenticated, already completed fold.

Planning reads pinned inputs only. Applying creates absent destinations exclusively,
then calls an explicitly pinned store-free identity capture component. This does
not qualify a runtime, admit state, dispatch a worker or authorise an interval.
"""
from __future__ import annotations

import argparse
import ast
import copy
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import types


SCHEMA = 'atlas.plan31.folded-runtime-context.v2'
DEST_SCHEMA = 'atlas.plan31.folded-runtime-destinations.v1'
REQUEST_SCHEMA = 'atlas.plan31.folded-identity-request.v1'
PLAN_SCHEMA = 'atlas.plan31.folded-runtime-plan.v2'
RESULT_SCHEMA = 'atlas.plan31.folded-runtime-result.v2'
SOURCE_SCHEMA = 'atlas.private.resumable-composition.r3'
ENVIRONMENT = {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
               'MKL_NUM_THREADS': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONHASHSEED': '0'}
MAX_JSON = 8 << 20
SOURCE_FIELDS = {'construction_receipt', 'composition', 'manifest', 'fresh_profile', 'prepared_profile', 'policy'}
COMPONENT_FIELDS = {'utility', 'support', 'prepared_component', 'capture', 'interpreter'}
CONTEXT_FIELDS = {'schema', 'constructor', 'workspace', 'source_root', 'folded_root',
                  'sources', 'fold', 'components', 'destinations', 'review', 'capture_timeout_seconds'}
ACCEPTED_ROLE_PINS = {
    'utility': '171915e6871740755afdd54528b9a9fc2dfd236a0b60ae427175ab70d3f7492e',
    'support': '762bea12f5f127c723aac1c25cf3fa8a0351191539883c258624c0363058bf01',
    'prepared_component': 'c69731f55dcda5dc5984ef0ca15d9f78b8a4f44acb7a1bb652af03cabab72b83',
    'capture': '15051b9ef7d0def850d0f8528b6b9bca268dc24f3cf276195f4139a1eca7ac5f',
}
ACCEPTED_HISTORICAL_HELPER = 'e0c2879dc1290cabb4e9c86e0bed21113851988ad21fc81f51e88e7b84886f86'
ACCEPTED_FOLD_TOOLS = {
    'fold_r6_sha256': '857a2eec72a65f5add0fe799a30bab1813e9d2c7e3287351c5a94252e395cec1',
    'fold_r7_sha256': '31867454e090fe510673c55308e49c9ab95daed6ce895d97de0ec523511b3d5b',
    'facade_binding_sha256': 'c62fc8b76f7ffa2beef2f61fed58b4ee09a7e3a3e717e8b1bb65e8978319295d',
    'parity_sha256': 'a6256d32b9118acaa1643acc41e32cce23da0ffb07bf8f2445733d9e73c9974a',
    'parity_fixture_sha256': '48e982c97f54ccc43ed283ffd55cd0c1f1d58c57163fe4692c36ae6610592eaa',
}
REQUIRED_FOLD_GATES = {'ast', 'placement', 'historical_root', 'pins', 'scan', 'k3', 'placement_after_probes'}
RESERVED_EVIDENCE_FILES = ('capture-request.json', 'capture-result.json', 'capture-process.json',
                           'construction-result.json', 'failure.json')


class Refused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Refused(message)


def digest(raw):
    return sha256(raw).hexdigest()


def pin(value):
    require(type(value) is str and len(value) == 64 and
            all(c in '0123456789abcdef' for c in value), 'explicit lowercase SHA256 required')
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def unique(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, 'duplicate JSON key: ' + name)
        result[name] = value
    return result


def document(raw):
    require(len(raw) <= MAX_JSON, 'JSON source exceeds bounded size')
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: require(False, 'nonfinite JSON: ' + value))


def closed(value, fields, label):
    require(type(value) is dict and set(value) == set(fields), 'closed ' + label + ' required')
    return value


def ordinary(path, *, directory=False):
    """The accepted utility's ordinary-path rule, also used before loading it."""
    path = Path(path)
    require(path.is_absolute() and path == path.resolve(), 'canonical absolute path required: ' + str(path))
    for item in (path, *path.parents):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and
                not getattr(info, 'st_file_attributes', 0) & 0x400, 'linked/reparse path refused')
    require(path.is_dir() if directory else path.is_file(), 'ordinary path required: ' + str(path))
    return path


def relative(name):
    require(type(name) is str and name and ':' not in name and '\\' not in name,
            'canonical relative member required')
    parts = PurePosixPath(name).parts
    require('/'.join(parts) == name and not PurePosixPath(name).is_absolute() and
            all(p not in ('.', '..') and p.rstrip(' .') == p for p in parts) and
            all(p.casefold() != 'bridge' for p in parts), 'escaped/excluded relative member')
    return name


def reference(value):
    closed(value, {'path', 'sha256'}, 'source reference')
    pin(value['sha256'])
    require(type(value['path']) is str, 'source reference path must be text')
    return value


def absolute_ref(value):
    reference(value)
    require(Path(value['path']).is_absolute(), 'absolute source reference required')
    return value


def read_initial(value):
    absolute_ref(value)
    path = ordinary(value['path'])
    before = path.stat()
    raw = path.read_bytes()
    after = ordinary(path).stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'input changed during initial read')
    require(digest(raw) == value['sha256'], 'initial source differs from pin: ' + str(path))
    return raw


def load_component(inputs, binding, name):
    absolute_ref(binding)
    raw = inputs.raw(Path(binding['path']), binding['sha256'])
    module = types.ModuleType(name)
    module.__file__ = binding['path']
    require(name not in sys.modules, 'component name already occupied')
    sys.modules[name] = module
    try:
        exec(compile(raw, binding['path'], 'exec', dont_inherit=True), module.__dict__)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def inside(workspace, name):
    return workspace / relative(name)


def under(path, root):
    return path == root or path.is_relative_to(root)


def no_overlap(paths):
    values = [Path(p).resolve() for p in paths]
    require(len({str(p).casefold() for p in values}) == len(values), 'duplicate destination/input roots')
    require(not any(under(a, b) or under(b, a) for i, a in enumerate(values)
                    for b in values[i + 1:]), 'destination/source roots overlap')


def absent(path):
    require(not os.path.lexists(path), 'destination exists; preserve it: ' + str(path))
    ordinary(Path(path).parent, directory=True)


def refuse_rehearsal(value):
    """Preserve the selected constructor's recursive, presence-based refusal."""
    if type(value) is dict:
        require('purpose' not in value, 'purpose key refused, including falsey values')
        for key, item in value.items():
            require(not key.casefold().startswith('plan31:rehearsal-'), 'rehearsal key refused')
            refuse_rehearsal(item)
    elif type(value) is list:
        for item in value:
            refuse_rehearsal(item)
    elif type(value) is str:
        require(not value.casefold().startswith('plan31:rehearsal-'), 'rehearsal value refused')


def validate_component_bindings(components):
    """A mutable context cannot select new executable compiler/capture roles."""
    for role, expected in ACCEPTED_ROLE_PINS.items():
        absolute_ref(components[role])
        require(components[role]['sha256'] == expected, 'independent accepted component pin differs: ' + role)


def reviewed_constructor_binding(context, reviewed_sha256):
    require(type(reviewed_sha256) is str, 'independent reviewed-constructor SHA256 required for apply')
    reviewed_sha256 = pin(reviewed_sha256)
    own = ordinary(Path(__file__).resolve())
    actual = digest(own.read_bytes())
    require(actual == reviewed_sha256, 'constructor differs from independent reviewed SHA256')
    require(Path(context['constructor']['path']).resolve() == own and
            context['constructor']['sha256'] == reviewed_sha256,
            'context constructor differs from independent reviewed binding')
    return reviewed_sha256


def check_output_paths(workspace, destination, profiles, evidence_names, input_paths):
    """Before writes: UTF16 MAX_PATH +8 and CI file/directory ownership."""
    roots = [inside(workspace, destination[key]).resolve() for key in ('runtime_root', 'evidence_root')]
    runtime, evidence = roots
    files = [runtime/name for name in ('manifest.json', 'fresh-profile.json',
                                       'runtime-policy.json', 'prepared-profile.json')]
    files += [evidence/relative(name) for name in (*evidence_names, *RESERVED_EVIDENCE_FILES)]
    directories = list(roots)
    for profile in profiles.values():
        for field in ('output_directory', 'store_directory', 'completed_query_directory'):
            if field in profile:
                path = Path(profile[field])
                directories.append((path if path.is_absolute() else inside(workspace, profile[field])).resolve())
    # Ancestors are directory identities too; a file may never occupy one.
    parent_directories = set()
    for path in [*files, *directories]:
        require(path.is_absolute() and path == path.resolve() and any(under(path, root) for root in roots),
                'planned output escaped its selected roots')
        require(len(str(path).encode('utf-16-le')) // 2 + 8 < 260,
                'UTF16 MAX_PATH allowance exceeded: ' + str(path))
        for parent in path.parents:
            if any(under(parent, root) for root in roots):
                parent_directories.add(parent)
        require(not os.path.lexists(path), 'planned output already exists: ' + str(path))
    file_keys = [str(path).casefold() for path in files]
    directory_keys = [str(path).casefold() for path in directories]
    require(len(set(file_keys)) == len(file_keys), 'case-insensitive output file collision')
    require(len(set(directory_keys)) == len(directory_keys), 'case-insensitive output directory collision')
    all_directory_keys = set(directory_keys) | {str(path).casefold() for path in parent_directories}
    require(not set(file_keys) & all_directory_keys, 'case-insensitive output file/directory collision')
    for name in input_paths:
        path = Path(name).resolve()
        require(not any(under(path, root) or under(root, path) for root in roots), 'planned output/input overlap')
    return {'files': [str(path) for path in files],
            'directories': [str(path) for path in sorted(set(directories) | parent_directories)]}


def source_receipt(inputs, context, records):
    receipt = records['construction_receipt']
    refuse_rehearsal(receipt)
    refuse_rehearsal(records['composition'])
    require(type(receipt) is dict and receipt.get('schema') == 'atlas.private.plan31.final-generation.r1' and
            receipt.get('status') == 'PREPARED_SOURCE_NOT_QUALIFIED' and receipt.get('pending') == [] and
            receipt.get('input_finality') is True and receipt.get('output_finality') is True and
            receipt.get('source_only') is True,
            'completed authentic source construction receipt/finality required')
    require(all(receipt.get(field) is False for field in ('execution_authority', 'interval_authority',
            'holds_released', 'scientific_acceptance', 'default_changed', 'numerical_changes')),
            'source-only receipt authority/change flags differ')
    generation = PurePosixPath(context['source_root']).name
    require(receipt.get('generation') == generation and
            receipt.get('stage') == 'plan31:final-generation-' + generation,
            'source receipt generation/stage differs')
    require(receipt.get('composition_sha256') == context['sources']['composition']['sha256'] and
            receipt.get('manifest_sha256') == context['sources']['manifest']['sha256'] and
            receipt.get('profile_sha256') == context['sources']['fresh_profile']['sha256'],
            'source receipt composition/manifest/fresh raw pins differ')
    prepared = absolute_ref(receipt.get('prepared_profile'))
    require(Path(prepared['path']) == Path(context['sources']['prepared_profile']['path']) and
            prepared['sha256'] == context['sources']['prepared_profile']['sha256'],
            'source receipt prepared profile differs')
    bindings = receipt.get('source_inputs')
    require(type(bindings) is dict and bindings and len({name.casefold() for name in bindings}) == len(bindings),
            'complete original construction source bindings required')
    for name, expected in bindings.items():
        path = Path(name)
        require(path.is_absolute() and all(part.casefold() != 'bridge' for part in path.parts),
                'excluded/nonabsolute construction source binding')
        inputs.raw(path, pin(expected))
    return receipt


def source_stage_intake(inputs, context, records):
    """Retain an observed original-source intake; never rerun it on a fold."""
    selected = context['review']['evidence'].get('source-paired-intake.json')
    if selected is None:
        return 'SOURCE_STAGE_DISPOSITION_NOT_REASSERTED', None
    report = inputs.doc(Path(selected['path']), selected['sha256'])
    require(type(report) is dict and type(report.get('final')) is dict,
            'selected source-stage paired-intake evidence differs')
    row = report['final']
    closed(row, {'component', 'config', 'prepared_profile', 'receipt', 'status',
                 'unpublished_receipt_used', 'worker_dispatched'}, 'source-stage intake final row')
    require(row['status'] == 'PASS_ACTUAL_FINAL_RECEIPT_PAIRED_API' and
            row['unpublished_receipt_used'] is False and row['worker_dispatched'] is False,
            'source-stage paired-intake disposition differs')
    workspace = Path(context['workspace'])
    def same_reference(actual, expected):
        reference(actual); absolute_ref(expected)
        path = Path(actual['path'])
        if not path.is_absolute():
            path = inside(workspace, actual['path'])
        return path.resolve() == Path(expected['path']).resolve() and actual['sha256'] == expected['sha256']
    for field, expected in (('component', context['components']['prepared_component']),
                            ('receipt', context['sources']['construction_receipt']),
                            ('prepared_profile', context['sources']['prepared_profile'])):
        require(same_reference(row[field], expected), 'source-stage intake has a different selected ' + field)
    absolute_ref(row['config'])
    config = inputs.doc(Path(row['config']['path']), row['config']['sha256'])
    require(config.get('schema') == 'atlas.prepared-restart-construction.v3' and
            config.get('profile') == {key: value for key, value in records['prepared_profile'].items() if key != 'schema'},
            'source-stage intake configuration/profile differs')
    for field, source in (('construction_receipt', 'construction_receipt'), ('composition', 'composition'),
                          ('constructor_profile', 'fresh_profile'), ('prepared_profile', 'prepared_profile'),
                          ('compatibility_policy', 'policy')):
        require(same_reference(config[field], context['sources'][source]),
                'source-stage intake configuration has a different ' + field)
    return 'SATISFIED_BY_ACTUAL_SOURCE_CONFIGURATION', dict(selected)


def runner_names(raw, constant, count):
    tree = ast.parse(raw)
    nodes = [node for node in tree.body if isinstance(node, ast.Assign) and
             any(isinstance(target, ast.Name) and target.id == constant for target in node.targets)]
    require(len(nodes) == 1 and len(nodes[0].targets) == 1, 'unique runner module tuple required')
    names = ast.literal_eval(nodes[0].value)
    require(type(names) is tuple and len(names) == count and len(set(names)) == count and
            all(type(name) is str and name.isidentifier() for name in names), 'closed runner module tuple differs')
    return names


def source_maps(inputs, utility, context):
    ws = Path(context['workspace'])
    records = {key: inputs.doc(Path(ref['path']), ref['sha256'])
               for key, ref in context['sources'].items()}
    source_receipt(inputs, context, records)
    comp, manifest = records['composition'], records['manifest']
    root = inside(ws, context['source_root'])
    require(comp.get('schema') == SOURCE_SCHEMA and Path(comp.get('root', '')).resolve() == root.resolve()
            and comp.get('frozen') is False and comp.get('completed_query_store') == 'files',
            'actual source composition frame differs')
    require(Path(context['sources']['composition']['path']) == root/'composition.json',
            'selected composition is outside its actual source root')
    require(manifest.get('completed_query_store') == 'files' and
            type(manifest.get('files')) is dict and manifest['files'] and
            type(manifest.get('data_only')) is dict and
            not manifest['files'].keys() & manifest['data_only'].keys(), 'source manifest partitions differ')
    names = [*manifest['files'], *manifest['data_only']]
    require(len({name.casefold() for name in names}) == len(names), 'source closure has case aliases')
    composition_ref = manifest.get('composition')
    require(type(composition_ref) is dict and composition_ref.get('root') == context['source_root'] and
            composition_ref.get('composition_json') == context['source_root'] + '/composition.json' and
            composition_ref.get('composition_sha256') == context['sources']['composition']['sha256'] and
            composition_ref.get('frozen') is False, 'source manifest composition provenance differs')
    for key in ('outputs', 'helpers'):
        require(type(comp.get(key)) is dict and comp[key], 'complete source composition inventory required')
        part = root/('src' if key == 'outputs' else 'helpers')
        utility.inventory(part, inputs, comp[key])
        inputs.inventories.append((part, set(comp[key])))
        for name, expected in comp[key].items():
            relative(name)
            path = (part/name).relative_to(ws).as_posix()
            mapping = manifest['files'] if name.endswith('.py') else manifest['data_only']
            require(mapping.get(path) == expected, 'composition/source manifest binding differs: ' + name)
    native = {name: value for name, value in comp['outputs'].items()
              if name.startswith('atlas_tectonics/') and name.endswith('.py')}
    require(native == manifest.get('source_hashes'), 'complete pre-fold native source inventory differs')
    for name, expected in (*manifest['files'].items(), *manifest['data_only'].items()):
        inputs.raw(inside(ws, name), pin(expected))
    fresh, prepared, policy = (records[key] for key in ('fresh_profile', 'prepared_profile', 'policy'))
    expected_manifest = {'path': Path(context['sources']['manifest']['path']).relative_to(ws).as_posix(),
                         'sha256': context['sources']['manifest']['sha256']}
    for profile, schema, count in ((fresh, 'atlas.fresh-interval-profile.v2', 21),
                                   (prepared, 'atlas.prepared-restart-launch.v3', 41)):
        require(profile.get('schema') == schema and Path(profile.get('workspace', '')).resolve() == ws and
                profile.get('source_manifest') == expected_manifest and
                profile.get('native_root') == context['source_root'] + '/src' and
                profile.get('import_roots') == composition_ref.get('import_root_order') and
                type(profile.get('modules')) is dict and len(profile['modules']) == count,
                'authentic source paired profile frame differs')
        for name, path in profile['modules'].items():
            require(name.isidentifier() and path in manifest['files'], 'source profile member is unbound')
        binding = profile['advance_driver']
        require(manifest['files'].get(binding['path']) == binding['sha256'], 'source driver is unbound')
    for kind, constant, count in (('fresh', 'FRESH_MODULES', 21), ('prepared', 'REQUIRED_MODULES', 41)):
        name = context['source_root'] + '/helpers/run_' + ('fresh_interval' if kind == 'fresh' else 'prepared_restart') + '.py'
        require(name in manifest['files'], 'actual source runner is absent')
        names = runner_names(inputs.raw(inside(ws, name), manifest['files'][name]), constant, count)
        require(set(names) == set(records[kind + '_profile']['modules']), 'source profile keys differ from actual runner API')
    require(all(fresh['modules'][key] == prepared['modules'][key]
                for key in fresh['modules'].keys() & prepared['modules'].keys()), 'source paired aliases differ')
    require(prepared['historical_inputs'] == fresh['historical_inputs'], 'source historical catalogue differs')
    require(manifest['files'].get(prepared['preparation']['path']) == prepared['preparation']['sha256'],
            'source preparation is unbound')
    expected_policy = {'path': Path(context['sources']['policy']['path']).relative_to(ws).as_posix(),
                       'sha256': context['sources']['policy']['sha256']}
    require(prepared['compatibility_policy'] == expected_policy and
            policy.get('current', {}).get('source_hashes') == native and
            policy['current'].get('source_manifest_path') == expected_manifest['path'] and
            policy['current'].get('source_manifest_sha256') == expected_manifest['sha256'],
            'source policy/profile/manifest binding differs')
    require(policy['current'].get('native_source_digest') == digest(canonical(native)),
            'source policy current inventory digest differs')
    pin(policy['current'].get('execution_identity'))
    return records


def fold_maps(inputs, utility, context, records):
    """Production coordinates using parity_fixture.fold_maps/new_sha semantics."""
    fold_root = inside(Path(context['workspace']), context['folded_root'])
    require(context['fold']['tool']['sha256'] == ACCEPTED_FOLD_TOOLS['fold_r7_sha256'],
            'independently accepted fold tool pin differs')
    fold = inputs.doc(Path(context['fold']['manifest']['path']), context['fold']['manifest']['sha256'])
    report = inputs.doc(Path(context['fold']['report']['path']), context['fold']['report']['sha256'])
    inputs.raw(Path(context['fold']['proof']['path']), context['fold']['proof']['sha256'])
    inputs.raw(Path(context['fold']['tool']['path']), context['fold']['tool']['sha256'])
    inputs.raw(Path(context['fold']['tool_acceptance']['path']), context['fold']['tool_acceptance']['sha256'])
    require(type(fold.get('modules')) is dict and fold['modules'] and
            type(fold.get('sha_map')) is dict and fold['sha_map'], 'actual fold MANIFEST maps required')
    require(report.get('composition_json_sha256') == context['sources']['composition']['sha256'] and
            report.get('manifest_sha256') == context['fold']['manifest']['sha256'] and
            type(report.get('rehearsal')) is list and report['rehearsal'] == [] and report.get('gated') is True,
            'actual non-rehearsal gated fold report required')
    require(type(report.get('gates')) is dict and set(report['gates']) == REQUIRED_FOLD_GATES,
            'actual fold gate key set differs')
    require(
            all(type(row) is dict and row.get('status') in ('PASS', 'PRIVATE')
                for row in report['gates'].values()), 'actual fold gate status differs')
    require(report.get('tools') == ACCEPTED_FOLD_TOOLS,
            'actual accepted five-role fold tool receipts differ')
    require(Path(context['fold']['manifest']['path']).parent == fold_root.parent and
            Path(context['fold']['report']['path']).parent == fold_root.parent,
            'fold MANIFEST/report are outside their actual output root')
    pins = {}
    for name, pair in fold['sha_map'].items():
        relative(name)
        require(type(pair) is list and len(pair) == 2, 'closed fold sha_map pair required')
        pin(pair[0]); pins[name] = pin(pair[1])
        require(name.startswith('atlas_tectonics/') or name == 'atlas_runtime.py', 'unexpected folded destination')
    utility.inventory(fold_root, inputs, pins)
    inputs.inventories.append((fold_root, set(pins)))
    for kind, constant, count in (('fresh', 'FRESH_MODULES', 21), ('prepared', 'REQUIRED_MODULES', 41)):
        name = 'atlas_tectonics/_private/run_' + ('fresh_interval' if kind == 'fresh' else 'prepared_restart') + '.py'
        require(name in pins, 'actual folded runner is absent')
        names = runner_names(inputs.raw(fold_root/name, pins[name]), constant, count)
        require(set(names) == set(records[kind + '_profile']['modules']), 'fold changed the selected logical runner API')
    paths = {}
    source_manifest = records['manifest']
    for origin, key in fold['modules'].items():
        relative(origin); relative(key)
        require(origin.startswith(('src/', 'helpers/')) and key in pins and key.endswith('.py'),
                'fold module mapping is outside selected source/fold')
        old = context['source_root'] + '/' + origin
        require(old in source_manifest['files'], 'fold module has no authenticated source member')
        paths[old] = context['folded_root'] + '/' + key
    require(len(set(paths.values())) == len(paths), 'fold module mapping is not injective')
    for key in (*fold.get('data_files', {}), *fold.get('fixture_files', {})):
        relative(key)
        source = context['source_root'] + '/src/' + key
        require(key in pins and source in {**source_manifest['files'], **source_manifest['data_only']},
                'fold fixture/DATA lacks a source declaration')
        paths.setdefault(source, context['folded_root'] + '/' + key)
    for old, new in paths.items():
        key = new[len(context['folded_root']) + 1:]
        original = {**source_manifest['files'], **source_manifest['data_only']}[old]
        spellings = set(fold.get('f5_repins', {}).get(key, {}).get('spellings', {}).values())
        require(original == fold['sha_map'][key][0] or original in spellings,
                'fold old pin differs from selected source bytes: ' + old)
    for key, expected in {**fold.get('data_files', {}), **fold.get('fixture_files', {})}.items():
        require(fold['sha_map'].get(key) == [expected, expected], 'fixture/DATA must remain byte equal')
    additions = {context['folded_root'] + '/' + key: value for key, value in pins.items()
                 if context['folded_root'] + '/' + key not in set(paths.values())}
    return fold, report, pins, paths, additions


def map_manifest(context, records, fold, pins, paths):
    old = records['manifest']
    source_prefix, prefix = context['source_root'] + '/', context['folded_root'] + '/'
    # Unchanged external dependencies retain their actual declarations. Original
    # owned code is carried only through authenticated fold mapping/membership.
    files = {name: value for name, value in old['files'].items() if not name.startswith(source_prefix)}
    data = {name: value for name, value in old['data_only'].items() if not name.startswith(source_prefix)
            or name.endswith('/composition.json')}
    for name, value in pins.items():
        target = files if name.endswith('.py') else data
        key = prefix + name
        require(key not in target, 'folded/external destination collision')
        target[key] = value
    require(not files.keys() & data.keys(), 'derived source/DATA partitions overlap')
    names = [*files, *data]
    require(len({name.casefold() for name in names}) == len(names), 'derived closure has case aliases')
    fixture = old.get('fixture_source_map')
    require(type(fixture) is dict and type(fixture.get('modules')) is dict and fixture['modules'],
            'authentic production fixture declaration required')
    mapped_fixture = copy.deepcopy(fixture)
    for field in ('modules', 'by_path'):
        if field in fixture:
            require(all(path in paths for path in fixture[field].values()), 'unmapped source fixture')
            mapped_fixture[field] = {name: paths[path] for name, path in fixture[field].items()}
    declaration = fold.get('fixture_source_map')
    require(type(declaration) is dict and declaration.get('schema') == mapped_fixture['schema'],
            'fold fixture declaration schema differs')
    # The fixture reader treats an absent by_path as {}, and the fold declares by_path
    # only when it is non-empty, so an exactly empty by_path compares as absent.
    declared = [{field for field, value in item.items() if field != 'by_path' or value != {}}
                for item in (declaration, mapped_fixture)]
    require(declared[0] == declared[1] and
            all(type(declaration[field]) is dict and
                {name: prefix + path for name, path in declaration[field].items()} == mapped_fixture[field]
                for field in ('modules', 'by_path') if field in declared[0]),
            'fold fixture declaration differs from mapped authentic source declaration')
    result = {'files': files, 'data_only': data, 'source_hashes': {
        key: value for key, value in pins.items() if key.startswith('atlas_tectonics/') and key.endswith('.py')},
        'fixture_source_map': mapped_fixture, 'completed_query_store': old['completed_query_store'],
        # Immutable original-source lineage and the actual strict-peak lookup
        # key. Folded native identity remains the complete source_hashes/capture.
        'composition': copy.deepcopy(old['composition'])}
    require(result['source_hashes'] and all(files.get(prefix + key) == value
            for key, value in result['source_hashes'].items()), 'folded native source closure differs')
    omitted = sorted(name for name in (*old['files'], *old['data_only'])
                     if name.startswith(source_prefix) and name not in paths and not name.endswith('/composition.json'))
    return result, omitted


def mapped_binding(binding, context, fold, paths):
    row = copy.deepcopy(binding)
    old = row['path']
    require(old in paths, 'required participating reference was not folded: ' + old)
    row['path'] = paths[old]
    key = row['path'][len(context['folded_root']) + 1:]
    require(binding['sha256'] == fold['sha_map'][key][0] or binding['sha256'] in
            set(fold.get('f5_repins', {}).get(key, {}).get('spellings', {}).values()),
            'participating reference old pin differs')
    row['sha256'] = fold['sha_map'][key][1]
    return row


def output_translation(value, *, workspace, old_runtime, new_runtime):
    path = Path(value)
    if path.is_absolute():
        old = workspace / old_runtime
        require(path.resolve().is_relative_to(old.resolve()), 'source output lies outside source runtime root')
        return str(workspace / new_runtime / path.resolve().relative_to(old.resolve()))
    relative(value)
    require(value.startswith(old_runtime + '/'), 'relative source output lies outside source runtime root')
    return new_runtime + value[len(old_runtime):]


def map_profiles(context, records, fold, paths, destination, manifest_raw):
    ws, runtime = Path(context['workspace']), destination['runtime_root']
    old_runtime = Path(context['sources']['manifest']['path']).parent.relative_to(ws).as_posix()
    manifest_binding = {'path': runtime + '/manifest.json', 'sha256': digest(manifest_raw)}
    profiles = {}
    for kind in ('fresh', 'prepared'):
        row = copy.deepcopy(records[kind + '_profile'])
        row['source_manifest'] = dict(manifest_binding)
        row['native_root'], row['import_roots'] = context['folded_root'], [context['folded_root']]
        require(all(value in paths for value in row['modules'].values()), 'required 21/41 module was not folded')
        row['modules'] = {name: paths[path] for name, path in row['modules'].items()}
        row['advance_driver'] = mapped_binding(row['advance_driver'], context, fold, paths)
        for field in ('output_directory', 'store_directory', 'completed_query_directory'):
            if field in row:
                row[field] = output_translation(row[field], workspace=ws, old_runtime=old_runtime, new_runtime=runtime)
        if kind == 'prepared':
            row['preparation'] = mapped_binding(row['preparation'], context, fold, paths)
            # The final policy reference is deliberately absent until its actual
            # identity/review-bound bytes exist; this row cannot be emitted yet.
            row['compatibility_policy'] = None
        profiles[kind] = row
    return profiles, manifest_binding


def destination_record(inputs, context):
    ref = context['destinations']
    row = inputs.doc(Path(ref['path']), ref['sha256'])
    closed(row, {'schema', 'workspace', 'source_root', 'folded_root', 'source_composition',
                 'fold_manifest', 'runtime_root', 'evidence_root'}, 'destination authority')
    require(row['schema'] == DEST_SCHEMA and row['workspace'] == context['workspace'] and
            row['source_root'] == context['source_root'] and row['folded_root'] == context['folded_root'] and
            row['source_composition'] == context['sources']['composition'] and
            row['fold_manifest'] == context['fold']['manifest'], 'destination authority input frame differs')
    ws = Path(context['workspace'])
    roots = [inside(ws, row[key]) for key in ('runtime_root', 'evidence_root')]
    no_overlap([*roots, inside(ws, context['source_root']), inside(ws, context['folded_root']),
                Path(context['sources']['manifest']['path']).parent])
    for root in roots:
        absent(root)
    for binding in all_refs(context):
        path = Path(binding['path']).resolve()
        require(not any(under(path, root.resolve()) for root in roots), 'input is inside a new output root')
    return row


def all_refs(context):
    return [context['constructor'], context['destinations'], *context['sources'].values(),
            *context['fold'].values(), *context['components'].values(), context['review']['changes'],
            *context['review']['evidence'].values()]


def validate_review(inputs, context, records, manifest):
    review = context['review']
    changes = inputs.doc(Path(review['changes']['path']), review['changes']['sha256'])
    historical = records['policy']['historical']
    before, after = historical['source_hashes'], manifest['source_hashes']
    delta = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
    require(type(changes) is dict and set(changes) == delta,
            'review must cover exactly all historical/folded changed, added and removed sources')
    evidence = review['evidence']
    require(type(evidence) is dict and evidence, 'explicit accepted fold/source review evidence required')
    require(len({name.casefold() for name in evidence}) == len(evidence), 'case-aliased review evidence destinations')
    required = [context['fold']['proof'], context['fold']['report'], context['fold']['manifest'],
                context['fold']['tool'], context['fold']['tool_acceptance'],
                context['sources']['composition'], context['sources']['construction_receipt'],
                context['sources']['policy']]
    require(all(ref in evidence.values() for ref in required), 'review evidence omits authentic fold/source/tool proof')
    for name, ref in evidence.items():
        relative(name)
        require('/' not in name and name.casefold() not in RESERVED_EVIDENCE_FILES,
                'unsafe/reserved review evidence destination')
        inputs.raw(Path(ref['path']), ref['sha256'])
    for name, row in changes.items():
        closed(row, {'before', 'after', 'reason', 'evidence'}, 'native review row')
        require(row['before'] == before.get(name) and row['after'] == after.get(name) and
                type(row['reason']) is str and row['reason'].strip() and
                type(row['evidence']) is list and row['evidence'] and
                all(type(ref) is str and (ref in evidence or ref in records['policy']['evidence'])
                    for ref in row['evidence']),
                'native review delta/evidence differs: ' + name)
    return changes


def prepare(context_path, context_pin):
    binding = {'path': str(ordinary(context_path)), 'sha256': pin(context_pin)}
    context_raw = read_initial(binding)
    context = document(context_raw)
    closed(context, CONTEXT_FIELDS, 'folded runtime context')
    require(context['schema'] == SCHEMA, 'unsupported folded runtime context')
    require(type(context['capture_timeout_seconds']) is int and 1 <= context['capture_timeout_seconds'] <= 3600,
            'explicit bounded capture timeout (1..3600 seconds) required')
    closed(context['sources'], SOURCE_FIELDS, 'source records')
    closed(context['components'], COMPONENT_FIELDS, 'component records')
    validate_component_bindings(context['components'])
    closed(context['fold'], {'manifest', 'report', 'proof', 'tool', 'tool_acceptance'}, 'fold records')
    closed(context['review'], {'changes', 'evidence'}, 'native review selection')
    ws = ordinary(context['workspace'], directory=True)
    require(str(ws) == context['workspace'], 'canonical workspace spelling required')
    relative(context['source_root']); relative(context['folded_root'])
    for ref in all_refs(context):
        absolute_ref(ref)
    require(not Path(context['components']['capture']['path']).resolve().is_relative_to(ws),
            'capture component must stay outside the selected native workspace')
    require(Path(context['constructor']['path']).resolve() == Path(__file__).resolve(),
            'context names a different constructor')
    utility_binding = context['components']['utility']
    utility_raw = read_initial(utility_binding)
    utility = types.ModuleType('_folded_runtime_utility_' + utility_binding['sha256'][:16])
    utility.__file__ = utility_binding['path']
    exec(compile(utility_raw, utility_binding['path'], 'exec', dont_inherit=True), utility.__dict__)
    inputs = utility.Inputs()
    inputs.raw(Path(binding['path']), binding['sha256'])
    for ref in all_refs(context):
        inputs.raw(Path(ref['path']), ref['sha256'])
    support = load_component(inputs, context['components']['support'], '_folded_runtime_support_' + context_pin[:16])
    prepared_component = context['components']['prepared_component']
    require(prepared_component['sha256'] == support.PLAN02_SHA256,
            'actual accepted prepared producer component required')
    inputs.raw(Path(prepared_component['path']).with_name('historical_input_contract.py'),
               ACCEPTED_HISTORICAL_HELPER)
    destination = destination_record(inputs, context)
    records = source_maps(inputs, utility, context)
    source_intake_status, source_intake_ref = source_stage_intake(inputs, context, records)
    closed(records['fresh_profile'], support.FRESH_PROFILE_FIELDS, 'authentic fresh source profile')
    closed(records['prepared_profile'], support.PREPARED_PROFILE_FIELDS, 'authentic prepared source profile')
    fold, report, pins, paths, additions = fold_maps(inputs, utility, context, records)
    manifest, omitted = map_manifest(context, records, fold, pins, paths)
    manifest_raw = canonical(manifest)
    profiles, manifest_binding = map_profiles(context, records, fold, paths, destination, manifest_raw)
    changes = validate_review(inputs, context, records, manifest)
    output_paths = check_output_paths(ws, destination, profiles, context['review']['evidence'], inputs.pins)
    policy = records['policy']
    require(policy.get('schema') == support.POLICY_SCHEMA and policy.get('constraints') == support.POLICY_CONSTRAINTS,
            'source runtime policy contract changed')
    for name, expected in policy['evidence'].items():
        inputs.raw(inside(ws, name), pin(expected))
    for profile in profiles.values():
        for field in ('output_directory', 'store_directory', 'completed_query_directory'):
            if field in profile:
                path = Path(profile[field])
                require(not os.path.lexists(path if path.is_absolute() else inside(ws, profile[field])),
                        'new runtime output already exists')
    plan = {'schema': PLAN_SCHEMA, 'context': binding, 'status': 'PREPARED_NOT_QUALIFIED',
            'runtime_root': destination['runtime_root'], 'evidence_root': destination['evidence_root'],
            'manifest_sha256': digest(manifest_raw), 'fresh_profile_sha256': digest(canonical(profiles['fresh'])),
            'native_source_digest': digest(canonical(manifest['source_hashes'])),
            'folded_members': len(pins), 'native_python_members': len(manifest['source_hashes']),
            'mapped_members': len(paths), 'additions': additions, 'not_carried': omitted,
            'reviewed_source_delta': len(changes), 'structural_inputs_ready': True,
            'apply_authorised': False, 'constructor_implementation_review_required': True,
            'blocking': None, 'scientific_acceptance': False, 'holds_released': False,
            'worker_dispatched': False, 'interval_authority': False}
    plan.update(source_stage_c697_intake=source_intake_status,
                source_stage_c697_intake_evidence=source_intake_ref,
                source_stage_c697_intake_reexecuted=False,
                folded_high_level_c697_intake_required=False)
    inputs.recheck()
    return {'inputs': inputs, 'utility': utility, 'support': support, 'context': context,
            'records': records, 'destination': destination, 'fold': fold, 'paths': paths,
            'manifest': manifest, 'manifest_raw': manifest_raw, 'manifest_binding': manifest_binding,
            'profiles': profiles, 'changes': changes, 'output_paths': output_paths, 'plan': plan}


def write_exclusive(path, raw):
    with Path(path).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    require(Path(path).read_bytes() == raw, 'emitted metadata differs: ' + str(path))
    return digest(raw)


def capture_request(state):
    context, destination = state['context'], state['destination']
    prefix, files = context['folded_root'] + '/', state['manifest']['files']
    request = {'schema': REQUEST_SCHEMA, 'workspace': context['workspace'], 'backend': 'scipy',
               'source_manifest': state['manifest_binding'],
               'fresh_profile': {'path': destination['runtime_root'] + '/fresh-profile.json',
                                 'sha256': digest(canonical(state['profiles']['fresh']))},
               'interpreter': context['components']['interpreter']}
    for field, key in (('bootstrap', 'atlas_tectonics/integration_worker_bootstrap.py'),
                       ('fresh_runner', 'atlas_tectonics/_private/run_fresh_interval.py'),
                       ('prepared_runner', 'atlas_tectonics/_private/run_prepared_restart.py')):
        name = prefix + key
        require(name in files, 'selected folded capture member is absent: ' + name)
        request[field] = {'path': name, 'sha256': files[name]}
    return request


def validate_measurement(state, request, request_pin, measurement):
    profile = state['profiles']['fresh']
    fields = {'schema', 'status', 'backend', 'historical_inputs', 'execution_provenance',
              'source_manifest_sha256', 'native_source_digest', 'native_root', 'import_roots',
              'interpreter', 'launch_environment', 'loaded_workspace_sources', 'fresh_process',
              'policy_written', 'request_sha256', 'source_manifest', 'fresh_profile', 'bootstrap',
              'fresh_runner', 'prepared_runner', 'source_verification_before',
              'source_verification_after', 'execution_context_closed', 'strict_execution', 'worker_dispatched'}
    closed(measurement, fields, 'actual capture result')
    for field in ('source_manifest', 'fresh_profile', 'bootstrap', 'fresh_runner', 'prepared_runner'):
        require(measurement[field] == request[field], 'capture returned a different selected reference: ' + field)
    expected_verification = {'source_manifest_sha256': state['manifest_binding']['sha256'],
                             'native_source_digest': state['plan']['native_source_digest']}
    require(measurement['source_verification_before'] == expected_verification and
            measurement['source_verification_after'] == expected_verification and
            measurement['execution_context_closed'] is True and measurement['strict_execution'] is True,
            'capture source/boundary/close verification differs')
    require(type(measurement) is dict and measurement.get('schema') == 'atlas.execution-identity-probe.v2' and
            measurement.get('request_sha256') == request_pin and measurement.get('status') == 'MEASURED_NOT_REVIEWED' and
            measurement.get('fresh_process') is True and measurement.get('policy_written') is False and
            measurement.get('worker_dispatched') is False and measurement.get('backend') == 'scipy' and
            measurement.get('source_manifest_sha256') == state['manifest_binding']['sha256'] and
            measurement.get('native_source_digest') == state['plan']['native_source_digest'] and
            measurement.get('native_root') == profile['native_root'] and
            measurement.get('import_roots') == profile['import_roots'] and
            measurement.get('historical_inputs') == profile['historical_inputs'] and
            measurement.get('launch_environment') == ENVIRONMENT and
            type(measurement.get('loaded_workspace_sources')) is int and measurement['loaded_workspace_sources'] > 0,
            'actual strict folded identity measurement differs')
    interpreter = measurement.get('interpreter')
    closed(interpreter, {'executable', 'version', 'hash_randomization', 'sha256', 'flags',
                         'xoptions', 'warnoptions', 'prefix', 'base_prefix'}, 'captured interpreter')
    require(type(interpreter) is dict and Path(interpreter.get('executable', '')).resolve() ==
            Path(request['interpreter']['path']).resolve() and interpreter.get('hash_randomization') == 0,
            'captured interpreter differs')
    require(interpreter.get('sha256') == request['interpreter']['sha256'], 'captured interpreter bytes differ')
    require(interpreter['flags'] == {'dont_write_bytecode': 1, 'no_user_site': 1, 'safe_path': True,
            'hash_randomization': 0, 'ignore_environment': 0, 'isolated': 0}, 'captured launch flags differ')
    provenance = measurement.get('execution_provenance')
    closed(provenance, {'execution_identity', 'execution_mode'}, 'strict execution provenance')
    require(provenance['execution_mode'] == 'strict', 'strict execution mode required')
    pin(provenance['execution_identity'])
    return {'source_hashes': dict(state['manifest']['source_hashes']),
            'native_source_digest': state['plan']['native_source_digest'],
            'source_manifest_path': state['manifest_binding']['path'],
            'source_manifest_sha256': state['manifest_binding']['sha256'],
            'execution_identity': provenance['execution_identity']}


def apply(state, *, reviewed_constructor_sha256=None):
    reviewed_constructor_binding(state['context'], reviewed_constructor_sha256)
    require(sys.dont_write_bytecode and sys.flags.no_user_site and sys.flags.safe_path,
            'apply constructor with -B -s -P')
    require(state['plan']['structural_inputs_ready'], state['plan']['blocking'] or 'actual fold proof is missing')
    context, inputs, support = state['context'], state['inputs'], state['support']
    require(Path(sys.executable).resolve() == Path(context['components']['interpreter']['path']).resolve(),
            'apply must use the explicitly pinned capture interpreter')
    ws, dest = Path(context['workspace']), state['destination']
    runtime, evidence_root = (inside(ws, dest[key]) for key in ('runtime_root', 'evidence_root'))
    # Final recheck precedes exclusive construction. Failures preserve every
    # already emitted file; no existing or failed destination is reset/deleted.
    inputs.recheck()
    absent(runtime); absent(evidence_root)
    check_output_paths(ws, dest, state['profiles'], context['review']['evidence'], inputs.pins)
    runtime.mkdir(); evidence_root.mkdir()
    emitted = {}
    def emit(path, raw):
        value = write_exclusive(path, raw)
        emitted[str(path)] = value
        return value
    try:
        for name, ref in context['review']['evidence'].items():
            emit(evidence_root/name, inputs.raw(Path(ref['path']), ref['sha256']))
        for name, raw in (('manifest.json', state['manifest_raw']),
                           ('fresh-profile.json', canonical(state['profiles']['fresh']))):
            emit(runtime/name, raw)
        request = capture_request(state)
        raw = canonical(request)
        request_pin = emit(evidence_root/'capture-request.json', raw)
        capture = context['components']['capture']
        command = [context['components']['interpreter']['path'], '-B', '-s', '-P', capture['path'],
                   '--request', str(evidence_root/'capture-request.json'), '--request-sha256', request_pin]
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith('PYTHON')}
        env.update(ENVIRONMENT)
        inputs.recheck()
        process = subprocess.run(command, cwd=inside(ws, context['folded_root']), env=env,
                                 capture_output=True, text=True, timeout=context['capture_timeout_seconds'], check=False)
        process_record = {'command': command, 'exit_code': process.returncode,
                          'stdout': process.stdout, 'stderr': process.stderr, 'worker_dispatched': False}
        emit(evidence_root/'capture-process.json', canonical(process_record))
        require(process.returncode == 0, 'trusted identity capture refused; preserved process evidence')
        measurement = document(process.stdout.encode('utf-8'))
        current = validate_measurement(state, request, request_pin, measurement)
        emit(evidence_root/'capture-result.json', canonical(measurement))
        old_policy = state['records']['policy']
        evidence = dict(old_policy['evidence'])
        evidence.update({dest['evidence_root'] + '/' + name: ref['sha256']
                         for name, ref in context['review']['evidence'].items()})
        translated_changes = copy.deepcopy(state['changes'])
        for row in translated_changes.values():
            row['evidence'] = [dest['evidence_root'] + '/' + name if name in context['review']['evidence']
                               else name for name in row['evidence']]
        _, policy_raw = support.build_policy(inputs, workspace=ws, evidence_root='.',
            historical=copy.deepcopy(old_policy['historical']), current=current,
            reviewed_changes=translated_changes, evidence=evidence)
        policy_pin = emit(runtime/'runtime-policy.json', policy_raw)
        prepared = copy.deepcopy(state['profiles']['prepared'])
        prepared['compatibility_policy'] = {'path': dest['runtime_root'] + '/runtime-policy.json', 'sha256': policy_pin}
        component = support.authenticate_plan02(inputs, binding=context['components']['prepared_component'])
        actual_prepared = support.build_prepared_profile(component,
            bindings={key: value for key, value in prepared.items() if key != 'schema'}, policy_raw=policy_raw)
        require(actual_prepared == prepared, 'accepted prepared producer changed selected nontranslation fields')
        prepared_pin = emit(runtime/'prepared-profile.json', canonical(actual_prepared))
        inputs.recheck()
        for path, expected in emitted.items():
            require(digest(ordinary(path).read_bytes()) == expected, 'emitted metadata finality differs')
        for root in (runtime, evidence_root):
            actual = set(state['utility'].inventory(root))
            expected = {Path(path).relative_to(root).as_posix() for path in emitted if Path(path).is_relative_to(root)}
            require(actual == expected, 'unexpected/missing construction output member')
        result = {'schema': RESULT_SCHEMA, 'status': 'PREPARED_SOURCE_NOT_QUALIFIED',
                  'context': state['plan']['context'], 'source_manifest': state['manifest_binding'],
                  'reviewed_constructor_sha256': reviewed_constructor_sha256,
                  'fresh_profile': request['fresh_profile'],
                  'prepared_profile': {'path': dest['runtime_root'] + '/prepared-profile.json', 'sha256': prepared_pin},
                  'compatibility_policy': prepared['compatibility_policy'], 'execution_provenance': measurement['execution_provenance'],
                  'source_finality': True, 'output_finality': True, 'prepared_profile_producer_validated': True,
                  'source_stage_c697_intake': state['plan']['source_stage_c697_intake'],
                  'source_stage_c697_intake_evidence': state['plan']['source_stage_c697_intake_evidence'],
                  'source_stage_c697_intake_reexecuted': False,
                  'folded_high_level_c697_intake_required': False, 'qualification_pending': True,
                  'worker_dispatched': False, 'scientific_acceptance': False, 'holds_released': False,
                  'interval_authority': False}
        emit(evidence_root/'construction-result.json', canonical(result))
        return result
    except BaseException as error:
        failure = {'schema': RESULT_SCHEMA, 'status': 'FAILED_PRESERVED',
                   'error': type(error).__name__ + ': ' + str(error), 'worker_dispatched': False,
                   'scientific_acceptance': False, 'holds_released': False}
        if not os.path.lexists(evidence_root/'failure.json'):
            write_exclusive(evidence_root/'failure.json', canonical(failure))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('plan', 'apply'))
    parser.add_argument('--context', required=True, type=Path)
    parser.add_argument('--context-sha256', required=True)
    parser.add_argument('--reviewed-constructor-sha256')
    args = parser.parse_args(argv)
    try:
        state = prepare(args.context, args.context_sha256)
        result = state['plan'] if args.mode == 'plan' else apply(state,
            reviewed_constructor_sha256=args.reviewed_constructor_sha256)
        print(json.dumps(result, sort_keys=True, allow_nan=False), flush=True)
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print('REFUSED: ' + type(error).__name__ + ': ' + str(error), file=sys.stderr, flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
