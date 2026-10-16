"""Tiny actual storage/codec migration controls; no historical or IV2 acceptance."""
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE/'compact-geometry-r1'), str(HERE.parent/'runtime-integration-r1/runtime-src')]

import numpy as np
import historical_admission as H
import materialise_endpoint as E
import workflow_transfer as W
import native_transfer as N
import mesh_tables as M
import spatial_workflow_patch as X
import spatial_records_patch as R
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreLimits
from atlas_tectonics.integration_regional_workflow import CollarWorkflow
from compact_restart_store import CompactRestartStore
from compact_contracts import SegmentRef
from content_cache import create_retained_scope
from partition_v2 import PartitionV2
from record_views import RecordRef
from test_partition_tables import tiny_partition
from test_mesh_tables import small_mesh_record


class Step8MaterialiseTests(unittest.TestCase):
    def setUp(self):
        import gc
        gc.disable()
        self.addCleanup(gc.enable)
        self.tmp = tempfile.TemporaryDirectory(prefix='step8-materialise-', dir=HERE.parents[3]/'_t')
        self.path = Path(self.tmp.name)
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='step8-materialise')
        self.original = ArrayStore(self.path/'original.sqlite', StoreLimits(chunk_bytes=65536,
            max_array_bytes=2 << 20, max_store_bytes=32 << 20), budget=self.budget)
        self.working = CompactRestartStore.create_migration(self.path/'catalog.json', workflow_id='a'*64,
            scope=self.scope, producer_identity='b'*64, runtime_identity='c'*64)
        self.producer = {'fixture': 'synthetic conversion only'}
        body, supports = tiny_partition(self.budget, count=2, depth=0)
        self.record = dict(body, partition_id=M.digest(body), supports=supports)
        self.raw = W.canonical(self.record)
        refs = {'partition': dict(array='partition-record:partition', bytes=len(self.raw),
                                 sha256=sha256(self.raw).hexdigest())}
        self.head = dict(key='d'*64, differential_partition=CollarWorkflow._partition_header(self.record, refs))
        self.original.put(self.head['key'], {'partition-record:partition': np.frombuffer(self.raw, dtype='u1'),
            'spatial-record:state': np.frombuffer(W.canonical({'cells': [], 'schema': 'fixture-state'}), dtype='u1'),
            'spatial-record:exchange': np.frombuffer(W.canonical({'graph': [{'q': ['0x1', '0x3']}]*3}), dtype='u1')},
            self.head, budget=self.budget)
        with self.original._read_scope():
            manifest = self.original._manifest(self.head['key'])
        capsule = {'snapshot_manifests': {self.head['key']: manifest}}
        encoded = (W.canonical(capsule), W.canonical({'capsule_sha256': W.digest(capsule)}))
        owner = N._Allocation(self.budget, sum(map(len, encoded))+4096, category='fixture-admission')
        self.admission = object.__new__(W.HistoricalEndpointAdmission)
        object.__setattr__(self.admission, '_record', N._RecordBytes(encoded[0], owner))
        object.__setattr__(self.admission, '_binding', N._RecordBytes(encoded[1], owner))
        object.__setattr__(self.admission, '_source_audit', None)

    def tearDown(self):
        self.admission = None
        self.working.close()
        self.original.close()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())
        self.tmp.cleanup()

    def arguments(self):
        return dict(original_store=self.original, working_store=self.working, admission=self.admission,
            head=self.head, source_producer=self.producer, budget=self.budget, scope=self.scope, check=lambda: None)

    def test_partition_mesh_seal_reopen_and_next_interval_keep_exact_identity(self):
        original_token = self.original.change_token()
        view = E.historical_partition_v2(**self.arguments())
        self.assertIs(type(view), PartitionV2)
        self.assertEqual(view.identity().sha256, sha256(self.raw).hexdigest())
        mesh_record = small_mesh_record(self.budget)
        mesh_record['support_tables']['differential_supports'] = {
            M.digest(row): row for row in self.record['supports']}
        mesh_record['support_ids'] = self.record['support_ids']
        mesh = E.convert_mesh_v3(self.working, mesh_record, expected_geometry_id=M.digest(mesh_record),
            source_producer=self.producer, budget=self.budget, scope=self.scope, partition=view, check=lambda: None)
        mesh_identity, partition_identity = mesh.identity(), view.identity()
        history = E.compact_historical_records(**self.arguments())
        self.assertEqual(set(history['records']), {'spatial-record:state', 'spatial-record:exchange'})
        key = W.digest(W.compact_history_binding(self.head['key'], self.producer))
        self.working.seal_and_promote(key)
        self.assertEqual(mesh.identity(), mesh_identity)
        self.assertEqual(view.identity(), partition_identity)
        next_store = self.working.begin_interval(producer_identity='b'*64, runtime_identity='c'*64)
        self.assertEqual(mesh.cell(0).value['cell_id'], mesh_record['cells'][0]['cell_id'])
        self.assertEqual(view.support_id(0), self.record['support_ids'][0])
        next_store.close()
        mesh.close()
        del mesh
        view.close()
        del view
        with patch.object(H, 'read_selected_arrays', side_effect=AssertionError('legacy payload read forbidden')):
            reopened = E.historical_partition_v2(**self.arguments())
            self.assertEqual(reopened.identity(), partition_identity)
            self.assertEqual(E.compact_historical_records(**self.arguments()), history)
            reopened.close()
            del reopened
        self.assertEqual(self.original.change_token(), original_token)

    def test_foreign_scope_and_missing_readonly_reference_refuse_before_read(self):
        other = WorkBudget(1 << 30)
        foreign = create_retained_scope(other, process_epoch='step8-foreign')
        try:
            with self.assertRaisesRegex(W.WorkflowTransferRefused, 'exact shared retained scope'):
                E.historical_partition_v2(**dict(self.arguments(), scope=foreign))
        finally:
            foreign.close()
        key = 'e'*64
        self.working.put(key, {'empty': np.empty(0, dtype='u1')}, {'fixture': True}, budget=self.budget)
        self.working.seal_and_promote(key)
        with patch.object(H, 'read_selected_arrays', side_effect=AssertionError('legacy read forbidden')):
            with self.assertRaisesRegex(E.EndpointMaterialisationRefused, 'lacks its converted compact partition'):
                E.historical_partition_v2(**self.arguments())
            with self.assertRaisesRegex(E.EndpointMaterialisationRefused, 'lacks its compact historical records'):
                E.compact_historical_records(**self.arguments())

    def test_manifest_reference_checks_do_not_read_record_payloads(self):
        view = E.historical_partition_v2(**self.arguments())
        history = E.compact_historical_records(**self.arguments())
        descriptor = history['records']['spatial-record:state']
        ref = SegmentRef.from_wire(descriptor['compact']['segment'])
        with patch.object(RecordRef, 'export', side_effect=AssertionError('whole export forbidden')):
            R.verify_records(self.working, {'spatial-record:state': descriptor}, budget=self.budget,
                             source_producer=self.producer)
        with patch.object(self.working, 'resolve_chunk', side_effect=AssertionError('payload read forbidden'), create=True):
            R.verify_records(self.working, {'spatial-record:state': descriptor}, budget=self.budget,
                             source_producer=self.producer)
        self.assertEqual(ref.identity.record_schema, R.BUNDLE_SCHEMA)
        view.close()

    def test_geometry_v2_scalar_body_and_ordered_support_checks_release_refs(self):
        import geometry_transfer as G
        import partition_native_patch as PN
        view = E.historical_partition_v2(**self.arguments())
        self.assertTrue(G._sealed_view(view, self.budget))
        self.assertFalse(G._sealed_view(view, WorkBudget(1 << 30)))
        self.assertFalse(G._sealed_view(object(), self.budget))
        self.assertEqual(G._compact_ids(view, ('schema', 'funding_id')),
                         {name: self.record[name] for name in ('schema', 'funding_id')})
        self.assertEqual(G._streamed_body_id(view), self.record['partition_id'])
        G._verify_ordered_supports(view)
        root = view.root()
        try:
            header = PN._view_fields(view, root, G.PARENT_COMPACT_FIELDS)
        finally:
            root.close()
        self.assertEqual(header.value, {name: self.record[name] for name in G.PARENT_COMPACT_FIELDS})
        del header
        view.close()


class LegacyGeometryIsolationTests(unittest.TestCase):
    def test_v1_geometry_helpers_do_not_import_v2(self):
        import builtins
        from types import SimpleNamespace
        import geometry_transfer as G
        from test_partition_tables import opened
        budget = WorkBudget(128 << 20)
        body, supports = tiny_partition(budget, count=1, depth=0)
        view, metadata, arrays = opened(body, supports, budget)
        original_import = builtins.__import__
        def no_v2(name, *args, **kwargs):
            if name in ('partition_v2', 'content_cache'):
                raise AssertionError('legacy geometry imported '+name)
            return original_import(name, *args, **kwargs)
        funding = SimpleNamespace(funding_id=body['funding_id'], _snapshot=SimpleNamespace(
            _metadata=W.canonical({'source': body['source']}), descriptor=lambda: {'source': body['source']}))
        step = {name: body[name] for name in ('end_time_s', 'endpoint_network_id', 'trajectory_id')}
        geometry = SimpleNamespace(interval_id=body['interval_id'], _json=W.canonical(step), record=lambda: step)
        evidence = dict(input=dict(historical_plan_graph=dict(collar=dict(plan_id=body['collar_plan_id']))),
                        current_collar=dict(fields=dict(time_s=1.)))
        with patch.object(builtins, '__import__', no_v2):
            self.assertTrue(G._sealed_view(view, budget))
            self.assertEqual(G._compact_ids(view, G.MATCH_COMPACT_FIELDS),
                             {name: body[name] for name in G.MATCH_COMPACT_FIELDS})
            self.assertEqual(G._streamed_body_id(view), M.digest(body))
            G._verify_ordered_supports(view)
            # 16 Oct: the parent check takes the two transfer scalars, not the record.
            old_plan_id, clock = G._transfer_scalars(evidence)
            self.assertEqual(G._validate_parent_compact(view, geometry, funding, old_plan_id, clock, budget),
                             M.digest(body))
        del view, metadata, arrays
        self.assertEqual(budget.reserved_bytes, 0, budget.statistics())


def step8_live_child(operation, directory, TS, TG):
    """Actual transferred owners; synthetic archive, separately composed runtime.

    Only publication and cold opening are exercised. This fixture conveys no
    historical scientific acceptance or successor interval acceptance.
    """
    from contextlib import ExitStack
    from copy import deepcopy
    import json
    from types import SimpleNamespace
    import time
    import test_partition_workflow_fresh_process as PF
    import spatial_transfer as S
    import historical_compact_heat as HH
    import partition_workflow_patch as PW
    from compact_store import CompactMeshStoreV3
    from atlas_tectonics import integration_sphere as Sphere
    from atlas_tectonics.storage import Compression

    F, SW = PF.F, PF.SW
    started = time.monotonic()
    def phase(name):
        print('STEP8_LIVE_PHASE '+operation+' '+name+' '+format(time.monotonic()-started, '.3f'), flush=True)
    owner, budget = TS.SpatialTransferTests, TS.SpatialTransferTests.budget
    original, catalog = directory/'original.sqlite', directory/'catalog.json'
    limits = StoreLimits(chunk_bytes=1024, max_array_bytes=2 << 20, max_store_bytes=16 << 20,
        max_manifest_bytes=2 << 20, sqlite_cache_bytes=65536, codec_workspace_bytes=65536)
    if operation == 'publish':
        phase('archive-start')
        fixture = TS.SpatialTransferTests('test_old_root_restore_remains_strict')
        fixture.setUp()
        SW.real_mesh(fixture, TS)
        initial = restored = None
        try:
            with S.admit_migrated_spatial_owner(**fixture.args) as lease:
                initial = lease.adopt()
            metadata, arrays = F.archive_operands(fixture, initial, TS, TG)
            native, restored, interval, bridge, partition = F.restore_transfers(metadata, arrays, owner, TS, TG)
            descriptor = PF.native_schema_parent(metadata.pop('partition'), TG.D, budget)
            raw = W.canonical(descriptor)
            partition_refs = {'partition': dict(array='partition-record:partition', bytes=len(raw),
                                                sha256=sha256(raw).hexdigest())}
            current = TG.D.current_geometry_from_interval(interval, budget=budget)
            chain, audit = F.fixture_chain(native.record(), fixture.args, restored, interval,
                SimpleNamespace(partition_id=descriptor['partition_id']), current, TS)
            head = chain[-1]
            head['differential_partition'] = CollarWorkflow._partition_header(descriptor, partition_refs)
            saved = metadata['historical_spatial_record']
            blobs = {kind: W.canonical(value) for kind, value in (
                ('state', {k: v for k, v in saved.items() if k != 'thermal_mesh'}),
                ('mesh', saved['thermal_mesh']))}
            refs = {kind: dict(array='spatial-record:'+kind, bytes=len(value), sha256=sha256(value).hexdigest())
                    for kind, value in blobs.items()}
            head['exterior_state'], _ = CollarWorkflow._spatial_headers(saved, None, refs)
            W.validate_historical_chain(chain)
            metadata['chain_keys'] = [row['key'] for row in chain]
            arrays.update({'audit:'+k: audit.array(k) for k in audit.array_names})
            with ArrayStore(original, limits, budget=budget) as archive:
                archive.put(F.ARCHIVE_KEY, arrays, metadata, budget=budget)
                for row in chain:
                    payload = {'fixture': np.array([1], dtype='u1')}
                    if row is head:
                        payload.update({'spatial-record:'+k: np.frombuffer(v, dtype='u1') for k, v in blobs.items()})
                        payload['partition-record:partition'] = np.frombuffer(raw, dtype='u1')
                    archive.put(row['key'], payload, row, budget=budget)
            del metadata, arrays, native, interval, bridge, partition, descriptor, raw, current, chain, audit
            del payload, head, saved, blobs, refs, partition_refs, row
        finally:
            for transferred in (initial, restored):
                if transferred is not None:
                    transferred.owner.close()
            fixture.args = fixture.native_owned = None
        del fixture, initial, restored, transferred, lease
        phase('archive-complete')

    phase('stores-open')
    original_sha = F.file_hash(original)
    scope = create_retained_scope(budget, process_epoch='step8-live-'+operation)
    store = (CompactRestartStore.create_migration(catalog, workflow_id='f'*64, scope=scope,
        producer_identity='b'*64, runtime_identity='c'*64) if operation == 'publish' else
        CompactRestartStore.open_catalog(catalog, scope=scope))
    source = H.open_successor_readonly(original, expected_sha256=original_sha, limits=limits,
                                      compression=Compression(), budget=budget)
    spatial = workflow = mesh = view = None
    try:
        with source as original_store, ExitStack() as guards:
            if operation == 'reopen':
                for module, name in ((H, 'read_selected_arrays'), (E, 'partition_record'),
                                     (E, 'convert_mesh_v3')):
                    guards.enter_context(patch.object(module, name, side_effect=AssertionError('cold conversion '+name)))
            token = store.change_token()
            metadata = original_store.metadata(F.ARCHIVE_KEY)
            arrays = original_store.get(F.ARCHIVE_KEY, budget=budget)
            def fields(prefix, values=arrays):
                return {k.removeprefix(prefix): v for k, v in values.items() if k.startswith(prefix)}
            incoming = metadata['native_input']
            with N.admit_migrated_native_collar(native=owner.native, collar=owner.collar,
                    historical_graph=incoming['historical_plan_graph'], historical_native=incoming['historical_native'],
                    historical_native_id=incoming['historical_native_id'], native_arrays=fields('native:'),
                    historical_collar=incoming['historical_collar'], collar_arrays=fields('collar:'),
                    origin=incoming['origin']) as lease:
                native = lease.adopt()
            phase('native-owner-restored')
            chain = [original_store.metadata(key) for key in metadata['chain_keys']]
            head = chain[-1]
            with original_store._read_scope():
                manifests = {key: deepcopy(original_store._manifest(key)) for key in [F.ARCHIVE_KEY, *metadata['chain_keys']]}
            audit = TS.Snapshot(head['source_audit'], fields('audit:'))
            capsule = dict(schema='atlas.restart-historical-endpoint.v1', authority=F.FIXTURE_ONLY,
                chain_metadata=chain, snapshot_manifests=manifests,
                source=dict(root_key=chain[0]['key'], head_key=head['key'], workflow_id=chain[0]['workflow_id'],
                    sequence=3, time_s=12.5, store_token=dict(fixture=F.FIXTURE_ONLY), database_sha256=original_sha),
                producer=dict(execution_identity='a'*64, source_manifest_sha256='b'*64))
            historical, compatibility = F.fixture_admissions(capsule, incoming['origin'], audit,
                                                             original, native.record(), budget)
            producer = X.producer(owner.collar)
            common = dict(original_store=original_store, working_store=store, admission=historical,
                head=head, budget=budget, scope=scope, check=lambda: None)
            phase('partition-start')
            view = E.historical_partition_v2(**common, source_producer=producer)
            phase('partition-complete')
            saved = metadata['historical_spatial_record']
            reference = X.existing_mesh(store, saved['thermal_mesh_id'], producer, budget=budget)
            phase('mesh-start')
            if reference is None:
                mesh = E.convert_mesh_v3(store, saved['thermal_mesh'], expected_geometry_id=saved['thermal_mesh_id'],
                    source_producer=producer, budget=budget, scope=scope, partition=view, check=lambda: None)
            else:
                mesh = CompactMeshStoreV3(store, scope=scope).open(SegmentRef.from_wire(reference['segment']),
                    expected_geometry_id=saved['thermal_mesh_id'])
            phase('mesh-complete')
            with S.admit_migrated_spatial_owner(collar=owner.collar, native_transfer=native,
                    funding_record=metadata['funding_record'], funding_arrays=fields('funding:'),
                    historical_owner_definition=metadata['historical_owner_definition'],
                    historical_spatial_record=dict(saved, thermal_mesh=mesh), spatial_arrays=fields('spatial:'),
                    funding_binding=metadata['funding_binding'], origin=incoming['origin']) as lease:
                spatial = lease.adopt()
            assert spatial.owner._budget is budget
            spatial.owner._record_scope = scope
            phase('spatial-owner-restored')
            network = Sphere.restore_network(metadata['endpoint_network'], fields('network:'), budget=budget)
            interval = TG.D._issue(TG.D.DifferentialInterval, metadata['interval'], budget, network)
            phase('geometry-bridge-start')
            bridge, partition = E.compact_parent_partition(**common, native_transfer=native, interval=interval,
                funding=spatial.funding, collar=owner.collar, compact_partition=view)
            phase('geometry-bridge-complete')
            phase('history-records-start')
            history = E.compact_historical_records(**common, source_producer=producer)
            phase('history-heat-start')
            heat = HH.migrate_heat_history(original_store, store, historical,
                                           source_producer=producer, budget=budget, check=lambda: None)
            phase('base-bind-start')
            base = W.bind_migrated_base(native_transfer=native, spatial_transfer=spatial, geometry_transfer=bridge,
                interval=interval, partition=partition, historical_admission=historical,
                runtime_admission=compatibility, budget=budget, original_store=original_store)
            phase('base-bind-complete')
            if operation == 'publish':
                import run_prepared_restart as RUN
                workflow = guards.enter_context(RUN.publish_and_reopen(store, base, budget=budget,
                    check=lambda: None, phase=phase, prepare_next=True,
                    producer_identity='b'*64, runtime_identity='c'*64))
                assert mesh.identity().sha256 == saved['thermal_mesh_id']
                assert view.support_id(0) == partition.supports.view.support_id(0)
            else:
                phase('readonly-root-open-start')
                with W.migrated_root_payload(base, store=store) as (expected, payload):
                    identity = expected['workflow_id']
                    del payload
                workflow = CollarWorkflow.open_migrated(store, identity, base, budget=budget)
                assert token == store.change_token(), 'cold opening changed the catalog'
            phase('root-open-complete')
            assert base.original_store is original_store
            assert W.compact_references_verified(store, workflow._head, budget=budget)
            W.verify_migrated_workflow(workflow)
            phase('root-verification-complete')
            def bindings(values):
                return {k: dict(dtype=v.dtype.str, shape=list(v.shape), sha256=sha256(memoryview(v).cast('B')).hexdigest())
                        for k, v in values.items()}
            result = dict(root=deepcopy(workflow._head), base=base.record(), transfer=bridge.record(),
                partition_id=partition.partition_id, header=PW.compact_header(view, head['differential_partition']['record_blobs']),
                descriptor_stats=PW.descriptor_stats(view), compact_history=history, compact_heat_history=heat,
                support_ids=[view.support_id(i) for i in range(view.support_count)],
                funding=workflow._funding.descriptor(), native_collar_record=workflow._state.record(),
                native_collar_fields=bindings(workflow._state.arrays()), spatial=SW.logical_summary(workflow._exterior_state),
                spatial_fields=bindings(workflow._exterior_state.arrays()), source_audit_id=workflow._source_audit.result_id,
                interval=workflow._differential_interval.descriptor(), original_database_sha256=original_sha,
                execution=owner.native._context.provenance, native_accepted_intervals=0)
            assert owner.native.statistics()['accepted_intervals'] == 0
            phase('owner-cleanup-start')
            guards.close()
            workflow.close()
            workflow = None
            spatial.owner.close()
            spatial = None
            del partition, bridge, base, native, interval, arrays, audit, historical, compatibility
            del network, common, lease, fields
            mesh.close()
            mesh = None
            view.close()
            view = None
            phase('owner-cleanup-complete')
        assert F.file_hash(original) == original_sha, 'original fixture changed'
        return json.loads(json.dumps(result))
    finally:
        phase('store-scope-cleanup-start')
        failed = sys.exc_info()[0] is not None
        if workflow is not None:
            workflow.close()
        if spatial is not None:
            spatial.owner.close()
        # Escaped validation frames own their mesh/partition borrows and charges.
        # Do not mask the actual error by force-closing those live views.
        if mesh is not None and not failed:
            mesh.close()
        if view is not None and not failed:
            view.close()
        store.close()
        if not failed:
            scope.close()
        phase('store-scope-cleanup-complete')


if __name__ == '__main__':
    unittest.main(verbosity=2)
