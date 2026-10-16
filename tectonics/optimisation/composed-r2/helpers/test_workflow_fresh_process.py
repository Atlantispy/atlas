"""Two independent processes, real transfer/store objects, fixture evidence.

This is persistence/ownership verification, NOT historical or scientific
acceptance. Historical execution/geometry/admission records are explicitly
synthetic. Both processes share byte-identical temporary runtime/helper sources;
the second reads archived operands rather than reusing Python objects or pickle.
No force, transport, heat or geometric solve, initial_state or funding call runs.
"""
from copy import deepcopy
import gc
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
INTEGRATION = HERE.parent/'runtime-integration-r1'
PACKAGE = INTEGRATION/'runtime-src/atlas_tectonics'
HEAT = HERE.parents[2]/'heat-repair-20261007'
ARCHIVE_KEY = '0'*64
FIXTURE_ONLY = 'SYNTHETIC FIXTURE ONLY; NOT HISTORICAL OR SCIENTIFIC ACCEPTANCE'


def file_hash(path):
    result = sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            result.update(block)
    return result.hexdigest()


def compose(directory):
    """One source tree, composed once before either child imports the runtime."""
    import native_transfer as N
    import spatial_transfer as S
    import geometry_transfer as G
    import workflow_transfer as W
    runtime = directory/'src'
    package = runtime/'atlas_tectonics'
    shutil.copytree(PACKAGE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name, transform in (('regional_execution.py', N.retained_snapshot_source),
            ('integration_spatial_owner.py', S.spatial_owner_source),
            ('integration_differential_geometry.py', G.transform),
            ('integration_regional_workflow.py', W.nonzero_cursor_source),
            ('integration_private_heat_cold.py', W.private_heat_cold_source)):
        path = package/name
        path.write_text(transform(path.read_text(encoding='utf8')), encoding='utf8')
    helpers = directory/'helpers'
    helpers.mkdir()
    for name in ('native_transfer.py', 'spatial_transfer.py', 'geometry_transfer.py', 'workflow_transfer.py',
                 'test_native_transfer.py', 'test_spatial_transfer.py', 'test_geometry_transfer_integration.py'):
        shutil.copy2(HERE/name, helpers/name)
    return {str(path.relative_to(directory)): file_hash(path)
            for folder in (runtime, helpers) for path in sorted(folder.rglob('*.py'))}


def initialise_child(directory):
    """Reuse fixture builders only; never run their module/suite setup."""
    sys.path[:0] = [str(directory/'src'), str(directory/'helpers'), str(INTEGRATION/'ram'),
                   str(INTEGRATION/'helpers'), str(HEAT), str(HEAT/'source/tectonics/tests')]
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
    return TS, TG


def fixture_chain(native, args, spatial, interval, partition, current, TS):
    """Same explicit sequence-three archive shape as the in-process control."""
    import numpy as np
    import workflow_transfer as W
    ident = '1'*64
    root = dict(schema=W.WORKFLOW_SCHEMA, kind='root', sequence=0, workflow_id=ident,
        key=W.workflow_key('root', ident), funding_id=spatial.funding.funding_id,
        funding=spatial.funding.descriptor(), exterior_remainder=spatial.funding.exterior_remainder(),
        state=dict(result_id='2'*64, fields=dict(time_s=0.), native={}),
        native_state_id='3'*64, exterior_state=dict(state_id='4'*64))
    chain = [root]
    for sequence, end in ((1, 4.), (2, 8.), (3, 12.5)):
        previous, last = chain[-1], sequence == 3
        state = native['input']['historical_collar'] if last else dict(
            result_id=('c' if sequence == 2 else '5')*64,
            fields=dict(time_s=end, parent_id=previous['state']['result_id']),
            native=dict(parent_state_id=previous['native_state_id']))
        audit = TS.Snapshot(dict(schema='fixture.synthetic-source-audit.v1',
            parent_state_id=previous['native_state_id'], start_time_s=previous['state']['fields']['time_s'],
            duration_s=end-previous['state']['fields']['time_s']), {'fixture': np.array([sequence], dtype=np.uint8)})
        exterior = args['historical_spatial_record'] if last else dict(
            state_id=('9' if sequence == 2 else '6')*64, parent_state_id=previous['exterior_state']['state_id'],
            intervals=sequence, time_s=end, collar_state_id=state['result_id'])
        chain.append(dict(schema=W.WORKFLOW_SCHEMA, kind='successor', sequence=sequence,
            workflow_id=ident, key=W.workflow_key('successor', previous['key']),
            parent_key=previous['key'], parent_digest=W.digest(previous), funding_id=root['funding_id'],
            state=state, native_state_id=native['input']['historical_native_id'] if last else ('b' if sequence == 2 else '7')*64,
            advance=dict(duration_s=audit.descriptor()['duration_s'], source_audit_id=audit.result_id),
            source_audit=audit.descriptor(), exterior_state=exterior, exterior_advance=dict(fixture=FIXTURE_ONLY),
            differential_geometry=dict(interval_id=interval.interval_id),
            differential_partition=dict(partition_id=partition.partition_id),
            differential_certification=dict(endpoint_current_geometry_id=current.geometry_id)))
    W.validate_historical_chain(chain)
    return chain, audit


def archive_operands(fixture, spatial, TS, TG):
    """Keep records plus complete numerical operands, not live Python owners."""
    from atlas_tectonics import integration_sphere as Sphere
    import workflow_transfer as W
    interval, partition_record = TG.synthetic_geometry_and_partition(spatial=spatial,
        collar=fixture.collar, native_transfer=fixture.native_owned, budget=fixture.budget)
    row = dict(interval.record(), duration_s=TS.enc(4.5), start_time_s=TS.enc(8),
        rays={}, boundary_paths=[], plate_angular_velocity_rad_s={}, ownership_fans=[],
        radius_m=TS.enc(10), trajectory=spatial.state.record()['trajectory'])
    network = fixture.source[0].network
    # Native restoration authenticates the actual network array/descriptor
    # shape. The enclosing interval remains explicitly synthetic geometry.
    restored_network = Sphere.restore_network(network.descriptor(), network.arrays(), budget=fixture.budget)
    interval = TG.D._issue(TG.D.DifferentialInterval, row, fixture.budget, restored_network)
    partition_record.update(interval_id=interval.interval_id, start_time_s=row['start_time_s'])
    TG.rehash_partition(partition_record)
    native = fixture.native_owned.record()
    metadata = dict(fixture=FIXTURE_ONLY, native_input=native['input'],
        funding_record=fixture.args['funding_record'], historical_owner_definition=fixture.args['historical_owner_definition'],
        historical_spatial_record=fixture.args['historical_spatial_record'], funding_binding=fixture.args['funding_binding'],
        interval=row, endpoint_network=network.descriptor(), partition=partition_record)
    arrays = {}
    for prefix, values in (
            ('native:', {k: fixture.native_owned.state.native_state.array(k) for k in fixture.native_owned.state.native_state.array_names}),
            ('collar:', fixture.native_owned.state.arrays()),
            ('funding:', fixture.args['funding_arrays']), ('spatial:', fixture.args['spatial_arrays']),
            ('network:', network.arrays())):
        arrays.update({prefix+k: v for k, v in values.items()})
    W.canonical(metadata)
    return metadata, arrays


def restore_transfers(metadata, arrays, owner, TS, TG):
    import native_transfer as N
    import spatial_transfer as S
    import geometry_transfer as G
    from atlas_tectonics import integration_sphere as Sphere
    def fields(prefix):
        return {k.removeprefix(prefix): v for k, v in arrays.items() if k.startswith(prefix)}
    incoming = metadata['native_input']
    with N.admit_migrated_native_collar(native=owner.native, collar=owner.collar,
            historical_graph=incoming['historical_plan_graph'], historical_native=incoming['historical_native'],
            historical_native_id=incoming['historical_native_id'], native_arrays=fields('native:'),
            historical_collar=incoming['historical_collar'], collar_arrays=fields('collar:'),
            origin=incoming['origin']) as lease:
        native = lease.adopt()
    with S.admit_migrated_spatial_owner(collar=owner.collar, native_transfer=native,
            funding_record=metadata['funding_record'], funding_arrays=fields('funding:'),
            historical_owner_definition=metadata['historical_owner_definition'],
            historical_spatial_record=metadata['historical_spatial_record'], spatial_arrays=fields('spatial:'),
            funding_binding=metadata['funding_binding'], origin=incoming['origin']) as lease:
        spatial = lease.adopt()
    try:
        network = Sphere.restore_network(metadata['endpoint_network'], fields('network:'), budget=owner.budget)
        interval = TG.D._issue(TG.D.DifferentialInterval, metadata['interval'], owner.budget, network)
        bridge = G.bind_parent_geometry(native_transfer=native, partition_descriptor=metadata['partition'],
            geometry=interval, funding=spatial.funding, collar=owner.collar, budget=owner.budget)
        partition = TG.D.DifferentialPartition.restore(metadata['partition'], spatial.funding, owner.collar,
            interval, budget=owner.budget, _runtime_transfer=bridge)
        return native, spatial, interval, bridge, partition
    except BaseException:
        spatial.owner.close()
        raise


def fixture_admissions(capsule, origin, audit, original, native, budget):
    """Test-only issuance; deliberately separate from production adapters."""
    import workflow_transfer as W
    import native_transfer as N
    binding = dict(capsule_sha256=W.digest(capsule), origin=origin,
        original_database_path=str(original), fixture=FIXTURE_ONLY)
    runtime = dict(schema='atlas.restart-runtime-compatibility.v1', historical_execution_identity='a'*64,
        current_execution_identity=native['input']['current_plan_graph']['native']['definition']['execution'],
        scientific_contract_id=native['input']['compatibility']['scientific_contract_id'],
        historical_source_manifest_sha256='b'*64, current_source_manifest_sha256='c'*64,
        validation_evidence=[FIXTURE_ONLY])
    encoded = tuple(map(W.canonical, (capsule, binding, runtime)))
    allocation = N._Allocation(budget, sum(map(len, encoded))+4096, category='fixture-admissions-retained')
    historical, compatibility = object.__new__(W.HistoricalEndpointAdmission), object.__new__(W.RuntimeCompatibilityAdmission)
    object.__setattr__(historical, '_record', N._RecordBytes(encoded[0], allocation))
    object.__setattr__(historical, '_binding', N._RecordBytes(encoded[1], allocation))
    object.__setattr__(historical, '_source_audit', audit)
    object.__setattr__(compatibility, '_record', N._RecordBytes(encoded[2], allocation))
    return historical, compatibility


def run_child(operation, directory, TS, TG):
    import numpy as np
    import spatial_transfer as S
    import workflow_transfer as W
    from atlas_tectonics.storage import ArrayStore, StoreLimits
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    owner = TS.SpatialTransferTests
    budget = owner.budget
    original, working = directory/'original.sqlite', directory/'working.sqlite'
    limits = StoreLimits(chunk_bytes=1024, max_array_bytes=2 << 20, max_store_bytes=16 << 20,
        max_manifest_bytes=2 << 20, sqlite_cache_bytes=65536, codec_workspace_bytes=65536)
    spatial = initial_spatial = fixture = workflow = None
    try:
        if operation == 'publish':
            fixture = TS.SpatialTransferTests('test_old_root_restore_remains_strict')
            fixture.setUp()
            with S.admit_migrated_spatial_owner(**fixture.args) as lease:
                initial_spatial = lease.adopt()
            metadata, arrays = archive_operands(fixture, initial_spatial, TS, TG)
            native, spatial, interval, bridge, partition = restore_transfers(metadata, arrays, owner, TS, TG)
            current = TG.D.current_geometry_from_interval(interval, budget=budget)
            chain, audit = fixture_chain(native.record(), fixture.args, spatial, interval, partition, current, TS)
            metadata['chain_keys'] = [row['key'] for row in chain]
            arrays.update({'audit:'+k: audit.array(k) for k in audit.array_names})
            with ArrayStore(original, limits, budget=budget) as store:
                store.put(ARCHIVE_KEY, arrays, metadata, budget=budget)
                for row in chain:
                    store.put(row['key'], {'fixture': np.array([1], dtype=np.uint8)}, row, budget=budget)
            initial_spatial.owner.close()
            initial_spatial = None
            spatial.owner.close()
            fixture.args = fixture.native_owned = None
            fixture = None
            del arrays, native, spatial, interval, bridge, partition, current, audit, chain
            spatial = None
            gc.collect()
            shutil.copy2(original, working)
        original_sha = file_hash(original)
        with ArrayStore(working, limits, budget=budget) as store:
            before_token = store.change_token()
            metadata = store.metadata(ARCHIVE_KEY)
            arrays = store.get(ARCHIVE_KEY, budget=budget)
            native, spatial, interval, bridge, partition = restore_transfers(metadata, arrays, owner, TS, TG)
            chain = [store.metadata(key) for key in metadata['chain_keys']]
            W.validate_historical_chain(chain)
            with store._read_scope():
                manifests = {key: deepcopy(store._manifest(key)) for key in [ARCHIVE_KEY, *metadata['chain_keys']]}
            audit = TS.Snapshot(chain[-1]['source_audit'],
                {k.removeprefix('audit:'): v for k, v in arrays.items() if k.startswith('audit:')})
            token = dict(schema='atlas.historical-store-content-token.v1', database_sha256=original_sha,
                         reader_receipt_sha256='f'*64, fixture=FIXTURE_ONLY)
            capsule = dict(schema='atlas.restart-historical-endpoint.v1', authority=FIXTURE_ONLY,
                chain_metadata=chain, snapshot_manifests=manifests,
                source=dict(root_key=chain[0]['key'], head_key=chain[-1]['key'], workflow_id=chain[0]['workflow_id'],
                    sequence=3, time_s=12.5, store_token=token, database_sha256=original_sha),
                producer=dict(execution_identity='a'*64, source_manifest_sha256='b'*64))
            historical, compatibility = fixture_admissions(capsule, native.record()['input']['origin'],
                audit, original, native.record(), budget)
            base = W.bind_migrated_base(native_transfer=native, spatial_transfer=spatial,
                geometry_transfer=bridge, interval=interval, partition=partition,
                historical_admission=historical, runtime_admission=compatibility, budget=budget)
            with W.migrated_root_payload(base) as (expected_root, _borrowed):
                workflow_id = expected_root['workflow_id']
            workflow = (W.publish_migrated_root(store, base, budget=budget) if operation == 'publish' else
                        CollarWorkflow.open_migrated(store, workflow_id, base, budget=budget))
            assert workflow._head == expected_root
            assert workflow._head['sequence'] == 3
            assert workflow._state.record()['fields']['time_s'] == 12.5
            assert workflow._state.record() == native.state.record()
            assert workflow._exterior_state.record() == spatial.state.record()
            assert workflow._funding.descriptor() == metadata['funding_record']
            assert workflow._differential_partition.descriptor() == metadata['partition']
            assert owner.native.statistics()['accepted_intervals'] == 0
            assert [store.metadata(key) for key in metadata['chain_keys']] == chain
            if operation == 'reopen':
                assert store.change_token() == before_token, 'fresh reopen wrote to the store'
            def fields(values):
                return {k: dict(dtype=v.dtype.str, shape=list(v.shape), sha256=sha256(memoryview(v).cast('B')).hexdigest())
                        for k, v in values.items()}
            result = dict(root=deepcopy(workflow._head), funding=workflow._funding.descriptor(),
                native_collar_record=workflow._state.record(), native_collar_fields=fields(workflow._state.arrays()),
                spatial_record=workflow._exterior_state.record(), spatial_fields=fields(workflow._exterior_state.arrays()),
                source_audit_id=workflow._source_audit.result_id, partition=workflow._differential_partition.descriptor(),
                interval=workflow._differential_interval.descriptor(),
                original_manifests=manifests, original_database_sha256=original_sha,
                execution=owner.native._context.provenance, native_accepted_intervals=0)
            workflow.close()
            workflow = None
        assert file_hash(original) == original_sha, 'original fixture database changed'
        return result
    finally:
        if workflow is not None:
            workflow.close()
        if spatial is not None:
            spatial.owner.close()
        if initial_spatial is not None:
            initial_spatial.owner.close()
        if fixture is not None:
            fixture.args = fixture.native_owned = None


def child_main(operation, directory):
    TS, TG = initialise_child(directory)
    budget = TS.SpatialTransferTests.budget
    result = run_child(operation, directory, TS, TG)
    TS.SpatialTransferTests.tearDownClass()
    TS.SpatialTransferTests.collar = TS.SpatialTransferTests.native = None
    TS.SpatialTransferTests.old = TS.SpatialTransferTests.current = None
    gc.collect()
    assert budget.reserved_bytes == 0, budget.statistics()
    print('FRESH_PROCESS_RESULT '+json.dumps(dict(pid=os.getpid(), reserved_after_close=0, result=result),
                                          sort_keys=True, separators=(',', ':')), flush=True)


class FreshProcessTests(unittest.TestCase):
    def test_publish_then_independent_reopen_identical_sources_and_exact_state(self):
        with tempfile.TemporaryDirectory(prefix='wf-', dir=HERE) as temporary:
            directory = Path(temporary)
            sources = compose(directory)
            reports = []
            for operation in ('publish', 'reopen'):
                completed = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                    '--child', operation, str(directory)], capture_output=True, text=True, timeout=180)
                self.assertEqual(completed.returncode, 0, completed.stdout[-3000:]+completed.stderr[-12000:])
                rows = [line for line in completed.stdout.splitlines() if line.startswith('FRESH_PROCESS_RESULT ')]
                self.assertEqual(len(rows), 1)
                reports.append(json.loads(rows[0].removeprefix('FRESH_PROCESS_RESULT ')))
                self.assertEqual({name: file_hash(directory/name) for name in sources}, sources)
            self.assertNotEqual(reports[0]['pid'], reports[1]['pid'])
            self.assertEqual(reports[0]['reserved_after_close'], 0)
            self.assertEqual(reports[1]['reserved_after_close'], 0)
            self.assertEqual(reports[0]['result'], reports[1]['result'])
            print('WORKFLOW_FRESH_PROCESS_FIXTURE_PASS '+json.dumps(dict(processes=2,
                sequence=3, time_s=12.5, reserved_after_close=[0, 0],
                runtime_source_closure_sha256=sha256(json.dumps(sources, sort_keys=True,
                    separators=(',', ':')).encode()).hexdigest(),
                transfer_helper_sha256={name: value for name, value in sources.items()
                    if name.startswith('helpers') and not Path(name).name.startswith('test_')}),
                sort_keys=True), flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--child' and sys.argv[2] in ('publish', 'reopen'):
        child_main(sys.argv[2], Path(sys.argv[3]).resolve())
    else:
        unittest.main(verbosity=2)
