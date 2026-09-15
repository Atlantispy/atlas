"""Fresh-source, dual-mode, disk/restart proof. No seal before reviewed inventory."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import types
import unittest

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
OUTPUT_ROOT = TASK/'outputs/generator-upgrade-r11'
ENTRY_SOURCE_SHA256 = None
EXPECTED_COUNT = 487
INVENTORY_SHA256 = '206d88b8b4382f7bd8c0ad729ce117a3efe94f75b1b67d1b9fa0ee1efa882fb5'
RELEASE_READY = True
R10_SEAL_SHA256 = '610396bd1e358ac2501059020597482041f73b487655ea062f9a8f478b91e509'
ARTIFACT_NAMES = frozenset(('recipe.json', 'parent-result.json', 'full-result.json', 'stop-result.json',
    'restart-result.json', 'full-checkpoint.json', 'stop-checkpoint.json', 'restart-checkpoint.json',
    'workflow-consequences.json', 'thermal-diagnostic.json'))
WORKFLOW_NAMES = ('workflow-generated', 'workflow-supplied', 'workflow-stop', 'workflow-restart')
WORKFLOW_ENVELOPES = {'metadata.json', 'graph.json', 'checkpoint.json', 'recipe.json'}
PARTITIONED_NAMES = frozenset(('full-result.json', 'stop-result.json', 'restart-result.json',
    'full-checkpoint.json', 'stop-checkpoint.json', 'restart-checkpoint.json', 'workflow-consequences.json'))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def read_pinned_json(storage, path, digest):
    """The audited object is decoded from the SAME bounded bytes that were hashed."""
    path = storage.plain_path(path)
    if not path.is_file() or path.stat().st_size > 8*1024*1024:
        raise ValueError('bounded regular saved artifact required')
    raw = path.read_bytes()
    if len(raw) > 8*1024*1024 or sha(raw) != digest:
        raise ValueError('saved artifact bytes changed')
    return storage.decoded(raw)


def retained_verifier():
    seal = TASK/'outputs/generator-upgrade-r10/seasonal-reference-01/VERIFICATION.json'
    raw = seal.read_bytes()
    if sha(raw) != R10_SEAL_SHA256:
        raise ValueError('retained verification seal changed')
    path = TASK/'work/generator_upgrade_r10/verify.py'
    expected = json.loads(raw)['source_snapshot'][str(path)]; raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError('retained verification source changed')
    module = types.ModuleType('_r11_retained_verifier'); module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    return module, path, expected


def install():
    if ENTRY_SOURCE_SHA256 is None or any(k.startswith('work.') for k in sys.modules):
        raise ValueError('fresh standalone source-compiled verifier required')
    retained, path, digest = retained_verifier()
    helper, utility_path, utility_digest = retained.utility(); capture = helper.ExecutionCapture()
    for p, d in ((HERE/'verify.py', ENTRY_SOURCE_SHA256), (path, digest), (utility_path, utility_digest)):
        capture.compiled[str(p)] = d; capture.executed[str(p)] = d; helper.READS[str(p)] = d
    sys.addaudithook(capture.observe); sys.meta_path.insert(0, helper.SourceFinder())
    return retained, helper, capture


def source_map(bundle, retained, helper):
    result = retained.source_map(bundle.parent.identity, helper)
    for name in ('r11_sources', 'extra_executable_sources', 'external_reference_sources'):
        for path, digest in bundle.identity[name].items():
            key = helper.canonical(path)
            if key in result and result[key] != digest:
                raise ValueError('conflicting dependency/source pin')
            result[key] = digest
    return result


def stable(bundle, retained, helper, capture, *, required=False):
    bundle.verify(); expected = source_map(bundle, retained, helper)
    if bundle.identity['r11_sources'][str(HERE/'verify.py')] != ENTRY_SOURCE_SHA256:
        raise ValueError('executed entrypoint changed')
    if capture.derived_executed:
        raise ValueError('unexpected rewritten scientific code')
    for path, digest in capture.executed.items():
        if expected.get(helper.canonical(path)) != digest or sha(Path(path).read_bytes()) != digest:
            raise ValueError('actual executed source differs: '+path)
    for path, digest in helper.READS.items():
        if capture.executed.get(path) != digest:
            raise ValueError('loader/actual source execution differs')
    if required:
        paths = [p for p in bundle.identity['r11_sources'] if p.endswith('.py')]
        if any(helper.canonical(p) not in capture.executed for p in paths):
            raise ValueError('required R11 source was not executed')
        for p in bundle.identity['extra_executable_sources']:
            if helper.canonical(p) not in capture.executed:
                raise ValueError('required unchanged crop/transport producer not executed')
    return expected


def discover(helper):
    names = sorted(p.stem for p in HERE.glob('test_*.py'))
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(['work.generator_upgrade_r11.'+n for n in names])
    if loader.errors:
        raise ValueError('test discovery errors: '+repr(loader.errors))
    ids = [test.id() for test in helper.flatten(suite)]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('unique nonempty tests required')
    return suite, ids


def require_inventory(ids):
    if (RELEASE_READY is not True or type(EXPECTED_COUNT) is not int or EXPECTED_COUNT <= 0
            or type(INVENTORY_SHA256) is not str or not re.fullmatch('[0-9a-f]{64}', INVENTORY_SHA256)):
        raise ValueError('reviewed implementation/inventory pending; no release seal')
    if len(ids) != EXPECTED_COUNT or sha(encoded(ids)) != INVENTORY_SHA256:
        raise ValueError('reviewed exact test inventory differs')


def validate_tests(record):
    ids = record['test_ids']; require_inventory(ids)
    if record['status'] != 'PASS' or type(record['tests']) is not int or record['tests'] != len(ids):
        raise ValueError('complete successful test run required')
    for key in ('started', 'stopped', 'passed'):
        if record[key] != ids:
            raise ValueError('actual test identities differ')
    if any(type(record[k]) is not int or record[k] != 0 for k in
            ('failures', 'errors', 'skips', 'expected_failures', 'unexpected_successes')):
            raise ValueError('no failed/skipped/expected-failure tests permitted')


def validate_worker_header(record, bundle, mode):
    if (type(mode) is not int or mode not in (0, 2) or record.get('status') != 'PASS'
            or type(record.get('optimisation_flag')) is not int or record['optimisation_flag'] != mode
            or record.get('source_identity') != bundle.identity or record.get('source_sha256') != bundle.source_sha256):
        raise ValueError('complete matching actual worker mode/source required')


def require_executed_sources(executed, expected, required, canonical):
    if type(executed) is not dict or not executed:
        raise ValueError('nonempty actual executed source map required')
    observed = {canonical(p): d for p, d in executed.items()}
    if len(observed) != len(executed) or not {canonical(p) for p in required} <= set(observed):
        raise ValueError('complete unique required actual execution map required')
    for path, digest in observed.items():
        if expected.get(path) != digest:
            raise ValueError('actual executed source binding differs')


def validate_execution(record, bundle, retained, helper):
    expected = source_map(bundle, retained, helper)
    required = [p for p in bundle.identity['r11_sources'] if p.endswith('.py')]+list(bundle.identity['extra_executable_sources'])
    actual = record['executed_source_hashes']
    require_executed_sources(actual, expected, required, helper.canonical)
    for path, digest in actual.items():
        if sha(Path(path).read_bytes()) != digest:
            raise ValueError('saved actual worker source bytes changed')
    private = record['private_dependency_executions']
    if type(private) is not dict or set(private) != {'r11', 'r10', 'r9', 'r8', 'r7', 'r6'}:
        raise ValueError('complete actual R11 and retained private graph chain required')
    retained.validate_private_executions({k:v for k,v in private.items() if k != 'r11'}, actual, bundle.parent, helper)
    rows = private['r11']
    if type(rows) is not dict or not rows:
        raise ValueError('actual R11 private execution map required')
    required_modules = {'work.generator_upgrade_r11.'+Path(p).stem for p in bundle.identity['r11_sources']
        if p.endswith('.py') and not Path(p).stem.startswith('test_')
        and Path(p).stem not in {'__init__', 'binding', 'provenance', 'fixtures', 'verify'}}
    if not required_modules <= set(rows):
        raise ValueError('complete scientific R11 private execution required')
    observed = {helper.canonical(p): d for p,d in actual.items()}
    for logical, row in rows.items():
        if type(row) is not dict or set(row) != {'path', 'sha256'} or logical not in bundle.graph.nodes:
            raise ValueError('explicit private logical/source binding required')
        node = bundle.graph.nodes[logical]; key = helper.canonical(row['path'])
        if (helper.canonical(node[0]) != key or node[1] != row['sha256']
                or expected.get(key) != row['sha256'] or observed.get(key) != row['sha256']):
            raise ValueError('R11 private/actual executed source differs')


def tests(suite, ids, helper):
    stream = io.StringIO(); start = time.perf_counter()
    r = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=helper.Result).run(suite)
    return {'status': 'PASS' if r.wasSuccessful() else 'FAIL', 'tests': r.testsRun, 'test_ids': ids,
        'started': r.started, 'stopped': r.stopped, 'passed': r.passed, 'failures': len(r.failures),
        'errors': len(r.errors), 'skips': len(r.skipped), 'expected_failures': len(r.expectedFailures),
        'unexpected_successes': len(r.unexpectedSuccesses), 'log': stream.getvalue(),
        'elapsed_wall_seconds': time.perf_counter()-start}


def persist_workflow(bundle, root, product):
    """Store each scientific unit independently; never flatten a whole world."""
    s = bundle.storage; root = s.plain_path(root); root.mkdir(exist_ok=False)
    s.plain_path(root/'artifacts').mkdir()
    metadata = {k: v for k, v in product.items() if k not in
        ('graph_artifact', 'graph_checkpoint', 'graph_recipe', 'packed_artifacts')}
    metadata['artifact_ids'] = sorted(product['packed_artifacts'])
    rows = {'metadata.json': metadata, 'graph.json': product['graph_artifact'],
        'checkpoint.json': product['graph_checkpoint'], 'recipe.json': product['graph_recipe']}
    codec = bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    for key, value in product['packed_artifacts'].items():
        if type(key) is not str or not re.fullmatch('[0-9a-f]{64}', key) or value['sha256'] != key:
            raise ValueError('exact content-addressed scientific unit required')
        codec.unpack(value)
        rows['artifacts/'+key+'.json'] = value
    for name, value in rows.items():
        s.write_json(root/name, value)
    record = {'path': str(root), 'files': {name: sha((root/name).read_bytes()) for name in sorted(rows)}}
    record['content_sha256'] = sha(encoded(record['files']))
    if read_workflow(bundle, record) != product:
        raise ValueError('saved individual scientific units differ from executed graph')
    return record


def read_workflow(bundle, record):
    s = bundle.storage; root = s.plain_path(record['path']); files = record['files']
    if not isinstance(files, dict) or not WORKFLOW_ENVELOPES <= set(files):
        raise ValueError('complete separate graph envelope inventory required')
    pattern = r'(?:metadata|graph|checkpoint|recipe)\.json|artifacts/[0-9a-f]{64}\.json'
    if any(type(name) is not str or re.fullmatch(pattern, name) is None for name in files):
        raise ValueError('exact bounded artifact file names required')
    if record['content_sha256'] != sha(encoded(files)):
        raise ValueError('workflow file manifest digest differs')
    if {p.name for p in root.iterdir()} != WORKFLOW_ENVELOPES | {'artifacts'}:
        raise ValueError('unexpected workflow envelope or directory')
    artifact_dir = s.plain_path(root/'artifacts')
    observed = WORKFLOW_ENVELOPES | {'artifacts/'+p.name for p in artifact_dir.iterdir()}
    if observed != set(files):
        raise ValueError('saved scientific unit inventory differs')
    rows = {}
    for name, digest in files.items():
        path = s.plain_path(root/name)
        if type(digest) is not str or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('exact scientific file digest required')
        rows[name] = read_pinned_json(s, path, digest)
    metadata = rows['metadata.json']; ids = metadata.pop('artifact_ids')
    if type(ids) is not list or ids != sorted(set(ids)) or {'artifacts/'+k+'.json' for k in ids} != set(files)-WORKFLOW_ENVELOPES:
        raise ValueError('complete unique declared scientific unit inventory required')
    records = {key: rows['artifacts/'+key+'.json'] for key in ids}
    codec = bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    for key, value in records.items():
        if value['sha256'] != key:
            raise ValueError('saved scientific content address differs')
        codec.unpack(value)
    return {**metadata, 'graph_artifact': rows['graph.json'], 'graph_checkpoint': rows['checkpoint.json'],
        'graph_recipe': rows['recipe.json'], 'packed_artifacts': records}


def persist_consequence(bundle, root, name, value):
    """Persist bounded metadata and shared, individually bounded scenario units."""
    if name not in PARTITIONED_NAMES:
        raise ValueError('declared consequence filename required')
    s = bundle.storage; root = s.plain_path(root)
    directory = s.plain_path(root/'consequence-units'); directory.mkdir(exist_ok=True)
    codec = bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    manifest, units = bundle.module('consequences').split(value, codec)
    checksums = {}
    for key, record in units.items():
        path = directory/(key+'.json'); raw = s.encoded(record)
        checksum = sha(raw)
        if path.exists():
            if read_pinned_json(s, path, checksum) != record:
                raise ValueError('shared scientific record differs')
        else:
            s.write_json(path, record)
        checksums[key] = checksum
    s.write_json(root/name, manifest)
    return checksums


def read_consequences(bundle, root, values, checksums):
    """Restore exact in-memory results only from a closed saved unit inventory."""
    s = bundle.storage; root = s.plain_path(root)
    directory = s.plain_path(root/'consequence-units')
    if (type(checksums) is not dict or any(type(k) is not str or re.fullmatch('[0-9a-f]{64}', k) is None
            or type(v) is not str or re.fullmatch('[0-9a-f]{64}', v) is None for k,v in checksums.items())):
        raise ValueError('exact consequence unit checksum inventory required')
    if {p.name for p in directory.iterdir()} != {k+'.json' for k in checksums}:
        raise ValueError('saved consequence unit inventory differs')
    units = {key: read_pinned_json(s, directory/(key+'.json'), digest) for key,digest in checksums.items()}
    codec = bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    module = bundle.module('consequences'); restored = dict(values); used = set()
    for name in PARTITIONED_NAMES:
        if name not in values:
            raise ValueError('complete partitioned consequence file inventory required')
        manifest = values[name]; ids = manifest.get('unit_sha256s')
        if type(ids) is not list or any(type(k) is not str or k not in units for k in ids):
            raise ValueError('manifest names an unavailable consequence unit')
        restored[name] = module.join(manifest, {k: units[k] for k in ids}, codec)
        used.update(ids)
    if used != set(units):
        raise ValueError('orphan consequence unit refused')
    return restored


def validate_consequence_view(bundle, recipe, parent, generated, legacy, view):
    """Compare graph-produced science with the independent compatibility run."""
    w = bundle.module('workflow')
    if view != w.materialise_consequences(bundle, recipe, generated):
        raise ValueError('saved consequence view differs from actual graph artifacts')
    bundle.module('audit').result(bundle, recipe, parent, view)
    codec = bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    keys = ('scenario_id', 'parent_unit_sha256', 'water', 'ecosystems', 'human', 'human_inputs',
        'water_joins', 'ecosystem_joins', 'status', 'actual_biology_calibrated', 'fixed_snapshot_not_history')
    if set(view['state']['results']) != set(legacy['state']['results']):
        raise ValueError('workflow/compatibility scenario set differs')
    for key, packed in view['state']['results'].items():
        actual = codec.unpack(packed); previous = codec.unpack(legacy['state']['results'][key])
        if any(actual[k] != previous[k] for k in keys):
            raise ValueError('actual registered workflow/compatibility science differs: '+key)
    return {'group_count': len(view['state']['results']), 'core_fields_per_group': list(keys),
        'science_parity': 'EXACT', 'soil_feedback': 'RETAINED_SEPARATELY_AND_AUDITED_NOT_LEGACY_EQUIVALENCE'}


def thermal_diagnostic(bundle):
    """Retain the already executed actual-layer test, without rerunning heat."""
    case = sys.modules['work.generator_upgrade_r11.test_soil_feedback'].SoilFeedbackTests
    codec = bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    return {'schema': 'diadem.executed-held-soil-thermal-diagnostic.r11', 'source_sha256': bundle.source_sha256,
        'actual_unit': codec.pack(case.unit), 'specification': codec.pack(case.spec), 'result': codec.pack(case.thermal_result),
        'source_token_semantics': 'Original isolated-test a*64 identity retained; actual executed R11 bytes are bound by this envelope and worker receipt',
        'scope': 'Actual retained layers and air; initial water held fixed, not time-varying frozen Richards'}


def validate_thermal_diagnostic(bundle, value):
    if value['schema'] != 'diadem.executed-held-soil-thermal-diagnostic.r11' or value['source_sha256'] != bundle.source_sha256:
        raise ValueError('actual executed thermal diagnostic source differs')
    codec = bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    unit, spec, product = (codec.unpack(value[key]) for key in ('actual_unit','specification','result'))
    fixture = bundle.module('fixtures').parent(bundle)
    if sha(encoded(unit)) not in {row['sha256'] for row in fixture['state']['results'].values()}:
        raise ValueError('thermal reference actual unit differs from pinned source fixture')
    sw = bundle.parent.parent.parent.parent.parent.solver
    if spec != bundle.module('soil_feedback').thermal_reference_spec(sw, unit):
        raise ValueError('actual thermal source/specification join differs')
    if product['source_binding_sha256'] != 'a'*64 or product['scenario_id'] != 'actual-held-thermal':
        raise ValueError('isolated thermal test identity changed or promoted')
    return bundle.module('audit_soil').thermal_reference(spec, product)


def artifacts(bundle, root):
    root.mkdir(exist_ok=False); s = bundle.storage; timers = {}
    def timed(name, call):
        start = time.perf_counter(); value = call(); timers[name] = time.perf_counter()-start
        return value
    s.write_json(root/'recipe.json', bundle.reference.recipe(bundle)); recipe = s.read_json(root/'recipe.json')
    diagnostic = thermal_diagnostic(bundle); s.write_json(root/'thermal-diagnostic.json', diagnostic)
    diagnostic_checks = validate_thermal_diagnostic(bundle, diagnostic)
    w = bundle.module('workflow'); wa = bundle.module('audit_workflow')
    generated = timed('actual_generated_workflow', lambda: bundle.run_workflow(recipe))
    workflow_records = {'workflow-generated': persist_workflow(bundle, root/'workflow-generated', generated)}
    workflow_checks = {'workflow-generated': wa.result(bundle, recipe, generated)}
    s.write_json(root/'parent-result.json', w.resolve(bundle, generated, generated['parent_ref']))
    parent = s.read_json(root/'parent-result.json'); p = bundle.module('pipeline')
    # Fresh R8/R9/R10 scientific runs actually occur INSIDE registered producers
    # above. Subsequent saved-parent seams are explicitly supplied, not fresh R10.
    supplied = timed('explicit_supplied_workflow', lambda: bundle.run_workflow(recipe, supplied_parent=parent))
    workflow_records['workflow-supplied'] = persist_workflow(bundle, root/'workflow-supplied', supplied)
    workflow_checks['workflow-supplied'] = wa.result(bundle, recipe, supplied, supplied_parent=parent)
    count = w.graph_stop_after_first_human(bundle, recipe, supplied_parent=parent)
    stopped_graph = timed('workflow_stage_boundary_stop', lambda: bundle.run_workflow(recipe, supplied_parent=parent, stop_after=count))
    workflow_records['workflow-stop'] = persist_workflow(bundle, root/'workflow-stop', stopped_graph)
    workflow_checks['workflow-stop'] = wa.result(bundle, recipe, stopped_graph, supplied_parent=parent, complete=False)
    saved_graph = read_workflow(bundle, workflow_records['workflow-stop'])
    resumed_graph = timed('saved_workflow_checkpoint_restart', lambda: bundle.run_workflow(recipe, supplied_parent=parent,
        resume=saved_graph['graph_checkpoint']))
    workflow_records['workflow-restart'] = persist_workflow(bundle, root/'workflow-restart', resumed_graph)
    workflow_checks['workflow-restart'] = wa.result(bundle, recipe, resumed_graph, supplied_parent=parent)
    view = w.materialise_consequences(bundle, recipe, generated)
    consequence_units = persist_consequence(bundle, root, 'workflow-consequences.json', view)
    def save_consequence(name, value):
        for key, digest in persist_consequence(bundle, root, name, value).items():
            if key in consequence_units and consequence_units[key] != digest:
                raise ValueError('same scientific unit identity has different saved bytes')
            consequence_units[key] = digest
    full = timed('all_scenarios', lambda: p.run_from_parent(bundle, recipe, parent))
    save_consequence('full-result.json', full); save_consequence('full-checkpoint.json', bundle.checkpoint(full))
    checks = bundle.module('audit').result(bundle, recipe, parent, full)
    stopped = timed('one_scenario', lambda: p.run_from_parent(bundle, recipe, parent, stop_after=1))
    save_consequence('stop-result.json', stopped); save_consequence('stop-checkpoint.json', bundle.checkpoint(stopped))
    saved_checkpoint = s.read_json(root/'stop-checkpoint.json')
    codec = bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    saved_units = {key: read_pinned_json(s, root/'consequence-units'/(key+'.json'), consequence_units[key])
        for key in saved_checkpoint['unit_sha256s']}
    saved_checkpoint = bundle.module('consequences').join(saved_checkpoint, saved_units, codec)
    resumed = timed('saved_checkpoint_restart', lambda: p.run_from_parent(bundle, recipe, parent, resume=saved_checkpoint))
    save_consequence('restart-result.json', resumed); save_consequence('restart-checkpoint.json', bundle.checkpoint(resumed))
    record = {'path': str(root), 'files': {name: sha((root/name).read_bytes()) for name in ARTIFACT_NAMES},
        'reference_sha256': bundle.module('consequences').digest(full, codec),
        'consequence_units': consequence_units, 'scientific_checks': checks, 'elapsed_wall_seconds': timers,
        'workflows': workflow_records, 'workflow_checks': workflow_checks,
        'thermal_diagnostic_checks': diagnostic_checks,
        'workflow_stop_completed_stages': count,
        'workflow_consequence_parity': validate_consequence_view(bundle, recipe, parent, generated, full, view)}
    validate_artifacts(record, bundle)
    return record


def validate_artifacts(record, bundle):
    s = bundle.storage; root = s.plain_path(record['path'])
    if (set(record['files']) != ARTIFACT_NAMES or set(record['workflows']) != set(WORKFLOW_NAMES)
            or {p.name for p in root.iterdir()} != ARTIFACT_NAMES | set(WORKFLOW_NAMES) | {'consequence-units'}):
        raise ValueError('exact immutable artifact inventory required')
    values = {}
    for name, digest in record['files'].items():
        values[name] = read_pinned_json(s, root/name, digest)
    values = read_consequences(bundle, root, values, record['consequence_units'])
    full = values['full-result.json']
    if record['thermal_diagnostic_checks'] != validate_thermal_diagnostic(bundle, values['thermal-diagnostic.json']):
        raise ValueError('saved held-soil thermal audit differs')
    if full != values['restart-result.json'] or values['full-checkpoint.json'] != values['restart-checkpoint.json']:
        raise ValueError('full versus actual saved restart differs')
    for label in ('full', 'stop', 'restart'):
        if bundle.checkpoint(values[label+'-result.json']) != values[label+'-checkpoint.json']:
            raise ValueError('saved state/checkpoint differs')
    if values['stop-result.json']['state']['completed_scenarios'] != 1:
        raise ValueError('exact saved scenario-boundary stop required')
    codec = bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    if record['reference_sha256'] != bundle.module('consequences').digest(full, codec):
        raise ValueError('complete scientific bytes differ')
    checks = bundle.module('audit').result(bundle, values['recipe.json'], values['parent-result.json'], full)
    if checks != record['scientific_checks']:
        raise ValueError('independent saved scientific audit differs')
    workflows = {}
    for label in WORKFLOW_NAMES:
        ref = record['workflows'][label]
        if s.plain_path(ref['path']) != root/label:
            raise ValueError('workflow record points outside this saved run')
        workflows[label] = read_workflow(bundle, ref)
        checked = bundle.module('audit_workflow').result(bundle, values['recipe.json'], workflows[label],
            supplied_parent=None if label == 'workflow-generated' else values['parent-result.json'],
            complete=label != 'workflow-stop')
        if checked != record['workflow_checks'][label]:
            raise ValueError('independent saved workflow audit differs')
    if workflows['workflow-supplied'] != workflows['workflow-restart']:
        raise ValueError('complete graph/scientific artifacts differ after saved restart')
    stopped = workflows['workflow-stop']['graph_artifact']; completed = workflows['workflow-supplied']['graph_artifact']
    if (stopped['state']['completed_stages'] != record['workflow_stop_completed_stages']
            or not 0 < stopped['state']['completed_stages'] < completed['state']['completed_stages']
            or stopped['status'] != 'STOPPED'):
        raise ValueError('meaningful saved graph-stage boundary required')
    generated = workflows['workflow-generated']; supplied = workflows['workflow-supplied']
    for key in ('parent_ref', 'physical_parent_ref', 'biology_parent_ref', 'biological_owner_overlay_ref'):
        if generated[key]['sha256'] != supplied[key]['sha256']:
            raise ValueError('fresh/generated versus supplied-parent source artifact differs')
    if generated['scenario_product_refs'] != supplied['scenario_product_refs']:
        raise ValueError('generated versus explicit supplied-parent scenario science differs')
    if record['workflow_consequence_parity'] != validate_consequence_view(bundle, values['recipe.json'],
            values['parent-result.json'], generated, full, values['workflow-consequences.json']):
        raise ValueError('saved workflow/compatibility comparison differs')
    return values


def worker(path, parent_path, mode):
    retained, helper, capture = install()
    from work.generator_upgrade_r11 import binding
    bundle = binding.load(); s = bundle.storage; start = time.perf_counter()
    parent = s.read_json(parent_path)
    if sys.flags.optimize != mode or parent['source_identity'] != bundle.identity or parent['source_sha256'] != bundle.source_sha256:
        raise ValueError('actual worker mode/source differs')
    suite, ids = discover(helper); require_inventory(ids)
    record = {'status': 'FAIL', 'optimisation_flag': sys.flags.optimize, 'source_identity': bundle.identity,
        'source_sha256': bundle.source_sha256, 'tests': tests(suite, ids, helper)}
    try:
        validate_tests(record['tests']); print('tests passed: '+str(len(ids)), flush=True)
        record['artifacts'] = artifacts(bundle, path.parent/(path.stem+'-reference'))
        stable(bundle, retained, helper, capture, required=True)
        private = {'r11': dict(bundle.graph.executed), **retained.private_executions(bundle.parent)}
        retained.validate_private_executions({k: v for k, v in private.items() if k != 'r11'}, capture.executed, bundle.parent, helper)
        record.update(status='PASS', private_dependency_executions=private)
        validate_execution({**record, 'executed_source_hashes': dict(capture.executed)}, bundle, retained, helper)
    except Exception as exc:
        record['status'] = 'FAIL'
        record['failure'] = repr(exc)
        record['failure_traceback'] = traceback.format_exc()
    record.update(executed_source_hashes=dict(capture.executed), elapsed_wall_seconds=time.perf_counter()-start)
    s.write_json(path, record); capture.active = False
    print(json.dumps({'status': record['status'], 'mode': mode, 'failure': record.get('failure')}), flush=True)
    return 0 if record['status'] == 'PASS' else 1


def final(run_id):
    if type(run_id) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,47}', run_id):
        raise ValueError('new bounded run identifier required')
    retained, helper, capture = install()
    from work.generator_upgrade_r11 import binding
    bundle = binding.load(); _, ids = discover(helper); require_inventory(ids)
    stable(bundle, retained, helper, capture)
    root = bundle.storage.plain_path(OUTPUT_ROOT/run_id); root.mkdir(parents=True, exist_ok=False)
    s = bundle.storage
    s.write_json(root/'PARENT_SOURCE.json', {'source_identity': bundle.identity, 'source_sha256': bundle.source_sha256,
        'parent_optimisation_flag': sys.flags.optimize})
    records = []; worker_digests = {}
    for label, mode, flags in (('n', 0, []), ('o', 2, ['-OO'])):
        path = root/(label+'-worker.json')
        command = [sys.executable, '-B', *flags, str(HERE/'verify.py'), '--worker', str(path),
            '--parent-source', str(root/'PARENT_SOURCE.json'), '--mode', str(mode)]
        print('Executing fresh-source verification mode '+str(mode), flush=True)
        try:
            proc = subprocess.run(command, cwd=TASK, env=helper.child_environment(), text=True, capture_output=True, timeout=3600)
        except subprocess.TimeoutExpired as exc:
            def report_text(value):
                return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
            s.write_json(root/(label+'-process.json'), {'status': 'TIMEOUT', 'exit_code': None,
                'timeout_seconds': 3600, 'stdout': report_text(exc.stdout), 'stderr': report_text(exc.stderr)})
            raise RuntimeError('worker timed out; evidence preserved, no seal: '+str(path)) from exc
        s.write_json(root/(label+'-process.json'), {'exit_code': proc.returncode, 'stdout': proc.stdout, 'stderr': proc.stderr})
        if proc.returncode:
            raise RuntimeError('worker failed; evidence preserved, no seal: '+str(path))
        raw = path.read_bytes()
        if len(raw) > 8*1024*1024:
            raise ValueError('bounded worker receipt required')
        worker_digests[label] = sha(raw); row = s.decoded(raw)
        validate_worker_header(row, bundle, mode)
        validate_tests(row['tests']); validate_artifacts(row['artifacts'], bundle)
        validate_execution(row, bundle, retained, helper)
        records.append(row)
    for key in ('executed_source_hashes', 'private_dependency_executions'):
        if records[0][key] != records[1][key]:
            raise ValueError('cross-mode scientific source identity differs')
    if records[0]['artifacts']['reference_sha256'] != records[1]['artifacts']['reference_sha256']:
        raise ValueError('cross-mode scientific full result differs')
    for key in ('files', 'consequence_units'):
        if records[0]['artifacts'][key] != records[1]['artifacts'][key]:
            raise ValueError('cross-mode saved result/checkpoint/unit bytes differ: '+key)
    for label in WORKFLOW_NAMES:
        if records[0]['artifacts']['workflows'][label]['content_sha256'] != records[1]['artifacts']['workflows'][label]['content_sha256']:
            raise ValueError('cross-mode complete graph/checkpoint/scientific artifact bytes differ: '+label)
    stable(bundle, retained, helper, capture)
    for label, digest in worker_digests.items():
        if sha((root/(label+'-worker.json')).read_bytes()) != digest:
            raise ValueError('validated worker receipt changed before seal')
    seal = {'schema': 'diadem.seasonal-consequences-verification.r11',
        'status': 'BOUNDED_SEASONAL_CONSEQUENCES_VERIFIED_WITH_EXPLICIT_WORLD_INPUT_GAPS',
        'source_identity': bundle.identity, 'source_sha256': bundle.source_sha256,
        'source_snapshot': bundle.identity['r11_sources'], 'test_ids': ids, 'test_count_per_mode': len(ids),
        'inventory_sha256': sha(encoded(ids)), 'actual_worker_flags': [0, 2], 'parent_optimisation_flag': sys.flags.optimize,
        'normal_oo_parity': 'EXACT_FULL_SCIENTIFIC_RESULTS_AND_SAVED_CHECKPOINTS',
        'workers': {label: {'path': str(root/(label+'-worker.json')), 'sha256': worker_digests[label]} for label in ('n', 'o')},
        'whole_generator_complete': False, 'production_installed': False, 'canon_changed': False, 'optimisation_performed': False}
    s.write_json(root/'VERIFICATION.json', seal); capture.active = False
    print(json.dumps({'status': seal['status'], 'path': str(root/'VERIFICATION.json')}), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run-id'); parser.add_argument('--inventory', action='store_true')
    parser.add_argument('--worker', type=Path); parser.add_argument('--parent-source', type=Path)
    parser.add_argument('--mode', type=int, choices=(0, 2)); args = parser.parse_args()
    if args.inventory:
        retained, helper, capture = install(); _, ids = discover(helper)
        print(json.dumps({'test_count': len(ids), 'inventory_sha256': sha(encoded(ids)), 'test_ids': ids})); capture.active = False
        return 0
    if args.worker:
        if args.parent_source is None or args.mode is None:
            parser.error('worker requires source and actual mode')
        return worker(args.worker, args.parent_source, args.mode)
    if not args.run_id:
        parser.error('new run ID required')
    return final(args.run_id)


if __name__ == '__main__':
    raw = Path(__file__).read_bytes(); namespace = {'__file__': __file__, '__name__': '_r11_fresh_verification_entry'}
    exec(compile(raw, __file__, 'exec', dont_inherit=True), namespace)
    namespace['ENTRY_SOURCE_SHA256'] = sha(raw)
    raise SystemExit(namespace['main']())
