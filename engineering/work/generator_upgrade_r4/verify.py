"""Exact-source, exact-inventory two-mode verification of the connected R4.

The final inventory remains explicitly unsealed until the owner freezes sources.
No missing suite or changed test count can be accepted by merely counting passes.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.abc
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unittest

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
if str(TASK) not in sys.path:
    sys.path.insert(0, str(TASK))
SUITES = ('test_storage', 'test_provenance', 'test_climate', 'test_hydromet',
          'test_retained_bridge', 'test_pipeline', 'test_coupled_climate', 'test_coupled_hydromet',
          'test_cli', 'test_verification')
EXPECTED_TEST_COUNT = 261
INVENTORY_SHA256 = '1b89b393bbecc1af6b0b2186258c02157dee7ccc483d59add78407f9c29dc3f3'
EXPECTED_PROTECTED_COUNT = 161
EXPECTED_CATEGORY_CONTRACT_COUNT = 4
EXPECTED_RETAINED_R3_COUNT = 25
EXPECTED_DEPENDENCY_COUNT = 2
WORKER_TIMEOUT_SECONDS = 1800
CLI_TIMEOUT_SECONDS = 600
ENTRY_SOURCE_SHA256 = None
READS = {}
RETAINED_WORK_ROOT = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-07-11/referenced-chatgpt-conversation-this-is-untrusted/work')
DERIVED_PREFIX = '<environment-successor:'
DERIVER_PATH = TASK / 'work/module_review_environment_r1/bindings.py'
DIAGNOSTICS_SCOPE = ('Actual successful-suite products retained without rerunning; internal source IDs are fixture-local '
                     'binding tokens, while this worker source_identity and execution records bind actual code. '
                     'No whole-chain first-order accuracy or new-terrain compatibility of retained A forcing is claimed.')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(path):
    return str(Path(path).resolve())


def inventory_digest(ids):
    return sha(json.dumps(ids, separators=(',', ':'), ensure_ascii=True).encode())


def child_environment():
    environment = os.environ.copy()
    environment.pop('PYTHONOPTIMIZE', None)
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    return environment


class SourceLoader(importlib.abc.Loader):
    """Compile the captured bytes directly; never consult timestamp-valid pyc."""
    def __init__(self, path):
        self.path = Path(path).resolve()

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raw = self.path.read_bytes()
        key, digest = str(self.path), sha(raw)
        if key in READS and READS[key] != digest:
            raise ValueError('project source changed between executions: ' + key)
        READS[key] = digest
        module.__file__ = key
        exec(compile(raw, key, 'exec', dont_inherit=True), module.__dict__)


class SourceFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'work' and not fullname.startswith('work.'):
            return None
        base = TASK.joinpath(*fullname.split('.'))
        for candidate, package in ((base.with_suffix('.py'), False), (base / '__init__.py', True)):
            if candidate.is_file():
                return importlib.util.spec_from_file_location(fullname, candidate,
                    loader=SourceLoader(candidate), submodule_search_locations=[str(base)] if package else None)
        return None


class ExecutionCapture:
    """Observe actual project compile/exec, including privately compiled pins.

    Third-party runtime libraries remain governed by the runtime identity; their
    bytecode is not misrepresented as project source. The hooks are disabled at
    exit because CPython audit hooks are not removable within the process.
    """
    def __init__(self, task=TASK):
        self.task = Path(task).resolve()
        self.compiled = {}
        self.executed = {}
        self.derived_compiled = {}
        self.derived_executed = {}
        self.active = True

    def project_path(self, filename):
        if not isinstance(filename, str) or filename.startswith('<'):
            return None
        path = Path(filename).resolve()
        relative = None
        for root in (self.task / 'work', RETAINED_WORK_ROOT):
            try:
                relative = path.relative_to(root)
                break
            except ValueError:
                pass
        if relative is None:
            return None
        if path.suffix != '.py' or 'runtime' in relative.parts or 'site-packages' in relative.parts:
            return None
        return str(path)

    def observe(self, event, args):
        if not self.active:
            return
        if event == 'compile':
            source, filename = args
            # CPython reports filename=None for AST compilation. Attribute it
            # only at the actual pinned binder's _compile call frame, whose
            # direct freshly compiled execution is separately source-verified.
            # Never attach an arbitrary pending AST to a later code object.
            if isinstance(source, ast.AST) and filename is None:
                caller = sys._getframe(1)
                if canonical(caller.f_code.co_filename) == canonical(DERIVER_PATH) and caller.f_code.co_name == '_compile':
                    relative = caller.f_locals.get('relative')
                    if type(relative) is not str:
                        raise ValueError('sealed binder omitted its exact producer identity')
                    filename = DERIVED_PREFIX + relative + '>'
            if isinstance(filename, str) and filename.startswith(DERIVED_PREFIX):
                producer = derived_producer_path(filename)
                if not isinstance(source, ast.AST):
                    raise ValueError('retained derived execution requires the sealed AST-binding path')
                representation = ast.dump(source, annotate_fields=True, include_attributes=True).encode('utf-8')
                if len(representation) > 2 * 1024 * 1024:
                    raise ValueError('derived AST exceeds the bounded execution envelope')
                proof = {'ast_sha256': sha(representation), 'producer_path': str(producer),
                         'producer_sha256': sha(producer.read_bytes()), 'deriver_path': str(DERIVER_PATH),
                         'deriver_sha256': sha(DERIVER_PATH.read_bytes()),
                         'meaning': 'source-derived bound functions; original full module not executed'}
                if filename in self.derived_compiled and self.derived_compiled[filename] != proof:
                    raise ValueError('different derived AST compiled under one producer identity')
                self.derived_compiled[filename] = proof
                return
            key = self.project_path(filename)
            if key is None:
                return
            if type(source) not in (str, bytes):
                raise ValueError('project execution requires captured source bytes, not an uncaptured AST')
            raw = source.encode('utf-8') if type(source) is str else source
            digest = sha(raw)
            if key in self.compiled and self.compiled[key] != digest:
                raise ValueError('different project bytes compiled under one path: ' + key)
            self.compiled[key] = digest
        elif event == 'exec':
            filename = args[0].co_filename
            if filename.startswith(DERIVED_PREFIX):
                if filename not in self.derived_compiled:
                    raise ValueError('derived project code executed without fresh AST capture')
                self.derived_executed[filename] = self.derived_compiled[filename]
                return
            key = self.project_path(args[0].co_filename)
            if key is None:
                return
            if key not in self.compiled:
                raise ValueError('project code executed without freshly captured source: ' + key)
            self.executed[key] = self.compiled[key]


def derived_producer_path(filename):
    if type(filename) is not str or not filename.startswith(DERIVED_PREFIX) or not filename.endswith('>'):
        raise ValueError('exact bounded derived producer filename required')
    relative = Path(filename[len(DERIVED_PREFIX):-1])
    if relative.is_absolute() or '..' in relative.parts or relative.suffix != '.py' or relative.parts[0] != 'work':
        raise ValueError('derived producer path escapes retained source scope')
    return (RETAINED_WORK_ROOT.parent / relative).resolve()


def install_fresh_execution():
    # A prior import could supply stale live objects even if later file hashes
    # match. Standalone worker/CLI entrypoints therefore start without project
    # modules; tests may use the lower-level loader on isolated fixtures.
    if any(name.startswith('work.') for name in sys.modules):
        raise ValueError('fresh verification process already contains project modules')
    if ENTRY_SOURCE_SHA256 is None:
        raise ValueError('entrypoint was not freshly compiled from captured bytes')
    capture = ExecutionCapture()
    key = canonical(__file__)
    capture.compiled[key] = ENTRY_SOURCE_SHA256
    capture.executed[key] = ENTRY_SOURCE_SHA256
    READS[key] = ENTRY_SOURCE_SHA256
    sys.addaudithook(capture.observe)
    sys.meta_path.insert(0, SourceFinder())
    return capture


def source_capture():
    from work.generator_upgrade_r4 import provenance
    identity, digest = provenance.source_identity()
    if len(identity['protected_sources']) != EXPECTED_PROTECTED_COUNT:
        raise ValueError('protected predecessor source inventory differs')
    if len(identity['category_contracts']) != EXPECTED_CATEGORY_CONTRACT_COUNT:
        raise ValueError('retained category contract inventory differs')
    if (len(identity['r3_sources']) != EXPECTED_RETAINED_R3_COUNT
            or len(identity['executed_dependency_sources']) != EXPECTED_DEPENDENCY_COUNT):
        raise ValueError('sealed R3/additional execution dependency inventory differs')
    return identity, digest


def source_map(identity):
    merged = {}
    maps = [identity[section] for section in ('r4_sources', 'r3_sources', 'protected_sources',
             'category_contracts', 'physical_interfaces', 'executed_dependency_sources', 'climate_owner_bindings',
             'hydromet_source_bindings')]
    maps.append(identity['climate_source_bindings']['sources'])
    for mapping in maps:
        for path, digest in mapping.items():
            key = canonical(path)
            if key in merged and merged[key] != digest:
                raise ValueError('conflicting captured source identity')
            merged[key] = digest
    return merged


def validate_executed(executed, identity, *, check_current=False, require_paths=()):
    if type(executed) is not dict or not executed:
        raise ValueError('nonempty actual executed-source evidence required')
    expected = source_map(identity)
    normalised = {}
    for path, digest in executed.items():
        key = canonical(path)
        if key in normalised or key not in expected or expected[key] != digest:
            raise ValueError('executed source differs from captured/approved source: ' + key)
        normalised[key] = digest
        if check_current and sha(Path(key).read_bytes()) != digest:
            raise ValueError('executed source changed after execution: ' + key)
    if any(canonical(path) not in normalised for path in require_paths):
        raise ValueError('required source was not actually executed')


def required_derived_names():
    return ('<environment-successor:work/cryosphere/c1_r1/snow_model.py>',)


def validate_derived(derived, identity, *, check_current=False, require_names=()):
    if type(derived) is not dict or len(derived) > 32:
        raise ValueError('bounded derived-execution evidence required')
    expected = source_map(identity)
    fields = {'ast_sha256', 'producer_path', 'producer_sha256', 'deriver_path', 'deriver_sha256', 'meaning'}
    for name, proof in derived.items():
        producer = str(derived_producer_path(name))
        if (type(proof) is not dict or set(proof) != fields or proof['producer_path'] != producer
                or canonical(proof['deriver_path']) != canonical(DERIVER_PATH)
                or proof['meaning'] != 'source-derived bound functions; original full module not executed'):
            raise ValueError('derived execution identity or scope differs')
        for field in ('ast_sha256', 'producer_sha256', 'deriver_sha256'):
            if type(proof[field]) is not str or not re.fullmatch('[0-9a-f]{64}', proof[field]):
                raise ValueError('exact derived execution hash required')
        for role in ('producer', 'deriver'):
            path = canonical(proof[role + '_path'])
            if expected.get(path) != proof[role + '_sha256']:
                raise ValueError('derived producer/binder differs from captured source')
            if check_current and sha(Path(path).read_bytes()) != proof[role + '_sha256']:
                raise ValueError('derived producer/binder changed after execution')
    if any(name not in derived for name in require_names):
        raise ValueError('required retained bound-function execution missing')


def assert_source_stable(before, digest, capture):
    if source_capture() != (before, digest):
        raise ValueError('source identity changed during verification')
    key = canonical(__file__)
    if before['r4_sources'].get(key) != ENTRY_SOURCE_SHA256:
        raise ValueError('actual verifier entry bytes differ from parent/source capture')
    validate_executed(capture.executed, before, check_current=True, require_paths=(key,))
    validate_derived(capture.derived_executed, before, check_current=True)
    for path, value in READS.items():
        if capture.executed.get(path) != value:
            raise ValueError('source loader and actual execution capture disagree')


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def discover():
    expected_files = {name + '.py' for name in SUITES}
    actual_files = {p.name for p in HERE.glob('test_*.py')}
    if expected_files != actual_files:
        raise ValueError('test suite file inventory differs; no omitted or undisclosed suite')
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(['work.generator_upgrade_r4.' + name for name in SUITES])
    if loader.errors:
        raise ValueError('test suite import/discovery failed: ' + repr(loader.errors))
    ids = [test.id() for test in flatten(suite)]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('test inventory must be nonempty and unique')
    return suite, ids


def require_inventory(ids):
    if type(EXPECTED_TEST_COUNT) is not int or EXPECTED_TEST_COUNT <= 0 or not isinstance(INVENTORY_SHA256, str):
        raise ValueError('reviewed test inventory is PENDING; final verification is not authorised yet')
    if type(ids) is not list or any(type(x) is not str for x in ids):
        raise ValueError('ordered exact test identities required')
    digest = inventory_digest(ids)
    if len(ids) != EXPECTED_TEST_COUNT or len(set(ids)) != len(ids) or digest != INVENTORY_SHA256:
        raise ValueError('test inventory differs from the exact reviewed inventory')
    return digest


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started, self.stopped, self.passed = [], [], []

    def startTest(self, test):
        self.started.append(test.id())
        super().startTest(test)

    def stopTest(self, test):
        self.stopped.append(test.id())
        super().stopTest(test)

    def addSuccess(self, test):
        self.passed.append(test.id())
        super().addSuccess(test)


def validate_test_result(record):
    required = ('tests', 'failures', 'errors', 'skips', 'expected_failures', 'unexpected_successes')
    if any(type(record.get(key)) is not int for key in required):
        raise ValueError('integer execution totals required; bool is not a count')
    digest = require_inventory(record['test_ids'])
    if record['status'] != 'PASS' or record['tests'] != EXPECTED_TEST_COUNT or any(record[key] for key in required[1:]):
        raise ValueError('worker did not pass the complete unskipped suite')
    if record['inventory_sha256'] != digest or not record['test_ids'] == record['started'] == record['stopped'] == record['passed']:
        raise ValueError('ordered discovery/start/stop/success inventories disagree')


def required_worker_sources():
    return (tuple(HERE / (name + '.py') for name in (*SUITES, 'verify', 'reference', 'pipeline',
                   'cli', 'climate', 'hydromet', 'retained_bridge', 'storage', 'provenance'))
            + tuple(TASK / 'work/generator_upgrade_r3' / (name + '.py')
                    for name in ('pipeline', 'soil_inputs', 'soil_water', 'terrain_transport')))


def required_cli_sources():
    return (HERE / 'cli.py', HERE / 'pipeline.py', HERE / 'reference.py', HERE / 'climate.py', HERE / 'hydromet.py',
            TASK / 'work/generator_upgrade_r3/pipeline.py', TASK / 'work/generator_upgrade_r3/soil_water.py')


def validate_reference(reference, source_sha256):
    scenarios = {'LOW_DDF3_SIGMA2', 'DIAGNOSTIC_DDF4_SIGMA4', 'HIGH_DDF5_SIGMA6'}
    if (type(reference) is not dict or reference.get('schema') != 'diadem.connected-climate-terrain-water-soil.r4'
            or reference.get('source_sha256') != source_sha256
            or reference.get('production_installed') is not False or reference.get('canon_changed') is not False
            or reference.get('snow_family') != 'THREE_COEQUAL_SENSITIVITIES_NO_PREFERRED_MEMBER'
            or type(reference.get('members')) is not dict or set(reference['members']) != scenarios
            or type(reference.get('state')) is not dict
            or type(reference['state'].get('completed_events')) is not int
            or reference['state']['completed_events'] < 1
            or type(reference['state'].get('members')) is not dict or set(reference['state']['members']) != scenarios):
        raise ValueError('actual source-bound three-member connected reference required')
    for member in reference['members'].values():
        receipt = member.get('final_terrain_climate_diagnostic', {}).get('receipt', {})
        if receipt.get('status') != 'BOUNDED_MECHANISTIC_REFERENCE' or receipt.get('old_climate_parent_reused') is not False:
            raise ValueError('retained/fixed forcing cannot impersonate actual mechanistic climate reference')


def collect_scientific_diagnostics():
    from work.generator_upgrade_r4.test_coupled_climate import CoupledClimateRefinementTests
    from work.generator_upgrade_r4.test_retained_bridge import RetainedBridgeTests
    from work.generator_upgrade_r3.pipeline import plain
    from work.generator_upgrade_r4 import storage
    # Do not call either setUpClass or experiment again. These must be the
    # products of the exact named successful test execution just completed.
    if not hasattr(CoupledClimateRefinementTests, 'report') or not hasattr(RetainedBridgeTests, 'result'):
        raise ValueError('actual successful-suite scientific diagnostics missing')
    report = storage.decoded(storage.encoded(plain(CoupledClimateRefinementTests.report)))
    bridge = storage.decoded(storage.encoded(plain(RetainedBridgeTests.result)))
    result = {'coupled_refinement_report': report, 'coupled_refinement_sha256': sha(storage.encoded(report)),
              'retained_bridge_result': bridge, 'retained_bridge_sha256': sha(storage.encoded(bridge)),
              'scientific_diagnostics_scope': DIAGNOSTICS_SCOPE}
    validate_scientific_diagnostics(result)
    return result


def validate_scientific_diagnostics(record):
    if record.get('scientific_diagnostics_scope') != DIAGNOSTICS_SCOPE:
        raise ValueError('scientific diagnostic scope or fixture-token distinction missing')
    for product, hash_field in (('coupled_refinement_report', 'coupled_refinement_sha256'),
                                 ('retained_bridge_result', 'retained_bridge_sha256')):
        value = record.get(product)
        if type(value) is not dict or not value:
            raise ValueError('actual scientific diagnostic product missing')
        if sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()) != record.get(hash_field):
            raise ValueError('scientific diagnostic product hash differs')
    report = record['coupled_refinement_report']
    flags = report.get('first_order_criterion_met')
    expected_quantities = {'sediment_export_kg', 'terrain_change_m', 'water_export_m3', 'swe_m',
                           'precipitation_m3', 'temperature_c', 'head_integral_m2'}
    if (report.get('caps_seconds') != [120, 60, 30] or type(flags) is not dict or set(flags) != expected_quantities
            or any(type(value) is not bool for value in flags.values())
            or flags['precipitation_m3'] is not False or flags['temperature_c'] is not False
            or flags['terrain_change_m'] is not False or flags['sediment_export_kg'] is not False
            or type(report.get('differences')) is not dict or set(report['differences']) != expected_quantities
            or type(report.get('predeclared_floors')) is not dict or set(report['predeclared_floors']) != expected_quantities
            or report.get('predeclared_ratio_band') != [1.4, 3.0]):
        raise ValueError('refinement diagnostic omitted the admitted quantity/order limits')
    bridge = record['retained_bridge_result']
    scenarios = {'LOW_DDF3_SIGMA2', 'DIAGNOSTIC_DDF4_SIGMA4', 'HIGH_DDF5_SIGMA6'}
    if (bridge.get('status') != 'ACTUAL_A_MONTHLY_SNOW_DEMAND_FIXED_FORCING_SENSITIVITY'
            or bridge.get('new_terrain_compatible') is not False or bridge.get('pm_recomputed') is not False
            or bridge.get('realised_et_computed') is not False or type(bridge.get('members')) is not dict
            or set(bridge['members']) != scenarios
            or any(type(row.get('monthly')) is not list or len(row['monthly']) != 12 for row in bridge['members'].values())):
        raise ValueError('retained diagnostic must preserve twelve months, three members and fixed-forcing limits')


def validate_cli_records(rows, mode, before, digest, reference, *, readback):
    if type(rows) is not list or len(rows) != 3 or [r.get('stage') for r in rows] != ['stop', 'restart', 'full']:
        raise ValueError('exact public stop/restart/full evidence inventory required')
    if len({r.get('path') for r in rows}) != 3 or len({r.get('run_id') for r in rows}) != 3:
        raise ValueError('distinct exclusive public CLI artefacts required')
    reference_digest = sha(json.dumps(reference, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    for row in rows:
        if (type(row.get('optimisation_flag')) is not int or row['optimisation_flag'] != mode or
                row.get('source_sha256') != digest or not isinstance(row.get('run_id'), str) or
                not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}', row['run_id']) or
                Path(row.get('path', '')).name != row['run_id']):
            raise ValueError('public CLI mode/source/output identity mismatch')
        for key in ('receipt_sha256', 'result_sha256', 'checkpoint_sha256', 'execution_receipt_sha256'):
            if type(row.get(key)) is not str or not re.fullmatch('[0-9a-f]{64}', row[key]):
                raise ValueError('public CLI file digest required')
        validate_executed(row.get('executed_source_hashes'), before, require_paths=required_cli_sources())
        validate_derived(row.get('derived_executions'), before)
        if row['stage'] != 'stop' and row['result_sha256'] != reference_digest:
            raise ValueError('public full/restarted result digest differs from actual reference')
    if rows[1]['checkpoint_sha256'] != rows[2]['checkpoint_sha256']:
        raise ValueError('public full/restarted checkpoint digest differs')
    if readback:
        from work.generator_upgrade_r4 import storage
        recipes = []
        for row in rows:
            path = storage.plain_path(Path(row['path']))
            if path.parent != storage.OUTPUT_ROOT:
                raise ValueError('public CLI artifact is outside the scoped output root')
            checked = storage.read_reference(path)
            execution_path = storage.plain_path(Path(row['execution_receipt_path']))
            expected_label = 'n' if mode == 0 else 'o'
            expected_root = storage.OUTPUT_ROOT / row['run_id'].rsplit('-cli-', 1)[0]
            if (execution_path.parent != expected_root
                    or execution_path.name != expected_label + '-cli-' + row['stage'] + '.json'):
                raise ValueError('public CLI execution receipt changed or moved after worker readback')
            execution = storage.read_json(execution_path)
            if sha(execution_path.read_bytes()) != row['execution_receipt_sha256']:
                raise ValueError('public CLI execution receipt changed after worker readback')
            if (execution.get('status') != 'PASS' or type(execution.get('optimisation_flag')) is not int
                    or execution['optimisation_flag'] != mode or execution.get('source_identity') != before
                    or execution.get('source_sha256') != digest
                    or execution.get('executed_source_hashes') != row['executed_source_hashes']
                    or execution.get('derived_executions') != row['derived_executions']
                    or execution.get('public_entrypoint') != 'work.generator_upgrade_r4.cli.main'):
                raise ValueError('public CLI execution receipt differs from parent evidence')
            for field, name in (('receipt_sha256', 'RECEIPT.json'), ('result_sha256', 'result.json'), ('checkpoint_sha256', 'checkpoint.json')):
                if sha((path / name).read_bytes()) != row[field]:
                    raise ValueError('public CLI artifact changed after worker readback')
            proof = checked['receipt']['evidence']
            if proof['source_identity'] != before or proof['source_sha256'] != digest:
                raise ValueError('public CLI receipt differs from parent source capture')
            recipe = checked['recipe.json']
            recipes.append(recipe)
            state = storage.restore(checked['checkpoint.json'], recipe_sha256=sha(storage.encoded(recipe)), source_sha256=digest)
            if state != checked['result.json']['state']:
                raise ValueError('public checkpoint and saved result state differ')
            if row['stage'] == 'stop':
                if state['completed_events'] != 1:
                    raise ValueError('public stop checkpoint has the wrong event cursor')
            elif checked['result.json'] != reference:
                raise ValueError('public artifact readback differs from actual direct reference')
        if recipes[0] != recipes[1] or recipes[1] != recipes[2]:
            raise ValueError('public CLI stop/restart/full recipes differ')


def validate_workers(records, before, before_digest, *, check_cli_artifacts=True):
    if type(records) is not list or len(records) != 2:
        raise ValueError('exactly two worker receipts required')
    for record, mode in zip(records, (0, 2)):
        if type(record.get('optimisation_flag')) is not int or record['optimisation_flag'] != mode:
            raise ValueError('required normal/-OO interpreter modes were not actually executed')
        validate_test_result(record)
        if record['source_identity'] != before or record['source_sha256'] != before_digest:
            raise ValueError('worker source identity differs from parent capture')
        validate_executed(record['executed_source_hashes'], before, require_paths=required_worker_sources())
        validate_derived(record.get('derived_executions'), before, require_names=required_derived_names())
        if record['actual_reference'] is None or not record['cli_readback']:
            raise ValueError('actual connected reference and public CLI readback required')
        validate_reference(record['actual_reference'], before_digest)
        validate_scientific_diagnostics(record)
        for key in ('test_duration_seconds', 'duration_seconds'):
            value = record.get(key)
            if type(value) not in (int, float) or not 0 <= value < float('inf'):
                raise ValueError('finite nonnegative actual timing evidence required')
        if record['duration_seconds'] < record['test_duration_seconds']:
            raise ValueError('complete worker cannot be shorter than its test suite')
        validate_cli_records(record['cli_readback'], mode, before, before_digest, record['actual_reference'], readback=check_cli_artifacts)
    for key in ('test_ids', 'inventory_sha256', 'source_identity', 'source_sha256',
                'executed_source_hashes', 'derived_executions', 'runtime', 'actual_reference', 'reference_sha256'):
        if records[0][key] != records[1][key]:
            raise ValueError('normal/-OO disagreement: ' + key)
    for key in ('coupled_refinement_report', 'coupled_refinement_sha256', 'retained_bridge_result',
                'retained_bridge_sha256', 'scientific_diagnostics_scope'):
        if records[0][key] != records[1][key]:
            raise ValueError('normal/-OO scientific diagnostic disagreement: ' + key)
    if records[0]['reference_sha256'] != sha(json.dumps(records[0]['actual_reference'], sort_keys=True,
                                                       separators=(',', ':'), allow_nan=False).encode()):
        raise ValueError('reference digest differs from actual reference')


def _process(command, record_path, timeout):
    from work.generator_upgrade_r4 import storage
    try:
        result = subprocess.run(command, cwd=TASK, env=child_environment(), capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        def text_value(value):
            return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value
        storage.write_json(record_path, {'status': 'TIMEOUT', 'timeout_seconds': timeout,
                                        'stdout': text_value(error.stdout), 'stderr': text_value(error.stderr)})
        raise RuntimeError('verification subprocess timeout; diagnostics preserved') from error
    storage.write_json(record_path, {'status': 'FINISHED', 'exit_code': result.returncode,
                                    'stdout': result.stdout, 'stderr': result.stderr})
    if result.returncode != 0:
        raise RuntimeError('verification subprocess failed; diagnostics preserved at ' + str(record_path))
    return result


def cli_capture(path, cli_args, expected_source, expected_mode):
    capture = install_fresh_execution()
    from work.generator_upgrade_r4 import cli, storage
    before, digest = source_capture()
    expected = storage.read_json(expected_source)
    if before != expected['source_identity'] or digest != expected['source_sha256'] or sys.flags.optimize != expected_mode:
        raise ValueError('CLI process differs from expected source/mode')
    previous = sys.argv
    try:
        sys.argv = [str(HERE / 'cli.py'), *cli_args]
        cli.main()
    finally:
        sys.argv = previous
    assert_source_stable(before, digest, capture)
    storage.write_json(path, {'status': 'PASS', 'optimisation_flag': sys.flags.optimize,
        'source_sha256': digest, 'source_identity': before, 'executed_source_hashes': capture.executed,
        'derived_executions': capture.derived_executed,
        'arguments': cli_args, 'public_entrypoint': 'work.generator_upgrade_r4.cli.main'})
    capture.active = False
    return 0


def public_cli_reference(root, label, before, digest, reference):
    """Execute the actual public parser in three fresh processes per mode."""
    from work.generator_upgrade_r4 import storage
    ids = {stage: root.name + '-cli-' + label + '-' + stage for stage in ('stop', 'restart', 'full')}
    paths = {stage: storage.OUTPUT_ROOT / identity for stage, identity in ids.items()}
    for path in paths.values():
        storage.plain_path(path)
        if path.exists():
            raise FileExistsError('CLI verification output already exists: ' + str(path))
    flags = ['-OO'] if sys.flags.optimize == 2 else []
    records = []
    for stage in ('stop', 'restart', 'full'):
        arguments = ['--reference', '--run-id', ids[stage]]
        if stage == 'stop':
            arguments += ['--stop-after', '1']
        elif stage == 'restart':
            arguments += ['--resume', str(paths['stop'] / 'checkpoint.json')]
        evidence_path = root / (label + '-cli-' + stage + '.json')
        _process([sys.executable, '-B', *flags, str(HERE / 'verify.py'), '--cli-capture', str(evidence_path),
                  '--expected-source', str(root / 'PARENT_SOURCE.json'), '--expected-mode', str(sys.flags.optimize),
                  '--', *arguments], root / (label + '-cli-' + stage + '-process.json'), CLI_TIMEOUT_SECONDS)
        proof = storage.read_json(evidence_path)
        if (proof['status'] != 'PASS' or proof['optimisation_flag'] != sys.flags.optimize or
                proof['source_identity'] != before or proof['source_sha256'] != digest or proof['arguments'] != arguments):
            raise ValueError('public CLI source/mode/argument evidence differs')
        validate_executed(proof['executed_source_hashes'], before, check_current=True,
                          require_paths=required_cli_sources())
        checked = storage.read_reference(paths[stage])
        if checked['receipt']['evidence']['source_identity'] != before or checked['receipt']['evidence']['source_sha256'] != digest:
            raise ValueError('public artifact belongs to different source capture')
        if stage == 'stop':
            if checked['result.json']['state']['completed_events'] != 1:
                raise ValueError('public stop did not preserve the requested event boundary')
        elif checked['result.json'] != reference:
            raise ValueError('public full/restarted result differs from actual direct reference')
        records.append({'stage': stage, 'run_id': ids[stage], 'path': str(paths[stage]),
                        'receipt_sha256': sha((paths[stage] / 'RECEIPT.json').read_bytes()),
                        'result_sha256': sha((paths[stage] / 'result.json').read_bytes()),
                        'checkpoint_sha256': sha((paths[stage] / 'checkpoint.json').read_bytes()),
                        'execution_receipt_path': str(evidence_path),
                        'execution_receipt_sha256': sha(evidence_path.read_bytes()),
                        'executed_source_hashes': proof['executed_source_hashes'],
                        'derived_executions': proof['derived_executions'],
                        'source_sha256': proof['source_sha256'], 'optimisation_flag': proof['optimisation_flag']})
    restarted = storage.read_reference(paths['restart'])
    full = storage.read_reference(paths['full'])
    if restarted['result.json'] != full['result.json'] or restarted['checkpoint.json'] != full['checkpoint.json']:
        raise ValueError('public full/restart checkpoint or result parity failed')
    return records


def worker(path, expected_source, expected_mode, label):
    worker_start = time.perf_counter()
    capture = install_fresh_execution()
    from work.generator_upgrade_r4 import storage
    before, digest = source_capture()
    parent = storage.read_json(expected_source)
    if before != parent['source_identity'] or digest != parent['source_sha256'] or sys.flags.optimize != expected_mode:
        raise ValueError('worker startup differs from parent source/mode')
    suite, ids = discover()
    inventory_hash = require_inventory(ids)
    stream = io.StringIO()
    start = time.perf_counter()
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=Result).run(suite)
    test_duration = time.perf_counter() - start
    record = {'status': 'PASS' if result.wasSuccessful() else 'FAIL', 'tests': result.testsRun,
        'test_ids': ids, 'inventory_sha256': inventory_hash, 'started': result.started,
        'stopped': result.stopped, 'passed': result.passed, 'failures': len(result.failures),
        'errors': len(result.errors), 'skips': len(result.skipped), 'expected_failures': len(result.expectedFailures),
        'unexpected_successes': len(result.unexpectedSuccesses), 'optimisation_flag': sys.flags.optimize,
        'source_identity': before, 'source_sha256': digest, 'runtime': before['runtime'],
        'actual_reference': None, 'reference_sha256': None, 'cli_readback': [], 'test_log': stream.getvalue(),
        'test_duration_seconds': test_duration}
    try:
        validate_test_result(record)
    except ValueError:
        record['status'] = 'FAIL'
    if record['status'] == 'PASS':
        record.update(collect_scientific_diagnostics())
        from work.generator_upgrade_r4.reference import verification_reference
        record['actual_reference'] = verification_reference()
        validate_reference(record['actual_reference'], digest)
        record['reference_sha256'] = sha(storage.encoded(record['actual_reference']))
        record['cli_readback'] = public_cli_reference(Path(path).parent, label, before, digest, record['actual_reference'])
    assert_source_stable(before, digest, capture)
    record['executed_source_hashes'] = capture.executed
    record['derived_executions'] = capture.derived_executed
    record['duration_seconds'] = time.perf_counter() - worker_start
    record['duration_meaning'] = 'worker startup, source capture, discovery, suite, actual reference, public CLI stop/restart/full and readback through pre-save receipt preparation; not a generation benchmark'
    storage.write_json(path, record)
    capture.active = False
    print(json.dumps({key: record[key] for key in ('status', 'tests', 'failures', 'errors', 'skips', 'optimisation_flag')}, sort_keys=True))
    return 0 if record['status'] == 'PASS' else 1


def inventory_only():
    capture = install_fresh_execution()
    before, digest = source_capture()
    _, ids = discover()
    assert_source_stable(before, digest, capture)
    capture.active = False
    print(json.dumps({'status': 'DISCOVERY_ONLY_NOT_VERIFICATION', 'tests': len(ids),
                      'inventory_sha256': inventory_digest(ids), 'test_ids': ids}, sort_keys=True))
    return 0


def final_verification(run_id):
    if type(run_id) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,47}', run_id):
        raise ValueError('new bounded run ID of at most 48 characters required')
    if EXPECTED_TEST_COUNT is None or INVENTORY_SHA256 is None:
        raise ValueError('reviewed test inventory is PENDING; do not seal before source freeze')
    capture = install_fresh_execution()
    from work.generator_upgrade_r4 import storage
    root = storage.plain_path(storage.OUTPUT_ROOT / run_id)
    if root.exists():
        raise FileExistsError('final verification output already exists: ' + str(root))
    before, digest = source_capture()
    _, ids = discover()
    require_inventory(ids)
    assert_source_stable(before, digest, capture)
    # Reserve all public artifact names before starting expensive verification.
    for label in ('n', 'o'):
        for stage in ('stop', 'restart', 'full'):
            path = storage.plain_path(storage.OUTPUT_ROOT / (run_id + '-cli-' + label + '-' + stage))
            if path.exists():
                raise FileExistsError('reserved public CLI output already exists: ' + str(path))
    root.mkdir(parents=True, exist_ok=False)
    storage.write_json(root / 'PARENT_SOURCE.json', {'source_identity': before, 'source_sha256': digest})
    records = []
    for label, mode, flags in (('n', 0, []), ('o', 2, ['-OO'])):
        path = root / (label + '-worker.json')
        print('Verifying ' + ('normal' if mode == 0 else 'assertions-disabled') + ' source-bound worker', flush=True)
        _process([sys.executable, '-B', *flags, str(HERE / 'verify.py'), '--worker', str(path),
                  '--expected-source', str(root / 'PARENT_SOURCE.json'), '--expected-mode', str(mode), '--label', label],
                 root / (label + '-worker-process.json'), WORKER_TIMEOUT_SECONDS)
        records.append(storage.read_json(path))
    validate_workers(records, before, digest)
    assert_source_stable(before, digest, capture)
    receipt = {'schema': 'diadem.connected-reference-verification.r4', 'status': 'BOUNDED_CONNECTED_REFERENCE_VERIFIED',
        'distinct_named_checks': EXPECTED_TEST_COUNT, 'runs_per_check': 2, 'failures': 0, 'errors': 0, 'skips': 0,
        'expected_failures': 0, 'unexpected_successes': 0, 'test_ids': ids, 'inventory_sha256': INVENTORY_SHA256,
        'source_snapshot': before['r4_sources'], 'source_identity': before, 'source_sha256': digest,
        'executed_source_hashes': records[0]['executed_source_hashes'], 'runtime': before['runtime'],
        'derived_executions': records[0]['derived_executions'],
        'workers': [{'path': str(root / (label + '-worker.json')), 'sha256': sha((root / (label + '-worker.json')).read_bytes()),
                     'test_duration_seconds': record['test_duration_seconds'], 'worker_duration_seconds': record['duration_seconds']}
                    for label, record in zip(('n', 'o'), records)],
        'reference_sha256': records[0]['reference_sha256'], 'public_cli_runs': [r['cli_readback'] for r in records],
        **{key: records[0][key] for key in ('coupled_refinement_report', 'coupled_refinement_sha256',
            'retained_bridge_result', 'retained_bridge_sha256', 'scientific_diagnostics_scope')},
        'protected_previous_source_files': EXPECTED_PROTECTED_COUNT, 'retained_category_contracts': EXPECTED_CATEGORY_CONTRACT_COUNT,
        'retained_r3_source_files': EXPECTED_RETAINED_R3_COUNT,
        'additional_retained_execution_dependencies': EXPECTED_DEPENDENCY_COUNT,
        'prior_tests_rerun_or_recounted': False, 'actual_interpreter_modes': [0, 2],
        'production_installed': False, 'whole_generator_upgraded': False, 'all_categories_physically_accepted': False,
        'new_world_generated': False, 'canon_changed': False, 'generation_speedup_percent': None,
        'scope': 'bounded mechanistic climate/precipitation, three coequal persistent snow members, explicit demand and actual terrain-water-soil coupling; not A/G recomputation, Diadem calibration or world production'}
    storage.write_json(root / 'VERIFICATION.json', receipt)
    if storage.read_json(root / 'VERIFICATION.json') != receipt:
        raise IOError('final verification receipt readback mismatch')
    capture.active = False
    print(json.dumps({key: receipt[key] for key in ('status', 'distinct_named_checks', 'runs_per_check', 'failures', 'errors', 'skips')}, sort_keys=True))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--run-id')
    action.add_argument('--inventory', action='store_true')
    action.add_argument('--worker', type=Path)
    action.add_argument('--cli-capture', type=Path)
    parser.add_argument('--expected-source', type=Path)
    parser.add_argument('--expected-mode', type=int, choices=(0, 2))
    parser.add_argument('--label', choices=('n', 'o'))
    parser.add_argument('cli_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.inventory:
        return inventory_only()
    if args.worker or args.cli_capture:
        if args.expected_source is None or args.expected_mode is None:
            parser.error('child processes require parent source capture and exact mode')
        if args.worker:
            if args.label is None or args.cli_args:
                parser.error('worker requires mode label and no CLI arguments')
            return worker(args.worker, args.expected_source, args.expected_mode, args.label)
        if not args.cli_args or args.cli_args[0] != '--':
            parser.error('public CLI arguments must follow --')
        return cli_capture(args.cli_capture, args.cli_args[1:], args.expected_source, args.expected_mode)
    return final_verification(args.run_id)


def bootstrap_entry():
    # The initially launched script is only a bootstrap. The actual verifier is
    # recompiled from exactly the bytes whose digest it subsequently binds, so
    # there is no unobserved entry-script read/capture window or stale pyc path.
    path = Path(__file__).resolve()
    raw = path.read_bytes()
    namespace = {'__name__': '__verified_entry__', '__file__': str(path)}
    exec(compile(raw, str(path), 'exec', dont_inherit=True), namespace)
    namespace['ENTRY_SOURCE_SHA256'] = sha(raw)
    return namespace['main']()


if __name__ == '__main__':
    raise SystemExit(bootstrap_entry())
