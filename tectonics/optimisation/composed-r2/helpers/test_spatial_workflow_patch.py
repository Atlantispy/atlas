"""Tiny real store/owner/workflow round trip; synthetic historical evidence only."""
from copy import deepcopy
from hashlib import sha256
import gc
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import test_workflow_fresh_process as F


def compose(directory):
    F.compose(directory)
    sys.path[:0] = [str(F.PACKAGE.parent), str(F.INTEGRATION/'ram'), str(F.INTEGRATION/'helpers')]
    import spatial_indexed_patch as X
    import spatial_workflow_patch as Y
    package = directory/'src/atlas_tectonics'
    for name, transform in (('integration_spatial_owner.py', X.transform),
                            ('integration_regional_workflow.py', Y.transform)):
        path = package/name
        path.write_text(transform(path.read_text(encoding='utf8')), encoding='utf8')
    for name in ('mesh_tables.py', 'compact_store.py', 'spatial_indexed_patch.py',
                 'spatial_workflow_patch.py', 'test_mesh_tables.py'):
        shutil.copy2(HERE/name, directory/'helpers'/name)
    shutil.copy2(HERE.parent/'materialise_endpoint.py', directory/'helpers/materialise_endpoint.py')
    return {str(p.relative_to(directory)): F.file_hash(p) for folder in (directory/'src', directory/'helpers')
            for p in sorted(folder.rglob('*.py'))}


def real_mesh(fixture, TS):
    import mesh_tables as M
    import spatial_transfer as S
    from test_mesh_tables import small_mesh_record
    saved = fixture.args['historical_spatial_record']
    mesh = small_mesh_record(fixture.budget)
    mesh.update(funding_id=saved['funding_id'], source=fixture.args['funding_record']['source'],
        grid_id=saved['grid_id'], support_id=saved['support_id'], time_s=TS.enc(saved['time_s']),
        trajectory_id=saved['trajectory_id'], trajectory_segments=saved['trajectory']['segments'])
    for geometric, stock in zip(mesh['cells'], saved['cells'], strict=True):
        geometric['kind'] = 'exterior'
        stock['cell_id'] = geometric['logical_cell_id']
    saved['thermal_mesh'], saved['thermal_mesh_id'] = mesh, M.digest(mesh)
    saved['state_id'] = S._snapshot_id({k: v for k, v in saved.items() if k != 'state_id'},
                                      S._bindings(fixture.args['spatial_arrays']))


def compact_restore(metadata, arrays, owner, TS, TG, *, store):
    import materialise_endpoint as E
    import spatial_workflow_patch as Y
    from compact_store import CompactMeshStore
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    saved = metadata['historical_spatial_record']
    producer = Y.producer(owner.collar)
    ref = Y.existing_mesh(store, saved['thermal_mesh_id'], producer, budget=owner.budget)
    view = None if ref is None else CompactMeshStore(store, budget=owner.budget).open(ref['snapshot_key'],
                                                          expected_geometry_id=saved['thermal_mesh_id'])
    # Exercise the production original blob decoder/converter, including the
    # cold reopen branch that reads only the old state, never its mesh JSON.
    with CollarWorkflow._spatial_records(saved, None, owner.budget) as (header, _, blobs):
        selected = blobs if view is None else {'spatial-record:state': blobs['spatial-record:state']}
        with E.spatial_records(header, selected, owner.budget, compact_mesh=view, working_store=store,
                source_producer=producer) as decoded:
            incoming = dict(metadata, historical_spatial_record=decoded.value)
            return F.restore_transfers(incoming, arrays, owner, TS, TG)


def logical_summary(state):
    import spatial_indexed_patch as X
    snapshot = state._snapshot
    assert type(snapshot) is X.IndexedSpatialSnapshot
    assert 'thermal_mesh' not in json.loads(snapshot._metadata)
    return dict(state_id=X.snapshot_identity(snapshot), logical_metadata=list(snapshot._logical_metadata),
                stock=json.loads(snapshot._metadata))


def extra_checks(store, workflow, spatial, owner, *, operation):
    import numpy as np
    import spatial_workflow_patch as Y
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    from atlas_tectonics.storage import ArrayReference
    ref = workflow._head['exterior_state']['compact_mesh']
    token = store.change_token()
    loaded = Y.workflow_arrays(store, workflow._head['key'], budget=owner.budget)
    assert not any(name.startswith(Y.PREFIX) for name in loaded)
    blobs = {k: v for k, v in loaded.items() if k.startswith('spatial-record:')}
    assert set(blobs) == {'spatial-record:state'}
    with CollarWorkflow._spatial_restore_records(workflow._head['exterior_state'], None, blobs,
            owner.budget, store=store) as (saved, exchange):
        assert exchange is None
        restored = spatial.owner.restore(saved, spatial.state.arrays())
        assert restored.state_id == spatial.state.state_id
    del restored, saved, loaded, blobs
    with CollarWorkflow._spatial_records(spatial.state, None, owner.budget, store=store,
            source_producer=Y.producer(owner.collar)) as (header, _, payload):
        assert header == workflow._head['exterior_state']
        assert 'spatial-record:mesh' not in payload
        assert all(type(v) is ArrayReference for k, v in payload.items() if k.startswith(Y.PREFIX))
    assert token == store.change_token(), 'identical mesh republished chunks or metadata'
    wrong = deepcopy(dict(ref)); wrong['source_producer']['role'] = 'changed'
    try:
        Y.verify_reference(store, wrong, budget=owner.budget)
    except Y.X.IndexedSpatialRefused:
        pass
    else:
        raise AssertionError('changed producer reference accepted')
    # Cancellation before staging must not change even a lookup root.
    from concurrent.futures import CancelledError
    before = store.change_token()
    try:
        Y.persist_mesh(store, spatial.state._snapshot._mesh, Y.producer(owner.collar),
                       budget=owner.budget, cancel=lambda: True)
    except CancelledError:
        pass
    else:
        raise AssertionError('cancel ignored')
    assert before == store.change_token()
    assert np.array_equal(workflow._exterior_state.arrays()['volume_m3'], spatial.state.arrays()['volume_m3'])


def child_main(operation, directory):
    TS, TG = F.initialise_child(directory)
    import mesh_tables as M
    # Reuse the established independent-process historical fixture body with
    # explicit, asserted substitutions; no production validator is mocked.
    source = inspect.getsource(F.run_child)
    changes = (
        ('            fixture.setUp()', '            fixture.setUp()\n            real_mesh(fixture, TS)'),
        ('            native, spatial, interval, bridge, partition = restore_transfers(metadata, arrays, owner, TS, TG)\n            chain =',
         '            native, spatial, interval, bridge, partition = compact_restore(metadata, arrays, owner, TS, TG, store=store)\n            chain ='),
        ('with W.migrated_root_payload(base)', 'with W.migrated_root_payload(base, store=store)'),
        ('workflow._exterior_state.record()', 'logical_summary(workflow._exterior_state)'),
        ('spatial.state.record()', 'logical_summary(spatial.state)'),
        ('            def fields(values):', '            extra_checks(store, workflow, spatial, owner, operation=operation)\n            def fields(values):'),
    )
    for old, new in changes:
        assert source.count(old) > 0, old
        source = source.replace(old, new)
    namespace = dict(vars(F), real_mesh=real_mesh, compact_restore=compact_restore,
                     logical_summary=logical_summary, extra_checks=extra_checks)
    exec(compile(source, '<compact-workflow-fixture>', 'exec'), namespace)
    budget = TS.SpatialTransferTests.budget
    with patch.object(M.CompactMesh, 'legacy_record', side_effect=AssertionError('full compact mesh export forbidden')):
        result = namespace['run_child'](operation, directory, TS, TG)
    TS.SpatialTransferTests.tearDownClass()
    TS.SpatialTransferTests.collar = TS.SpatialTransferTests.native = None
    TS.SpatialTransferTests.old = TS.SpatialTransferTests.current = None
    gc.collect()
    assert budget.reserved_bytes == 0, budget.statistics()
    print('COMPACT_WORKFLOW_RESULT '+json.dumps(dict(pid=os.getpid(), reserved_after_close=0, result=result),
                                              sort_keys=True, separators=(',', ':')), flush=True)


class CompactWorkflowTests(unittest.TestCase):
    def test_changed_alias_held_traceback_and_escaped_read_are_funded(self):
        import test_mesh_tables as MT
        import spatial_workflow_patch as Y
        import numpy as np
        from atlas_tectonics.storage import ArrayStore, StoreLimits
        budget = MT.WorkBudget(128 << 20)
        with tempfile.TemporaryDirectory(prefix='cwa-', dir=HERE.parents[4]) as temporary:
            with ArrayStore(Path(temporary)/'tiny.sqlite', StoreLimits(chunk_bytes=256,
                    max_array_bytes=2 << 20, max_store_bytes=16 << 20, max_manifest_bytes=256 << 10,
                    sqlite_cache_bytes=65536, codec_workspace_bytes=65536), budget=budget) as store:
                view, metadata, arrays, blobs, reads = MT.compact_fixture(budget=budget)
                ref = Y.persist_mesh(store, view, {'fixture': 'bounded ownership only'}, budget=budget)
                aliases = {Y.PREFIX+n: store.reference(ref['snapshot_key'], n) for n in ref['array_bindings']}
                aliases['fixture'] = np.arange(2, dtype=np.float64)
                key = '3'*64
                store.put(key, aliases, {'exterior_state': {'compact_mesh': ref}}, budget=budget)
                baseline = budget.reserved_bytes
                values = Y.workflow_arrays(store, key, budget=budget)
                escaped = values['fixture']
                del values
                self.assertGreater(budget.reserved_bytes, baseline)
                self.assertFalse(escaped.flags.writeable)
                del escaped
                gc.collect()
                self.assertEqual(budget.reserved_bytes, baseline)
                first = next(k for k in aliases if k.startswith(Y.PREFIX))
                aliases[first] = np.array([255], dtype=np.uint8)
                store.put('4'*64, aliases, {'exterior_state': {'compact_mesh': ref}}, budget=budget)
                baseline = budget.reserved_bytes
                held = None
                try:
                    Y.workflow_arrays(store, '4'*64, budget=budget)
                except Y.X.IndexedSpatialRefused as failure:
                    self.assertIn('aliases differ', str(failure))
                    held = failure.__traceback__
                    failure.__traceback__ = None
                self.assertIsNotNone(held)
                gc.collect()
                self.assertGreater(budget.reserved_bytes, baseline)
                del held
                gc.collect()
                self.assertEqual(budget.reserved_bytes, baseline)
                del view, metadata, arrays, blobs, reads, ref, aliases
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_many_supports_link_and_alias_manifests_stay_bounded(self):
        """Caps fix: persist_mesh's link put carried one alias and a full chunk list per support.

        The r9 head mesh has about 2,024 supports (derived lower bound 1,047,596 of
        1,048,576 bytes for the link). Here 1,100 supports exceed this store's
        256 KiB manifest at 256 B of projection each; root, link and a workflow
        alias set now hold the codec columns plus one packed array, and the
        reference binds each array by its ArrayReference descriptor digest.
        """
        import test_mesh_tables as MT
        import spatial_workflow_patch as Y
        import numpy as np
        from atlas_tectonics.storage import ArrayStore, StoreLimits, _json
        budget = MT.WorkBudget(256 << 20)
        record = MT.small_mesh_record(budget)
        record['support_tables']['differential_supports'] = {sha256(str(i).encode()).hexdigest():
            {'fixture': i, 'pad': 'p'*(i % 300)} for i in range(1100)}
        limits = StoreLimits(chunk_bytes=256, max_array_bytes=2 << 20, max_store_bytes=32 << 20,
                             max_manifest_bytes=256 << 10, sqlite_cache_bytes=65536, codec_workspace_bytes=65536)
        self.assertGreater(256*1100, limits.max_manifest_bytes)
        with tempfile.TemporaryDirectory(prefix='cws-', dir=HERE.parents[4]) as temporary:
            with ArrayStore(Path(temporary)/'many.sqlite', limits, budget=budget) as store:
                view = MT.compact_fixture(record, budget)[0]
                producer = {'fixture': 'bounded ownership only'}
                ref = Y.persist_mesh(store, view, producer, budget=budget)
                with store._read_scope():
                    root = store._manifest(ref['snapshot_key'])
                self.assertEqual(len(root['arrays']), len(root['metadata']['codec_metadata']['arrays'])+1)
                self.assertEqual(ref['array_bindings'], {n: store.reference(ref['snapshot_key'], n).descriptor_sha256
                                                         for n in root['arrays']})
                self.assertLess(len(_json(dict(ref))), 8192)
                self.assertEqual(Y.existing_mesh(store, view.geometry_id, producer, budget=budget), ref)
                aliases = {Y.PREFIX+n: store.reference(ref['snapshot_key'], n) for n in ref['array_bindings']}
                store.put('5'*64, dict(aliases, fixture=np.arange(2, dtype=np.float64)),
                          {'exterior_state': {'compact_mesh': ref}}, budget=budget)
                self.assertEqual(set(Y.workflow_arrays(store, '5'*64, budget=budget)), {'fixture'})
                # A reference carrying the old full description instead of its digest refuses.
                name = sorted(ref['array_bindings'])[0]
                stale = dict(ref, array_bindings=dict(ref['array_bindings'], **{name: root['arrays'][name]}))
                with self.assertRaises(Y.X.IndexedSpatialRefused):
                    Y.verify_reference(store, stale, budget=budget)
                del view, ref, aliases, stale
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_actual_publish_independent_reopen_no_mesh_json_and_exact_history(self):
        with tempfile.TemporaryDirectory(prefix='cwf-', dir=HERE.parents[4]) as temporary:
            directory = Path(temporary)
            sources = compose(directory)
            reports = []
            for operation in ('publish', 'reopen'):
                completed = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                    '--child', operation, str(directory)], capture_output=True, text=True, timeout=180)
                self.assertEqual(completed.returncode, 0, completed.stdout[-3000:]+completed.stderr[-14000:])
                rows = [line for line in completed.stdout.splitlines() if line.startswith('COMPACT_WORKFLOW_RESULT ')]
                self.assertEqual(len(rows), 1)
                reports.append(json.loads(rows[0].removeprefix('COMPACT_WORKFLOW_RESULT ')))
                self.assertEqual({name: F.file_hash(directory/name) for name in sources}, sources)
            self.assertNotEqual(reports[0]['pid'], reports[1]['pid'])
            self.assertEqual(reports[0]['result'], reports[1]['result'])
            self.assertEqual([r['reserved_after_close'] for r in reports], [0, 0])
            print('COMPACT_WORKFLOW_PASS '+json.dumps(dict(processes=2, sequence=3, time_s=12.5,
                reserved_after_close=[0, 0], source_closure_sha256=sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest())), flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--child':
        child_main(sys.argv[2], Path(sys.argv[3]).resolve())
    else:
        unittest.main(verbosity=2)
