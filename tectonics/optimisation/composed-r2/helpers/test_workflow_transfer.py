"""Small structural/CAS/control-flow checks, never fabricated science acceptance."""
import ast
from copy import deepcopy
import gc
import importlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

import workflow_transfer as W

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent/'runtime-integration-r1'
PACKAGE = RUNTIME/'runtime-src'/'atlas_tectonics'
HEAT = HERE.parents[2]/'heat-repair-20261007'
sys.path[:0] = [str(RUNTIME/'runtime-src'), str(RUNTIME/'ram'), str(RUNTIME/'helpers'),
               str(HEAT), str(HEAT/'source/tectonics/tests')]
_temporary = None


def setUpModule():
    """Compose the exact additive seams before any actual runtime import."""
    global _temporary
    import native_transfer as N
    import spatial_transfer as S
    import geometry_transfer as G
    if any(k == 'atlas_tectonics' or k.startswith('atlas_tectonics.') for k in sys.modules):
        raise RuntimeError('clean process required; no loaded runtime replacement')
    _temporary = tempfile.TemporaryDirectory(prefix='workflow-transfer-runtime-', dir=HERE)
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(PACKAGE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name, transform in (('regional_execution.py', N.retained_snapshot_source),
            ('integration_spatial_owner.py', S.spatial_owner_source),
            ('integration_differential_geometry.py', G.transform),
            ('integration_regional_workflow.py', W.nonzero_cursor_source),
            ('integration_private_heat_cold.py', W.private_heat_cold_source)):
        path = package/name
        path.write_text(transform(path.read_text(encoding='utf8')), encoding='utf8')
    sys.path.insert(0, _temporary.name)


def tearDownModule():
    if _temporary is not None:
        sys.path.remove(_temporary.name)
        _temporary.cleanup()


def fixtures():
    ident, funding = 'a'*64, 'f'*64
    initial = dict(result_id='b'*64, fields=dict(time_s=0., parent_id=None),
                   native=dict(time_s=0., parent_state_id=None))
    root = dict(schema=W.WORKFLOW_SCHEMA, kind='root', sequence=0, workflow_id=ident,
        key=W.workflow_key('root', ident), funding_id=funding, funding={'funding_id': funding},
        state=initial, native_state_id='c'*64,
        exterior_state=dict(state_id='d'*64, intervals=0, time_s=0.))
    old_native = dict(time_s=2.5, parent_state_id=root['native_state_id'], plan_id='1'*64)
    state = dict(result_id='e'*64,
        fields=dict(time_s=2.5, parent_id=initial['result_id'], plan_id='2'*64), native=old_native)
    head = dict(schema=W.WORKFLOW_SCHEMA, kind='successor', sequence=1, workflow_id=ident,
        key=W.workflow_key('successor', root['key']), parent_key=root['key'], parent_digest=W.digest(root),
        funding_id=funding, state=state, native_state_id='3'*64,
        advance=dict(duration_s=2.5, source_audit_id='4'*64),
        source_audit=dict(parent_state_id=root['native_state_id'], start_time_s=0., duration_s=2.5),
        exterior_state=dict(state_id='5'*64, parent_state_id=root['exterior_state']['state_id'],
                            time_s=2.5, intervals=1, collar_state_id=state['result_id']),
        exterior_advance=dict(state_id='5'*64), differential_geometry=dict(interval_id='6'*64),
        differential_partition=dict(partition_id='7'*64),
        differential_certification=dict(endpoint_current_geometry_id='8'*64))
    current_native = dict(old_native, parent_state_id=head['native_state_id'], plan_id='9'*64)
    current_state = dict(result_id='0'*64, native=current_native,
        fields=dict(time_s=2.5, parent_id=state['result_id'], plan_id='a'*64))
    graph = dict(native=dict(plan_id='9'*64, definition=dict(execution='b'*64)),
                 collar=dict(plan_id='a'*64, definition={}))
    transfer = dict(schema='atlas.native-collar-migrated-state.v1', input=dict(historical_collar=state,
        historical_native=old_native, historical_native_id=head['native_state_id'], current_plan_graph=graph),
        current_collar=current_state, current_native=current_native, current_native_id='c'*64,
        elapsed_time_s=0, funding_debit_applied=False, scientific_acceptance=False, continuation_authorised=False)
    manifest = dict(schema='fixture-only', invocation=head['key'], metadata=head,
        arrays={'component_mass_kg': dict(dtype='<f8', shape=[1], chunks=['d'*64])})
    return [root, head], transfer, manifest


def descriptor(chain=None, transfer=None, manifest=None):
    defaults = fixtures()
    return W.describe_migrated_root(chain=defaults[0] if chain is None else chain,
        native_transfer_record=defaults[1] if transfer is None else transfer,
        source_head_manifest=defaults[2] if manifest is None else manifest,
        source_store_token=(1, 2), historical_validation_sha256='e'*64,
        current_execution=dict(execution_identity='b'*64, execution_mode='strict'))


class ContractTests(unittest.TestCase):
    def test_nonzero_descriptor_keeps_full_inventory_and_original_chain(self):
        chain, transfer, manifest = fixtures()
        manifest['arrays']['all_history_fields'] = dict(dtype='|u1', shape=[1], chunks=['f'*64])
        result = descriptor(chain, transfer, manifest)
        self.assertEqual(result['sequence'], 1)
        self.assertEqual(result['time_s'], 2.5)
        self.assertEqual(result['predecessor']['head_manifest'], manifest)
        self.assertEqual(len(result['predecessor']['chain']), 2)
        self.assertFalse(result['may_open'])
        self.assertFalse(result['may_advance'])
        self.assertFalse(result['scientific_acceptance'])
        manifest['arrays'].clear()
        self.assertEqual(len(result['predecessor']['head_manifest']['arrays']), 2)

    def test_chain_gaps_wrong_parent_clock_and_funding_refuse(self):
        for mutate in (lambda h: h.update(sequence=2), lambda h: h.update(parent_digest='0'*64),
                       lambda h: h.update(funding_id='0'*64),
                       lambda h: h['state']['fields'].update(time_s=0.),
                       lambda h: h['exterior_state'].update(intervals=0)):
            chain = fixtures()[0]
            mutate(chain[-1])
            with self.assertRaises(W.WorkflowTransferRefused):
                W.validate_historical_chain(chain)
        with self.assertRaises(W.WorkflowTransferRefused):
            W.validate_historical_chain(fixtures()[0][1:])

    def test_native_reinitialisation_funding_and_runtime_refuse(self):
        for mutate in (lambda t: t.update(funding_debit_applied=True),
                       lambda t: t.update(elapsed_time_s=1),
                       lambda t: t['current_collar']['fields'].update(time_s=0),
                       lambda t: t['input']['current_plan_graph']['native']['definition'].update(execution='0'*64)):
            transfer = fixtures()[1]
            mutate(transfer)
            with self.assertRaises(W.WorkflowTransferRefused):
                descriptor(transfer=transfer)

    def test_no_caller_issued_authentication_or_runtime_compatibility(self):
        for cls in (W.HistoricalEndpointAdmission, W.RuntimeCompatibilityAdmission, W.MigratedWorkflowBase):
            with self.assertRaises(TypeError):
                cls({'accepted': True})
        with self.assertRaises(W.WorkflowTransferRefused):
            W.open_migrated_root(object, None, 'a'*64, descriptor(), budget=None)

    def test_absolute_interval_limit_not_reset(self):
        self.assertEqual(next(iter(W.successor_sequence_range(1))), 2)
        self.assertEqual(list(W.successor_sequence_range(256)), [257])
        for invalid in (True, -1, 257, 1.):
            with self.assertRaises(W.WorkflowTransferRefused):
                W.successor_sequence_range(invalid)

    def test_exact_source_patch_compiles_and_ordinary_create_open_unchanged(self):
        source = (PACKAGE/'integration_regional_workflow.py').read_text(encoding='utf8')
        candidate = W.nonzero_cursor_source(source)
        compile(candidate, '<candidate>', 'exec')
        classes = []
        for text in (source, candidate):
            tree = ast.parse(text)
            cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'CollarWorkflow')
            classes.append({node.name: ast.dump(node) for node in cls.body if isinstance(node, ast.FunctionDef)})
        for name in ('create', 'open', '_publish', '_saved_certification_expected', 'advance_spatial'):
            self.assertEqual(classes[0][name], classes[1][name])
        self.assertIn('open_migrated', classes[1])
        with self.assertRaises(W.WorkflowTransferRefused):
            W.nonzero_cursor_source(candidate)
        cold = (PACKAGE/'integration_private_heat_cold.py').read_text(encoding='utf8')
        updated = W.private_heat_cold_source(cold)
        compile(updated, '<cold-candidate>', 'exec')
        self.assertEqual(updated.count("('root', 'successor', 'migrated-root')"), 1)
        with self.assertRaises(W.WorkflowTransferRefused):
            W.private_heat_cold_source(updated)

    def test_actual_refresh_branch_routes_base_only_and_keeps_new_successor_checks(self):
        # Compile the ACTUAL changed method; stubs test only cursor/control flow,
        # never act as an issued physical object or historical science permit.
        source = W.nonzero_cursor_source((PACKAGE/'integration_regional_workflow.py').read_text(encoding='utf8'))
        cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'CollarWorkflow')
        function = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_refresh')
        module = ast.Module(body=[function], type_ignores=[])
        ast.fix_missing_locations(module)
        namespace = dict(json=json, RegionalOwnerRefused=W.WorkflowTransferRefused,
                         MAX_INTERVALS=256, _hash=W.digest)
        exec(compile(module, '<refresh-control>', 'exec'), namespace)
        root = dict(key='a'*64, kind='migrated-root', sequence=7, migration={'sequence': 7})
        records = {root['key']: root}
        state = SimpleNamespace(_root=json.dumps(root), _token=None, _verify=lambda: None,
            _is_differential=lambda: False, _migration=SimpleNamespace(record=lambda: {'sequence': 7}),
            _key=lambda kind, key: kind+key, _store=SimpleNamespace(change_token=lambda: (1, 2),
                metadata=lambda key: records.get(key)))
        with patch.object(W, 'verify_migrated_workflow') as verify, patch.object(W, 'restore_migrated_root') as restore:
            namespace['_refresh'](state)
            verify.assert_called_once_with(state)
            restore.assert_called_once_with(state, root, (1, 2))
            records['successor'+root['key']] = {'kind': 'successor', 'sequence': 8}
            state._exterior_owner = None
            with self.assertRaises(W.WorkflowTransferRefused):
                namespace['_refresh'](state)
            self.assertEqual(restore.call_count, 1)


class StoreFenceTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from atlas_tectonics.resources import WorkBudget
        from atlas_tectonics.storage import ArrayStore, StoreLimits
        self.directory = tempfile.TemporaryDirectory(prefix='.workflow-transfer-', dir=HERE.parents[3])
        self.budget = WorkBudget(32 << 20)
        self.store = ArrayStore(Path(self.directory.name)/'tiny.sqlite',
            StoreLimits(chunk_bytes=128, max_array_bytes=1 << 20, max_store_bytes=8 << 20,
                        max_manifest_bytes=65536, sqlite_cache_bytes=65536, codec_workspace_bytes=65536),
            budget=self.budget)
        self.array = {'fixture': np.array([1], dtype=np.uint8)}
        self.chain, transfer, _ = fixtures()
        for row in self.chain:
            self.store.put(row['key'], self.array, row, budget=self.budget)
        with self.store._read_scope():
            manifest = deepcopy(self.store._manifest(self.chain[-1]['key']))
        self.descriptor = descriptor(self.chain, transfer, manifest)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_fence_only_inside_actual_atomic_publication(self):
        fence = W.chain_publication_fence(self.store, self.descriptor)
        with self.assertRaises(W.WorkflowTransferRefused):
            fence()
        # Tiny arbitrary snapshot, not a migrated scientific root.
        self.store.put('0'*64, self.array, {'fixture': True}, publication_check=fence, budget=self.budget)
        self.assertTrue(self.store.contains('0'*64))

    def test_changed_source_head_fails_and_rolls_back(self):
        from atlas_tectonics.storage import StoreConflict
        fence = W.chain_publication_fence(self.store, self.descriptor)
        next_key = W.workflow_key('successor', self.chain[-1]['key'])
        self.store.put(next_key, self.array, {'fixture': 'advanced original head'}, budget=self.budget)
        with self.assertRaises(StoreConflict):
            self.store.put('0'*64, self.array, {'fixture': True}, publication_check=fence, budget=self.budget)
        self.assertFalse(self.store.contains('0'*64))


class TypedRootTests(unittest.TestCase):
    """Real object/persistence mechanics, explicitly NOT science admission.

    Existing native/spatial archive fixtures and the geometry agent's synthetic
    archive are reused. No force, transport, heat or geometric solve occurs.
    The two admission objects are TEST-ONLY issued evidence; production adapters
    must authenticate originals and explicitly review runtime compatibility.
    """
    @classmethod
    def setUpClass(cls):
        import test_spatial_transfer as TS
        import test_geometry_transfer_integration as TG
        TS.F = importlib.import_module('test_i04_regional_owner')
        TS.C = importlib.import_module('atlas_tectonics.regional_collar3d')
        TS.P = importlib.import_module('atlas_tectonics.integration_spatial_owner')
        TS.Snapshot = importlib.import_module('atlas_tectonics.regional_execution').RegionalMechanicalSnapshot
        TS.WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget
        TS.Registry = importlib.import_module('atlas_tectonics.integration_regional_inventory').ComponentRegistry
        TS.enc = importlib.import_module('atlas_tectonics.integration_mimetic_heat')._enc
        TS.TectonicsError = importlib.import_module('atlas_tectonics._validation').TectonicsError
        TG.D = importlib.import_module('atlas_tectonics.integration_differential_geometry')
        TS.SpatialTransferTests.setUpClass()
        cls.budget = TS.SpatialTransferTests.budget

    @classmethod
    def tearDownClass(cls):
        import test_spatial_transfer as TS
        TS.SpatialTransferTests.tearDownClass()
        TS.SpatialTransferTests.collar = TS.SpatialTransferTests.native = None
        TS.SpatialTransferTests.old = TS.SpatialTransferTests.current = None
        gc.collect()
        if cls.budget.reserved_bytes:
            raise AssertionError(cls.budget.statistics())

    def test_actual_publish_reopen_accounts_no_initialisation_and_original_guard(self):
        import numpy as np
        import spatial_transfer as S
        import geometry_transfer as G
        import test_spatial_transfer as TS
        import test_geometry_transfer_integration as TG
        from atlas_tectonics.integration_regional_workflow import CollarWorkflow
        from atlas_tectonics.storage import ArrayStore, StoreLimits
        fixture = TS.SpatialTransferTests('test_old_root_restore_remains_strict')
        fixture.setUp()
        spatial = None
        try:
            with S.admit_migrated_spatial_owner(**fixture.args) as lease:
                spatial = lease.adopt()
            interval, partition_record = TG.synthetic_geometry_and_partition(
                spatial=spatial, collar=fixture.collar, native_transfer=fixture.native_owned, budget=self.budget)
            # Complete the synthetic geometry shape used by the actual endpoint
            # derivation. Its explicit fixture disclaimer is retained verbatim.
            row = dict(interval.record(), duration_s=TS.enc(4.5), start_time_s=TS.enc(8),
                rays={}, boundary_paths=[], plate_angular_velocity_rad_s={}, ownership_fans=[],
                radius_m=TS.enc(10), trajectory=spatial.state.record()['trajectory'])
            interval = TG.D._issue(TG.D.DifferentialInterval, row, self.budget, fixture.source[0].network)
            partition_record.update(interval_id=interval.interval_id, start_time_s=row['start_time_s'])
            TG.rehash_partition(partition_record)
            bridge = G.bind_parent_geometry(native_transfer=fixture.native_owned,
                partition_descriptor=partition_record, geometry=interval, funding=spatial.funding,
                collar=fixture.collar, budget=self.budget)
            partition = TG.D.DifferentialPartition.restore(partition_record, spatial.funding,
                fixture.collar, interval, budget=self.budget, _runtime_transfer=bridge)
            current = TG.D.current_geometry_from_interval(interval, budget=self.budget)
            native = fixture.native_owned.record()
            old = native['input']['historical_collar']
            ident = '1'*64
            root = dict(schema=W.WORKFLOW_SCHEMA, kind='root', sequence=0, workflow_id=ident,
                key=W.workflow_key('root', ident), funding_id=spatial.funding.funding_id,
                funding=spatial.funding.descriptor(), exterior_remainder=spatial.funding.exterior_remainder(),
                state=dict(result_id='2'*64, fields=dict(time_s=0.), native={}),
                native_state_id='3'*64, exterior_state=dict(state_id='4'*64))
            chain = [root]
            for sequence, end in ((1, 4.), (2, 8.), (3, 12.5)):
                previous = chain[-1]
                last = sequence == 3
                state = old if last else dict(result_id=('c' if sequence == 2 else '5')*64,
                    fields=dict(time_s=end, parent_id=previous['state']['result_id']),
                    native=dict(parent_state_id=previous['native_state_id']))
                audit_metadata = dict(schema='fixture.synthetic-source-audit.v1',
                    parent_state_id=previous['native_state_id'], start_time_s=previous['state']['fields']['time_s'],
                    duration_s=end-previous['state']['fields']['time_s'])
                audit = TS.Snapshot(audit_metadata, {'fixture': np.array([sequence], dtype=np.uint8)})
                exterior = (fixture.args['historical_spatial_record'] if last else
                    dict(state_id=('9' if sequence == 2 else '6')*64,
                        parent_state_id=previous['exterior_state']['state_id'], intervals=sequence,
                        time_s=end, collar_state_id=state['result_id']))
                head = dict(schema=W.WORKFLOW_SCHEMA, kind='successor', sequence=sequence,
                    workflow_id=ident, key=W.workflow_key('successor', previous['key']),
                    parent_key=previous['key'], parent_digest=W.digest(previous), funding_id=root['funding_id'],
                    state=state, native_state_id=native['input']['historical_native_id'] if last else ('b' if sequence == 2 else '7')*64,
                    advance=dict(duration_s=audit_metadata['duration_s'], source_audit_id=audit.result_id),
                    source_audit=audit.descriptor(), exterior_state=exterior,
                    exterior_advance=dict(fixture='SYNTHETIC, NOT ACCEPTANCE'),
                    differential_geometry=dict(interval_id=interval.interval_id),
                    differential_partition=dict(partition_id=partition.partition_id),
                    differential_certification=dict(endpoint_current_geometry_id=current.geometry_id))
                chain.append(head)
            W.validate_historical_chain(chain)
            with tempfile.TemporaryDirectory(prefix='workflow-roundtrip-', dir=HERE) as directory:
                limits = StoreLimits(chunk_bytes=1024, max_array_bytes=2 << 20, max_store_bytes=8 << 20,
                    max_manifest_bytes=1 << 20, sqlite_cache_bytes=65536, codec_workspace_bytes=65536)
                with ArrayStore(Path(directory)/'copy.sqlite', limits, budget=self.budget) as store:
                    for row in chain:
                        store.put(row['key'], {'fixture': np.array([1], dtype=np.uint8)}, row, budget=self.budget)
                    with store._read_scope():
                        manifests = {row['key']: deepcopy(store._manifest(row['key'])) for row in chain}
                    capsule = dict(schema='atlas.restart-historical-endpoint.v1',
                        authority='SYNTHETIC TEST ONLY; NO SCIENTIFIC ACCEPTANCE', chain_metadata=chain,
                        snapshot_manifests=manifests,
                        source=dict(root_key=root['key'], head_key=head['key'], workflow_id=ident,
                            sequence=3, time_s=12.5, store_token=list(store.change_token())),
                        producer=dict(execution_identity='a'*64, source_manifest_sha256='b'*64))
                    binding = dict(capsule_sha256=W.digest(capsule), origin=native['input']['origin'],
                        original_database_path=str(Path(directory)/'original.sqlite'),
                        fixture='TEST ONLY, NOT AN AUTHENTICATED READER')
                    historical = object.__new__(W.HistoricalEndpointAdmission)
                    for name, value in dict(_record=W.canonical(capsule), _binding=W.canonical(binding),
                            _source_audit=audit).items():
                        object.__setattr__(historical, name, value)
                    runtime = object.__new__(W.RuntimeCompatibilityAdmission)
                    object.__setattr__(runtime, '_record', W.canonical(dict(
                        schema='atlas.restart-runtime-compatibility.v1', historical_execution_identity='a'*64,
                        current_execution_identity=native['input']['current_plan_graph']['native']['definition']['execution'],
                        scientific_contract_id=native['input']['compatibility']['scientific_contract_id'],
                        historical_source_manifest_sha256='b'*64, current_source_manifest_sha256='c'*64,
                        validation_evidence=['SYNTHETIC TEST ONLY; NOT RUNTIME SCIENCE COMPATIBILITY'])))
                    base = W.bind_migrated_base(native_transfer=fixture.native_owned, spatial_transfer=spatial,
                        geometry_transfer=bridge, interval=interval, partition=partition,
                        historical_admission=historical, runtime_admission=runtime, budget=self.budget)
                    before_native = fixture.collar._native.statistics()['accepted_intervals']
                    # Do not monkeypatch protected native methods: the actual
                    # ExecutionContext correctly rejects any changed callable.
                    # Verify the no-initialisation call graph structurally and
                    # preserve exact evolved IDs/accounts in the real roundtrip.
                    tree = ast.parse(Path(W.__file__).read_text(encoding='utf8'))
                    forbidden = {'initial_state', 'initial_state_from_funding', 'fund'}
                    self.assertFalse(any(isinstance(node, ast.Call) and
                        isinstance(node.func, ast.Attribute) and node.func.attr in forbidden
                        for node in ast.walk(tree)))
                    workflow = W.publish_migrated_root(store, base, budget=self.budget)
                    self.assertIs(type(workflow), CollarWorkflow)
                    self.assertEqual(workflow._head['sequence'], 3)
                    self.assertEqual(workflow._state.record()['fields']['time_s'], 12.5)
                    self.assertIs(workflow._funding, spatial.funding)
                    self.assertEqual(workflow._exterior_state.record(), spatial.state.record())
                    self.assertIs(workflow._differential_partition, partition)
                    self.assertIs(workflow._source_audit, audit)
                    workflow_id = workflow._head['workflow_id']
                    workflow.close()
                    reopened = CollarWorkflow.open_migrated(store, workflow_id, base, budget=self.budget)
                    self.assertEqual(reopened._head['sequence'], 3)
                    self.assertEqual(reopened._state.record(), fixture.native_owned.state.record())
                    reopened.close()
                    self.assertEqual(fixture.collar._native.statistics()['accepted_intervals'], before_native)
                    self.assertEqual([store.metadata(r['key']) for r in chain], chain)
                    # Same actual base, deliberately swapped destination identity
                    # in TEST admission: writer must refuse original path first.
                    original_endpoint = base._endpoint
                    object.__setattr__(base, '_endpoint', W.canonical(dict(json.loads(base._endpoint),
                        original_database_path=str(store.path))))
                    try:
                        with self.assertRaisesRegex(W.WorkflowTransferRefused, 'original database'):
                            W.publish_migrated_root(store, base, budget=self.budget)
                    finally:
                        object.__setattr__(base, '_endpoint', original_endpoint)
                    del workflow, reopened, base, historical, runtime, capsule, binding, manifests, original_endpoint
            del current, bridge, partition, interval, audit, native, old, chain, root, head, row, state, exterior
        finally:
            if spatial is not None:
                spatial.owner.close()
            spatial = None
            gc.collect()
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
