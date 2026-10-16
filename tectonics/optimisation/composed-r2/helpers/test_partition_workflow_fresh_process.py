"""Two processes: compact historical partition, migrated root publication, cold reopen.

Process A converts the archived native-schema parent once into its working
copy through materialise_endpoint.compact_parent_partition, binds the compact
geometry transfer and base, and publishes the migrated root with a top-level
compact_partition reference plus 'partition-dag:' aliases. Process B copies that
store to another path, opens the copy read-only (mode=ro, query_only) as the
independent reader does, re-materialises the parent without reading, decoding or
packing any partition JSON, and cold-opens the root. SYNTHETIC FIXTURE EVIDENCE
ONLY: persistence/ownership verification, not historical or scientific
acceptance. Sources are composed once: the compact-spatial tree of
test_spatial_workflow_patch, the geometry chain partition_native_patch ->
endpoint seam (staged) -> geometry_transfer(compact=True) and the workflow chain
nonzero cursor -> spatial -> partition_workflow_transform, at their pinned digests.
"""
from contextlib import ExitStack
from copy import deepcopy
import gc
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_spatial_workflow_patch as SW

F = SW.F
R = HERE.parent
HEADER = ('source', 'funding_id', 'collar_plan_id', 'interval_id', 'parent_network_id',
          'endpoint_network_id', 'trajectory_id', 'start_time_s', 'end_time_s')
# w1a stage digests (string bytes) of the reviewed geometry chain.
PARTITION_READER_SHA256 = '29443f86c8dce100af71072426f9848a5cc7ed4f20cbbb323d98a6ec0c725924'
ENDPOINT_READER_SHA256 = '213d1ebb5ef4d072f65ae3c08b99a4537f61985e46fe802e54c58a1b6ac471fd'
GEOMETRY_COMPACT_SHA256 = 'fc9dd85e002fe54db6e409ebe89083996f62611c40d958a5a1e60184f3424253'
PARTITION_HELPERS = ('partition_tables.py', 'partition_native_patch.py', 'partition_store.py',
                     'partition_workflow_patch.py', 'test_partition_tables.py')
PHASES = {'publish': ['convert-historical-partition', 'publish-compact-partition'], 'reopen': []}


def _digest(text):
    return sha256(text.encode('utf8')).hexdigest()


def staged_seam(text, staging):
    """The endpoint seam reads package files: stage this text beside the frozen batch."""
    spec = importlib.util.spec_from_file_location('w2b_patch_endpoint_seam',
                                                  R/'endpoint-checkpoints'/'patch_endpoint_seam.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    staging.mkdir()
    (staging/'integration_differential_geometry.py').write_bytes(text.encode('utf8'))
    shutil.copyfile(F.PACKAGE/'integration_component_volume_batch.py', staging/'integration_component_volume_batch.py')
    try:
        return module.candidate_sources(staging)
    finally:
        shutil.rmtree(staging)


def compose(directory):
    """One tree, composed once before either child imports the runtime."""
    SW.compose(directory)
    import geometry_transfer as G
    import partition_native_patch as PN
    import partition_workflow_transform as PWT
    package = directory/'src/atlas_tectonics'
    reader = PN.transform((F.PACKAGE/'integration_differential_geometry.py').read_text(encoding='utf8'))
    sources = staged_seam(reader, directory/'staging')
    endpoint = sources['integration_differential_geometry.py']
    sources['integration_differential_geometry.py'] = G.transform(endpoint, compact=True)
    assert (_digest(reader), _digest(endpoint), _digest(sources['integration_differential_geometry.py'])) == (
        PARTITION_READER_SHA256, ENDPOINT_READER_SHA256, GEOMETRY_COMPACT_SHA256)
    for name, text in sources.items():
        (package/name).write_bytes(text.encode('utf8'))
    workflow = package/'integration_regional_workflow.py'
    spatial = workflow.read_text(encoding='utf8')
    assert _digest(spatial) == PWT.WORKFLOW_INPUT_SHA256
    composed = PWT.transform(spatial)
    assert _digest(composed) == PWT.WORKFLOW_OUTPUT_SHA256
    workflow.write_bytes(composed.encode('utf8'))
    for name in PARTITION_HELPERS:
        shutil.copy2(HERE/name, directory/'helpers'/name)
    shutil.copy2(R/'historical_admission.py', directory/'helpers'/'historical_admission.py')
    return {str(p.relative_to(directory)): F.file_hash(p) for folder in (directory/'src', directory/'helpers')
            for p in sorted(folder.rglob('*.py'))}


def native_schema_parent(legacy, D, budget):
    """test_partition_tables' native-schema record carrying the archived synthetic header."""
    import test_partition_tables as TP
    body, supports = TP.tiny_partition(budget)
    for support in supports:
        # A fixed exclusion cannot be advected into a carried material chart.
        support['components'][0]['constraints'] = [['carried:edge', 1], ['normal', -1]]
    for name in HEADER:
        body[name] = deepcopy(legacy[name])
    body['support_ids'] = [D._record_hash(row) for row in supports]
    for contact, ident in zip(body['native_contacts'][0]['contacts'], body['support_ids'], strict=True):
        contact['support_id'] = ident
    return dict(partition_id=D._record_hash(body), **body, supports=supports)


def archive(original, working, limits, owner, TS, TG):
    """Process A only: the sequence-three original, its head carrying the parent blob."""
    import numpy as np
    import spatial_transfer as S
    import workflow_transfer as W
    from atlas_tectonics.storage import ArrayStore
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    budget = owner.budget
    fixture = TS.SpatialTransferTests('test_old_root_restore_remains_strict')
    fixture.setUp()
    SW.real_mesh(fixture, TS)
    initial = spatial = None
    try:
        with S.admit_migrated_spatial_owner(**fixture.args) as lease:
            initial = lease.adopt()
        metadata, arrays = F.archive_operands(fixture, initial, TS, TG)
        native, spatial, interval, bridge, partition = F.restore_transfers(metadata, arrays, owner, TS, TG)
        descriptor = native_schema_parent(metadata.pop('partition'), TG.D, budget)
        raw = W.canonical(descriptor)
        refs = {'partition': dict(array='partition-record:partition', bytes=len(raw), sha256=sha256(raw).hexdigest())}
        current = TG.D.current_geometry_from_interval(interval, budget=budget)
        chain, audit = F.fixture_chain(native.record(), fixture.args, spatial, interval,
                                       SimpleNamespace(partition_id=descriptor['partition_id']), current, TS)
        chain[-1]['differential_partition'] = CollarWorkflow._partition_header(descriptor, refs)
        W.validate_historical_chain(chain)
        metadata['chain_keys'] = [row['key'] for row in chain]
        arrays.update({'audit:'+k: audit.array(k) for k in audit.array_names})
        with ArrayStore(original, limits, budget=budget) as store:
            store.put(F.ARCHIVE_KEY, arrays, metadata, budget=budget)
            for row in chain:
                payload = {'fixture': np.array([1], dtype=np.uint8)}
                if row is chain[-1]:
                    payload['partition-record:partition'] = np.frombuffer(raw, dtype=np.uint8)
                store.put(row['key'], payload, row, budget=budget)
        del metadata, arrays, native, interval, bridge, partition, descriptor, raw, current, chain, audit, payload
    finally:
        for transfer in (initial, spatial):
            if transfer is not None:
                transfer.owner.close()
        fixture.args = fixture.native_owned = None
    gc.collect()
    shutil.copy2(original, working)


def restore_owners(metadata, arrays, owner, TS, TG, *, store):
    """Native, compact-mesh spatial and interval owners; the parent comes separately."""
    import materialise_endpoint as E
    import native_transfer as N
    import spatial_transfer as S
    import spatial_workflow_patch as Y
    from compact_store import CompactMeshStore
    from atlas_tectonics import integration_sphere as Sphere
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    def fields(prefix):
        return {k.removeprefix(prefix): v for k, v in arrays.items() if k.startswith(prefix)}
    incoming, saved = metadata['native_input'], metadata['historical_spatial_record']
    with N.admit_migrated_native_collar(native=owner.native, collar=owner.collar,
            historical_graph=incoming['historical_plan_graph'], historical_native=incoming['historical_native'],
            historical_native_id=incoming['historical_native_id'], native_arrays=fields('native:'),
            historical_collar=incoming['historical_collar'], collar_arrays=fields('collar:'),
            origin=incoming['origin']) as lease:
        native = lease.adopt()
    producer = Y.producer(owner.collar)
    ref = Y.existing_mesh(store, saved['thermal_mesh_id'], producer, budget=owner.budget)
    view = None if ref is None else CompactMeshStore(store, budget=owner.budget).open(ref['snapshot_key'],
                                                          expected_geometry_id=saved['thermal_mesh_id'])
    with CollarWorkflow._spatial_records(saved, None, owner.budget) as (header, _, blobs):
        selected = blobs if view is None else {'spatial-record:state': blobs['spatial-record:state']}
        with E.spatial_records(header, selected, owner.budget, compact_mesh=view, working_store=store,
                               source_producer=producer) as decoded:
            with S.admit_migrated_spatial_owner(collar=owner.collar, native_transfer=native,
                    funding_record=metadata['funding_record'], funding_arrays=fields('funding:'),
                    historical_owner_definition=metadata['historical_owner_definition'],
                    historical_spatial_record=decoded.value, spatial_arrays=fields('spatial:'),
                    funding_binding=metadata['funding_binding'], origin=incoming['origin']) as lease:
                spatial = lease.adopt()
    try:
        network = Sphere.restore_network(metadata['endpoint_network'], fields('network:'), budget=owner.budget)
        interval = TG.D._issue(TG.D.DifferentialInterval, metadata['interval'], owner.budget, network)
        return native, spatial, interval
    except BaseException:
        spatial.owner.close()
        raise


def legacy_parity(context, base, bridge, partition):
    """Process A: the unchanged legacy statements give identical transfer, base and root IDs."""
    import historical_admission as H
    import geometry_transfer as G
    import materialise_endpoint as E
    import partition_workflow_patch as PW
    import workflow_transfer as W
    c = SimpleNamespace(**context)
    arrays = H.read_selected_arrays(c.original_store, c.head['key'], ['partition-record:partition'],
                                    admission=c.historical, budget=c.budget, check=c.check)
    with E.partition_record(c.head['differential_partition'], arrays, c.budget) as decoded:
        legacy_bridge = G.bind_parent_geometry(native_transfer=c.native, partition_descriptor=decoded.value,
            geometry=c.interval, funding=c.spatial.funding, collar=c.collar, budget=c.budget)
        legacy = c.D.DifferentialPartition.restore(decoded.value, c.spatial.funding, c.collar, c.interval,
                                                   budget=c.budget, _runtime_transfer=legacy_bridge)
    del decoded, arrays
    assert bytes(legacy_bridge._record) == bytes(bridge._record)
    assert legacy.compact_view() is None and legacy.partition_id == partition.partition_id
    legacy_base = W.bind_migrated_base(native_transfer=c.native, spatial_transfer=c.spatial,
        geometry_transfer=legacy_bridge, interval=c.interval, partition=legacy,
        historical_admission=c.historical, runtime_admission=c.compatibility, budget=c.budget)
    assert bytes(legacy_base._record) == bytes(base._record)
    with W.migrated_root_payload(legacy_base, store=c.store) as (legacy_root, legacy_payload):
        with W.migrated_root_payload(base, store=c.store) as (root, payload):
            ref = root['compact_partition']
            assert 'compact_partition' not in legacy_root
            assert {k: v for k, v in root.items() if k != 'compact_partition'} == legacy_root
            assert set(payload)-set(legacy_payload) == {PW.PREFIX+n for n in ref['array_bindings']}
            assert set(legacy_payload) <= set(payload)
    # A compact base partition is pinned only through its actual working store.
    try:
        with W.migrated_root_payload(base):
            raise AssertionError('compact root payload without a store')
    except W.WorkflowTransferRefused as error:
        assert 'compact base partition requires' in str(error), error
    return legacy_root['workflow_id']


def run_child(operation, directory, TS, TG):
    import historical_admission as H
    import materialise_endpoint as E
    import partition_store as PS
    import partition_tables as P
    import partition_workflow_patch as PW
    import spatial_workflow_patch as Y
    import workflow_transfer as W
    from atlas_tectonics.storage import ArrayReference, ArrayStore, Compression, StoreLimits
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    owner = TS.SpatialTransferTests
    budget = owner.budget
    original, working, reader = directory/'original.sqlite', directory/'working.sqlite', directory/'reader.sqlite'
    limits = StoreLimits(chunk_bytes=1024, max_array_bytes=2 << 20, max_store_bytes=16 << 20,
        max_manifest_bytes=2 << 20, sqlite_cache_bytes=65536, codec_workspace_bytes=65536)
    phases, checks = [], [0]
    def check():
        checks[0] += 1
    spatial = workflow = None
    try:
        if operation == 'publish':
            archive(original, working, limits, owner, TS, TG)
            opened, path = ArrayStore(working, limits, budget=budget), working
        else:
            working_sha = F.file_hash(working)
            shutil.copyfile(working, reader)
            pin = F.file_hash(reader)
            opened, path = H.open_successor_readonly(reader, expected_sha256=pin, limits=limits,
                                                     compression=Compression(), budget=budget), reader
        original_sha = F.file_hash(original)
        # The original is only ever a readonly view (mode=ro, query_only) here.
        source = H.open_successor_readonly(original, expected_sha256=original_sha, limits=limits,
                                           compression=Compression(), budget=budget)
        with source as original_store, opened as store, ExitStack() as guards:
            if operation == 'reopen':
                # The cold reader never reads, decodes, packs or converts partition JSON.
                for module, name in ((H, 'read_selected_arrays'), (E, 'partition_record'),
                                     (P, 'pack_partition'), (PW, 'convert_native')):
                    guards.enter_context(patch.object(module, name, side_effect=AssertionError('cold reopen used '+name)))
            token = store.change_token()
            metadata = store.metadata(F.ARCHIVE_KEY)
            arrays = store.get(F.ARCHIVE_KEY, budget=budget)
            native, spatial, interval = restore_owners(metadata, arrays, owner, TS, TG, store=store)
            chain = [store.metadata(key) for key in metadata['chain_keys']]
            W.validate_historical_chain(chain)
            head = chain[-1]
            with store._read_scope():
                manifests = {key: deepcopy(store._manifest(key)) for key in [F.ARCHIVE_KEY, *metadata['chain_keys']]}
            audit = TS.Snapshot(head['source_audit'],
                {k.removeprefix('audit:'): v for k, v in arrays.items() if k.startswith('audit:')})
            capsule = dict(schema='atlas.restart-historical-endpoint.v1', authority=F.FIXTURE_ONLY,
                chain_metadata=chain, snapshot_manifests=manifests,
                source=dict(root_key=chain[0]['key'], head_key=head['key'], workflow_id=chain[0]['workflow_id'],
                    sequence=3, time_s=12.5, store_token=dict(fixture=F.FIXTURE_ONLY), database_sha256=original_sha),
                producer=dict(execution_identity='a'*64, source_manifest_sha256='b'*64))
            historical, compatibility = F.fixture_admissions(capsule, native.record()['input']['origin'],
                audit, original, native.record(), budget)
            bridge, partition = E.compact_parent_partition(original_store=original_store, working_store=store,
                admission=historical, head=head, native_transfer=native, interval=interval,
                funding=spatial.funding, collar=owner.collar, budget=budget, check=check, phase=phases.append)
            view = partition.compact_view()
            refs = head['differential_partition']['record_blobs']
            header, stats = dict(PW.compact_header(view, refs)), PW.descriptor_stats(view)
            assert type(view) is P.CompactPartition and view.budget is budget and partition.supports.view is view
            assert header == head['differential_partition']
            assert stats == {'sha256': refs['partition']['sha256'], 'nbytes': refs['partition']['bytes']}
            assert checks[0] > 0 and phases == PHASES[operation], (checks, phases)
            base = W.bind_migrated_base(native_transfer=native, spatial_transfer=spatial, geometry_transfer=bridge,
                interval=interval, partition=partition, historical_admission=historical,
                runtime_admission=compatibility, budget=budget)
            legacy_workflow_id = None
            if operation == 'publish':
                legacy_workflow_id = legacy_parity(dict(original_store=original_store, store=store, head=head,
                    historical=historical, compatibility=compatibility, native=native, spatial=spatial,
                    interval=interval, collar=owner.collar, budget=budget, check=check, D=TG.D),
                    base, bridge, partition)
            with W.migrated_root_payload(base, store=store) as (expected_root, payload):
                workflow_id = expected_root['workflow_id']
                ref = expected_root['compact_partition']
                assert ref == PS.CompactPartitionStore(store, budget=budget).find(partition.partition_id,
                                                                                  Y.producer(owner.collar))
                aliases = {n for n in payload if n.startswith(PW.PREFIX)}
                assert aliases == {PW.PREFIX+n for n in ref['array_bindings']}
                assert all(type(payload[n]) is ArrayReference and payload[n].store_path == str(store.path)
                           for n in aliases)
                assert not [n for n in payload if n.startswith('partition-record:')]
                del payload
            assert legacy_workflow_id in (None, workflow_id)
            workflow = (W.publish_migrated_root(store, base, budget=budget) if operation == 'publish' else
                        CollarWorkflow.open_migrated(store, workflow_id, base, budget=budget))
            assert workflow._head == expected_root and workflow._head['compact_partition'] == ref
            assert workflow._head['sequence'] == 3 and workflow._state.record()['fields']['time_s'] == 12.5
            assert workflow._differential_partition is partition and workflow._migration is base
            W.verify_migrated_workflow(workflow)
            with store._read_scope():
                manifest = deepcopy(store._manifest(workflow._head['key']))
            assert len(W.canonical(manifest)) <= limits.max_manifest_bytes
            assert {n for n in manifest['arrays'] if n.startswith(PW.PREFIX)} == aliases
            assert 'partition-record:partition' not in manifest['arrays']
            assert [store.metadata(key) for key in metadata['chain_keys']] == chain
            assert owner.native.statistics()['accepted_intervals'] == 0
            if operation == 'reopen':
                assert store.change_token() == token, 'cold reopen wrote to the store'
            def fields(values):
                return {k: dict(dtype=v.dtype.str, shape=list(v.shape), sha256=sha256(memoryview(v).cast('B')).hexdigest())
                        for k, v in values.items()}
            result = dict(root=deepcopy(workflow._head), base=base.record(), transfer=bridge.record(),
                partition_id=partition.partition_id, header=header, descriptor_stats=stats,
                support_ids=[view.support_id(i) for i in range(view.support_count)],
                root_aliases={n: manifest['arrays'][n] for n in sorted(aliases)},
                funding=workflow._funding.descriptor(), native_collar_record=workflow._state.record(),
                native_collar_fields=fields(workflow._state.arrays()),
                spatial=SW.logical_summary(workflow._exterior_state),
                spatial_fields=fields(workflow._exterior_state.arrays()),
                source_audit_id=workflow._source_audit.result_id,
                interval=workflow._differential_interval.descriptor(), original_manifests=manifests,
                original_database_sha256=original_sha, execution=owner.native._context.provenance,
                native_accepted_intervals=0)
            workflow.close()
            workflow = None
            del view, partition, bridge, base, historical, compatibility, native, interval, arrays, audit
        assert F.file_hash(original) == original_sha, 'original fixture database changed'
        if operation == 'reopen':
            assert F.file_hash(path) == pin and F.file_hash(working) == working_sha, 'reader or producer copy changed'
        return json.loads(json.dumps(result)), phases
    finally:
        if workflow is not None:
            workflow.close()
        if spatial is not None:
            spatial.owner.close()


def child_main(operation, directory):
    TS, TG = F.initialise_child(directory)
    import mesh_tables as M
    import partition_tables as P
    budget = TS.SpatialTransferTests.budget
    whole = P.CompactPartition.legacy_record
    def selected_only(instance, ref=None):
        if ref is None or ref.index == instance._body:
            raise AssertionError('whole compact partition export forbidden')
        return whole(instance, ref)
    with patch.object(M.CompactMesh, 'legacy_record', side_effect=AssertionError('full compact mesh export forbidden')), \
            patch.object(P.CompactPartition, 'legacy_record', selected_only):
        result, phases = run_child(operation, directory, TS, TG)
    TS.SpatialTransferTests.tearDownClass()
    TS.SpatialTransferTests.collar = TS.SpatialTransferTests.native = None
    TS.SpatialTransferTests.old = TS.SpatialTransferTests.current = None
    gc.collect()
    assert budget.reserved_bytes == 0, budget.statistics()
    print('COMPACT_PARTITION_RESULT '+json.dumps(dict(pid=os.getpid(), reserved_after_close=0, phases=phases,
        result=result), sort_keys=True, separators=(',', ':')), flush=True)


class PartitionFreshProcessTests(unittest.TestCase):
    def test_publish_compact_partition_root_then_cold_readonly_reopen(self):
        with tempfile.TemporaryDirectory(prefix='pwf-', dir=HERE.parents[4]) as temporary:
            directory = Path(temporary)
            sources = compose(directory)
            reports = []
            for operation in ('publish', 'reopen'):
                completed = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                    '--child', operation, str(directory)], capture_output=True, text=True, timeout=300)
                self.assertEqual(completed.returncode, 0, completed.stdout[-3000:]+completed.stderr[-14000:])
                rows = [line for line in completed.stdout.splitlines() if line.startswith('COMPACT_PARTITION_RESULT ')]
                self.assertEqual(len(rows), 1)
                reports.append(json.loads(rows[0].removeprefix('COMPACT_PARTITION_RESULT ')))
                self.assertEqual({name: F.file_hash(directory/name) for name in sources}, sources)
            self.assertNotEqual(reports[0]['pid'], reports[1]['pid'])
            self.assertEqual([r['phases'] for r in reports], [PHASES['publish'], PHASES['reopen']])
            self.assertEqual([r['reserved_after_close'] for r in reports], [0, 0])
            self.assertEqual(reports[0]['result'], reports[1]['result'])
            first = reports[0]['result']
            self.assertEqual(first['root']['compact_partition']['partition_id'], first['partition_id'])
            print('COMPACT_PARTITION_FRESH_PROCESS_PASS '+json.dumps(dict(processes=2, sequence=3, time_s=12.5,
                partition_id=first['partition_id'], descriptor_stats=first['descriptor_stats'],
                reserved_after_close=[0, 0], source_closure_sha256=sha256(json.dumps(sources,
                    sort_keys=True).encode()).hexdigest()), sort_keys=True), flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--child' and sys.argv[2] in PHASES:
        child_main(sys.argv[2], Path(sys.argv[3]).resolve())
    else:
        unittest.main(verbosity=2)
