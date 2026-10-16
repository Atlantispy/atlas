"""Bounded WP3 storage controls; synthetic provenance, no historical DB or IV2."""
from copy import deepcopy
from contextlib import ExitStack
import gc
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
sys.path[:0] = [str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'), str(HERE.parent)]

from atlas_tectonics.resources import WorkBudget
from compact_contracts import SegmentRef
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
from compact_store import CompactMeshStoreV3
import mesh_tables as M
from partition_tables import pack_partition_v2
from partition_store import publish_partition_v2
from support_source import support_source
from test_mesh_tables import small_mesh_record
from test_partition_tables import tiny_partition


class NativeSupport:
    def __init__(self, record):
        self.value = record

    def record(self):
        return self.value


def fixture(scope, candidate, *, count=3, coverage_bytes=0, checkpoint=lambda stage, **fields: None):
    body, examples = tiny_partition(scope.run_budget, count=1, depth=0)
    base = examples[0]
    base['coverage'] = 'x'*coverage_bytes if coverage_bytes else base['coverage']
    def rows():
        for i in range(count):
            yield dict(base, voxel_index=[i, 0, 0])
    identities = [M.digest(row) for row in rows()]
    checkpoint('support-identities')
    identity_set = set(identities)
    body['support_ids'] = identities[::-1]
    # Partition order deliberately differs from mesh's canonical table order.
    view = pack_partition_v2(body, (dict(base, voxel_index=[i, 0, 0]) for i in range(count-1, -1, -1)),
                             expected_partition_id=M.digest(body), scope=scope)
    checkpoint('partition-packed', nodes=view.record._meta['arrays']['node.kind']['shape'][0],
               columns={name: dict(shape=row['shape'], dtype=row['dtype'])
                        for name, row in view.record._meta['arrays'].items()})
    partition_ref = publish_partition_v2(candidate, view, producer='b'*64)
    checkpoint('partition-published', reference=partition_ref.to_wire())
    source = support_source(view)
    record = small_mesh_record(scope.run_budget)
    record['support_tables']['radial_layers'] = {sha256(b'static-radial-id').hexdigest(): base['radial_layer']}
    record['support_tables']['cones'] = {sha256(b'static-cone-id').hexdigest():
        [[[hex(int(i == j)), '0x1'] for i in range(3)] for j in range(3)]}
    record['support_tables']['differential_supports'] = {
        identity: NativeSupport(row) for identity, row in zip(identities, rows(), strict=True)}
    record['support_ids'] = identities
    static = {}
    def writer(content, raw):
        if content not in identity_set:
            static[content] = raw
    by_id = record['support_tables']['differential_supports']
    def reader(content, size):
        return static[content] if content in static else M.canonical(by_id[content].record())
    metadata, arrays = M.pack_mesh(record, support_writer=writer, budget=scope.run_budget)
    checkpoint('mesh-packed')
    mesh = M.CompactMesh(metadata, arrays, support_reader=reader,
                         expected_geometry_id=metadata['geometry_id'], budget=scope.run_budget)
    return mesh, record, source, view, partition_ref


def cold(path, reference, *, progress=False):
    budget = WorkBudget(1 << 30)
    scope = create_retained_scope(budget, process_epoch='mesh-v3-cold')
    stores = IntervalStoreSet.open_catalog(Path(path), scope=scope)
    ref = SegmentRef.from_wire(reference)
    counts = []
    original = M.CompactMesh.iter_legacy_json
    def counted(self):
        counts.append(self.geometry_id)
        yield from original(self)
    with ExitStack() as patches:
        patches.enter_context(patch.object(M.CompactMesh, 'iter_legacy_json', counted))
        at = perf_counter()
        last_report = at
        phase = ['mesh-open-preparation']
        if progress:
            print(json.dumps(dict(stage='cold-start', source_sha256={name:
                sha256((HERE/name).read_bytes()).hexdigest() for name in
                ('record_views.py', 'mesh_tables.py', 'compact_store.py', 'support_source.py')})), flush=True)
            import record_views
            import partition_v2
            import support_source as support_module
            def track(original, label):
                def measured(*args, **kwargs):
                    previous, phase[0] = phase[0], label
                    print(json.dumps(dict(stage=label+'-start', seconds=perf_counter()-at)), flush=True)
                    try:
                        result = original(*args, **kwargs)
                    except BaseException as error:
                        print(json.dumps(dict(stage=label+'-failed', seconds=perf_counter()-at,
                                              error=type(error).__name__)), flush=True)
                        raise
                    else:
                        print(json.dumps(dict(stage=label+'-complete', seconds=perf_counter()-at)), flush=True)
                        return result
                    finally:
                        phase[0] = previous
                return measured
            for target, name, label in ((record_views.CompactRecord, '_validate', 'record-validation'),
                    (partition_v2.PartitionV2, '_validate_domain', 'partition-domain'),
                    (support_module.SupportSource, '__init__', 'support-inventory'),
                    (M, 'mesh_from_segment', 'mesh-validation')):
                patches.enter_context(patch.object(target, name, track(getattr(target, name), label)))
        def cancel():
            nonlocal last_report
            now = perf_counter()
            if progress and now-last_report >= 30:
                print(json.dumps(dict(stage='cold-working', phase=phase[0], seconds=now-at,
                                      held_bytes=scope.stats().retained_bytes)), flush=True)
                last_report = now
            return progress and now-at > 600
        view = CompactMeshStoreV3(stores, scope=scope).open(ref, expected_geometry_id=ref.identity.sha256,
                                                         cancel=SimpleNamespace(is_set=cancel) if progress else None)
        identity = view.identity()
        seconds = perf_counter()-at
        held = scope.stats().retained_bytes
        assert counts == [ref.identity.sha256], counts
        assert identity == ref.identity
        assert held <= 64 << 20, held
        print(json.dumps(dict(stage='cold-open', seconds=seconds, held_bytes=held,
                              logical_bytes=identity.canonical_bytes, streams=len(counts))), flush=True)
        if progress:
            support_bytes = sum(view._reader.source.identity(view._reader.source.id_at(i)).canonical_bytes
                                for i in range(view._reader.source.count))
            assert view._reader.source.count == 7700 and support_bytes > 512 << 20
            print(json.dumps(dict(stage='cold-supports', count=7700, logical_bytes=support_bytes)), flush=True)
        view.close()
    stores.close(); gc.collect(); scope.close()
    assert budget.reserved_bytes == 0, budget.statistics()


class MeshV3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mesh-v3-', dir=TASK/'_t')
        self.path = Path(self.temp.name)
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='mesh-v3-fixture')
        self.stores = IntervalStoreSet.create_migration(self.path/'catalog.json', workflow_id='a'*64, scope=self.scope)
        self.candidate = self.stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)

    def tearDown(self):
        self.candidate.close(); self.stores.close(); gc.collect(); self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())
        self.temp.cleanup()

    def test_v3_workflow_transform_composes_after_partition_v2(self):
        import ast
        import spatial_workflow_patch as W
        import partition_workflow_transform as P
        from test_partition_workflow_patch import chains
        source = P.transform_v2(P.transform(chains()[2]))
        changed = W.transform_v3(source)
        ast.parse(changed)
        self.assertNotIn('geometry, thermal = bounds.record(), mesh.record()', changed)
        self.assertIn('_thermal_header = _COMPACT_SPATIAL.X.mesh_header(mesh, self._budget)', changed)
        self.assertIn('persist_mesh=True, cancel=None, aliases=False)', changed)
        self.assertIn('persist_mesh=False, aliases=True)', changed)
        with self.assertRaises(ValueError):
            W.transform_v3(changed)

    def test_mixed_shuffled_exact_native_parity_owned_support_and_reference_reuse(self):
        import ast
        from atlas_tectonics import integration_differential_mesh as D
        import differential_mesh_patch as P
        mesh, record, source, partition, _ = fixture(self.scope, self.candidate)
        expected = D._encode_mesh_record(record)
        self.assertEqual(mesh.geometry_id, sha256(expected).hexdigest())
        adapter = CompactMeshStoreV3(self.candidate, scope=self.scope, support_source=source)
        producer = {'fixture': 'mesh-v3'}
        producer_digest = M.digest(producer)
        ref = adapter.publish(mesh, producer=producer_digest)
        original = M.CompactMesh.iter_legacy_json
        streams = []
        def counted(value):
            streams.append(value.geometry_id)
            yield from original(value)
        with patch.object(M.CompactMesh, 'iter_legacy_json', counted):
            opened = adapter.open(ref, expected_geometry_id=mesh.geometry_id)
            self.assertEqual(opened.identity(), ref.identity)
            self.assertEqual(streams, [mesh.geometry_id])
        self.assertEqual(b''.join(opened.iter_legacy_json()), expected)
        self.assertEqual(adapter.publish(opened, producer=producer_digest), ref)
        import spatial_workflow_patch as W
        envelope = W.persist_mesh(self.candidate, opened, producer, budget=self.budget)
        self.assertEqual(envelope['schema'], 'atlas.compact-mesh-store.v3')
        self.assertEqual(envelope['segment'], ref.to_wire())
        self.assertEqual(W.verify_reference(self.candidate, envelope, budget=self.budget), envelope)
        with self.assertRaisesRegex(ValueError, 'producer'):
            W.verify_reference(self.candidate, dict(envelope, source_producer={'fixture': 'changed'}), budget=self.budget)
        with self.assertRaisesRegex(ValueError, 'producer'):
            W.persist_mesh(self.candidate, opened, {'fixture': 'changed'}, budget=self.budget)
        with self.assertRaisesRegex(ValueError, 'producer'):
            adapter.publish(opened, producer='d'*64)
        with self.assertRaises(ValueError):
            W.persist_mesh(self.candidate, opened, producer, budget=self.budget,
                           support_source=object())
        del envelope
        with patch.object(source, 'check_unchanged', side_effect=ValueError('changed partition file')):
            with self.assertRaisesRegex(ValueError, 'changed partition file'):
                opened.identity()
        self.assertLessEqual(self.scope.stats().retained_bytes, 64 << 20)
        with opened._segment.metadata() as held:
            metadata = json.loads(held.value)
        self.assertNotIn('support-blobs', metadata['arrays'])
        self.assertNotIn('s.blob', metadata['arrays'])
        self.assertNotIn('s.size', metadata['arrays'])
        self.assertNotIn('support_ids', metadata['codec']['header'])
        ident = next(iter(record['support_tables']['differential_supports']))
        support = opened.support('differential_supports', ident)
        self.assertEqual(support.value, record['support_tables']['differential_supports'][ident].record())
        with self.assertRaises(RuntimeError):
            opened.close()
        with self.assertRaises(RuntimeError):
            source.close()
        support.close()
        with self.assertRaises(M.MeshTablesRefused):
            opened.storage_payload()
        raw = Path(D.__file__).read_text(encoding='utf8')
        transformed = P.transform(raw)
        self.assertNotIn('encoded = _encode_mesh_record(record)', transformed)
        old_tree, new_tree = ast.parse(raw), ast.parse(transformed)
        old = next(node for node in old_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'build_differential_mesh')
        new = next(node for node in new_tree.body if isinstance(node, ast.FunctionDef) and node.name == old.name)
        # All outer statements and the complete numerical with-body prefix are
        # unchanged; only the seven final packing/retention statements differ.
        self.assertEqual(ast.dump(ast.Module(body=old.body[:-1], type_ignores=[])),
                         ast.dump(ast.Module(body=new.body[:-1], type_ignores=[])))
        self.assertEqual(ast.dump(ast.Module(body=old.body[-1].body[:-4], type_ignores=[])),
                         ast.dump(ast.Module(body=new.body[-1].body[:-2], type_ignores=[])))
        opened.close(); del opened, mesh, record
        source.close(); partition.close()

    def test_successor_binds_partition_ancestor_without_duplicated_static_chunks(self):
        from segment_store import SegmentBackend
        mesh, record, source, partition, partition_ref = fixture(self.scope, self.candidate)
        first = CompactMeshStoreV3(self.candidate, scope=self.scope, support_source=source).publish(mesh, producer='b'*64)
        sealed = self.candidate.seal(first)
        self.stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
        self.candidate.close()
        self.candidate = self.stores.begin_interval(self.stores.head, producer_identity='b'*64, runtime_identity='c'*64)
        changed = deepcopy(record)
        changed['time_s'] = ['0x1', '0x1']
        blobs = {}
        metadata, arrays = M.pack_mesh(changed, support_writer=lambda h, raw, blobs=blobs: blobs.setdefault(h, raw), budget=self.budget)
        new = M.CompactMesh(metadata, arrays, support_reader=lambda h, n, blobs=blobs: blobs[h],
                           expected_geometry_id=metadata['geometry_id'], budget=self.budget)
        second = CompactMeshStoreV3(self.candidate, scope=self.scope, support_source=source).publish(new, producer='b'*64)
        self.assertNotEqual(first.identity, second.identity)
        self.assertEqual(self.candidate._references, {0})
        self.assertEqual(self.candidate._stats['local_chunks'], 0)
        SegmentBackend().verify(self.candidate, partition_ref, scope=self.scope)
        with SegmentBackend().open(self.candidate, second, scope=self.scope) as segment:
            with segment.info.array('static.bytes') as held:
                self.assertGreater(held.value.logical_bytes, 0)
        sealed = self.candidate.seal(second)
        self.assertEqual(tuple(i for i, _ in sealed.entry.references), (0,))
        del mesh, record, changed, new, metadata, arrays, blobs
        source.close(); partition.close()

    def test_missing_shared_support_and_foreign_scope_refused(self):
        mesh, record, source, partition, _ = fixture(self.scope, self.candidate)
        other_scope = create_retained_scope(WorkBudget(1 << 30), process_epoch='foreign-mesh')
        with self.assertRaisesRegex(ValueError, 'foreign'):
            CompactMeshStoreV3(self.candidate, scope=other_scope, support_source=source)
        other_scope.close()
        changed = deepcopy(record)
        key, support = changed['support_tables']['differential_supports'].popitem()
        altered = dict(support.record(), voxel_index=[999, 0, 0])
        changed['support_tables']['differential_supports'][M.digest(altered)] = altered
        blobs = {}
        metadata, arrays = M.pack_mesh(changed, support_writer=lambda h, raw, blobs=blobs: blobs.setdefault(h, raw), budget=self.budget)
        bad = M.CompactMesh(metadata, arrays, support_reader=lambda h, n, blobs=blobs: blobs[h],
                            expected_geometry_id=metadata['geometry_id'], budget=self.budget)
        with self.assertRaises((KeyError, ValueError)):
            CompactMeshStoreV3(self.candidate, scope=self.scope, support_source=source).publish(bad, producer='b'*64)
        del mesh, record, changed, bad, metadata, arrays, blobs, support, altered, key
        source.close(); partition.close()

    def test_sealed_second_process_reopen(self):
        mesh, record, source, partition, partition_ref = fixture(self.scope, self.candidate)
        ref = CompactMeshStoreV3(self.candidate, scope=self.scope, support_source=source).publish(mesh, producer='b'*64)
        sealed = self.candidate.seal(ref)
        self.stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
        source.close(); partition.close(); del mesh, record, partition_ref
        result = subprocess.run([sys.executable, '-B', __file__, '--cold', str(self.path/'catalog.json'),
            json.dumps(ref.to_wire())], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        print(result.stdout.strip())


def large_fixture(path):
    Path(path).mkdir(parents=True, exist_ok=False)
    budget = WorkBudget(2 << 30)
    scope = create_retained_scope(budget, process_epoch='mesh-v3-large')
    stores = IntervalStoreSet.create_migration(Path(path)/'catalog.json', workflow_id='a'*64, scope=scope)
    candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
    print(json.dumps(dict(stage='large-start', supports=7700, shared_coverage_bytes=81920)), flush=True)
    at = perf_counter()
    def checkpoint(stage, **fields):
        print(json.dumps(dict(stage=stage, seconds=perf_counter()-at, **fields)), flush=True)
    mesh, record, source, partition, partition_ref = fixture(scope, candidate, count=7700,
                                                           coverage_bytes=81920, checkpoint=checkpoint)
    print(json.dumps(dict(stage='large-built', seconds=perf_counter()-at,
                          descriptor_logical_bytes=partition_ref.identity.canonical_bytes)), flush=True)
    assert partition_ref.identity.canonical_bytes > 600 << 20
    ref = CompactMeshStoreV3(candidate, scope=scope, support_source=source).publish(mesh, producer='b'*64)
    checkpoint('mesh-published', reference=ref.to_wire())
    sealed = candidate.seal(ref)
    stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
    support_bytes = sum(source.identity(source.id_at(i)).canonical_bytes for i in range(source.count))
    assert support_bytes > 512 << 20
    from segment_store import SegmentBackend, parse
    with SegmentBackend().open(stores, ref, scope=scope) as segment:
        with segment.metadata() as held:
            metadata = parse(held.value)
        columns = metadata['arrays']
    receipt = dict(stage='large-published', seconds=perf_counter()-at, reference=ref.to_wire(),
                   partition_reference=partition_ref.to_wire(), support_logical_bytes=support_bytes,
                   mesh_columns=columns, stored_file_bytes=sum(item.stat().st_size for item in Path(path).rglob('*') if item.is_file()),
                   provenance='synthetic high-sharing fixture; repeated 81920-byte coverage token')
    Path(path, 'mesh-v3-reference.json').write_text(json.dumps(receipt, sort_keys=True), encoding='utf8')
    print(json.dumps(receipt), flush=True)
    source.close(); partition.close(); del mesh, record
    candidate.close(); stores.close(); gc.collect(); scope.close()
    assert budget.reserved_bytes == 0, budget.statistics()


def inspect_large(path):
    """Recover bounded fixture evidence from a completed sealed publication."""
    from segment_store import SegmentBackend, parse
    budget = WorkBudget(1 << 30)
    scope = create_retained_scope(budget, process_epoch='mesh-v3-large-inspect')
    stores = IntervalStoreSet.open_catalog(Path(path)/'catalog.json', scope=scope)
    ref = stores.head.head
    with SegmentBackend().open(stores, ref, scope=scope) as segment:
        with segment.metadata() as held:
            metadata = parse(held.value)
    partition_ref = SegmentRef.from_wire(metadata['support_source']['partition'])
    assert partition_ref.identity.canonical_bytes > 600 << 20
    _, examples = tiny_partition(budget, count=1, depth=0)
    base = dict(examples[0], coverage='x'*81920)
    support_bytes = sum(len(M.canonical(dict(base, voxel_index=[i, 0, 0]))) for i in range(7700))
    assert support_bytes > 512 << 20
    receipt = dict(stage='large-published', reference=ref.to_wire(),
                   partition_reference=partition_ref.to_wire(), support_logical_bytes=support_bytes,
                   mesh_columns=metadata['arrays'],
                   stored_file_bytes=sum(item.stat().st_size for item in Path(path).rglob('*') if item.is_file()),
                   provenance='synthetic high-sharing fixture; repeated 81920-byte coverage token',
                   inspection='recovered from sealed catalog after post-publication fixture resolver error')
    Path(path, 'mesh-v3-reference.json').write_text(json.dumps(receipt, sort_keys=True), encoding='utf8')
    print(json.dumps(receipt), flush=True)
    stores.close(); gc.collect(); scope.close()
    assert budget.reserved_bytes == 0, budget.statistics()


def profile_large(path, *, warmed=False):
    """Forty bounded reads, without constructing/validating the large record."""
    import cProfile
    import pstats
    import math
    import numpy as np
    from record_views import _Segment
    from segment_store import SegmentBackend, SegmentView, parse
    receipt = json.loads(Path(path, 'mesh-v3-reference.json').read_text(encoding='utf8'))
    budget = WorkBudget(1 << 30)
    scope = create_retained_scope(budget, process_epoch='mesh-v3-large-profile')
    stores = IntervalStoreSet.open_catalog(Path(path)/'catalog.json', scope=scope)
    ref = SegmentRef.from_wire(receipt['partition_reference'])
    with SegmentBackend().open(stores, ref, scope=scope) as segment:
        with segment.metadata() as held:
            metadata = parse(held.value)
        sizes = {name: math.prod(row['shape'])*np.dtype(row['dtype']).itemsize
                 for name, row in metadata['arrays'].items()}
        large = sorted((size, name) for name, size in sizes.items() if size > 65536)
        assert large, sizes
        size, name = large[-1]
        columns = _Segment(segment, metadata['arrays'])
        reads = []
        original = SegmentView.read
        def counted(self, *args, **kwargs):
            reads.append(args)
            return original(self, *args, **kwargs)
        profile = cProfile.Profile()
        with patch.object(SegmentView, 'read', counted), columns.read_batch():
            if warmed:
                columns.value('node.kind', 0)
                columns.value('edge.child', 0)
                reads.clear()
            at = perf_counter()
            profile.enable()
            if warmed:
                for column in ('node.kind', 'edge.child'):
                    for i in range(2000):
                        columns.value(column, i)
            else:
                for i in range(20):
                    columns.value(name, i)
                for i in range(20):
                    with columns.raw(name, i, i+1):
                        pass
            profile.disable()
        print(json.dumps(dict(stage='large-profile-warm' if warmed else 'large-profile', column=name, bytes=size,
                              large_columns=large, seconds=perf_counter()-at,
                              underlying_reads=len(reads),
                              source_sha256=sha256((HERE/'record_views.py').read_bytes()).hexdigest())), flush=True)
        pstats.Stats(profile).sort_stats('cumulative').print_stats(15)
        del columns
    stores.close(); gc.collect(); scope.close()
    assert budget.reserved_bytes == 0, budget.statistics()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--cold':
        cold(sys.argv[2], json.loads(sys.argv[3]))
    elif len(sys.argv) > 1 and sys.argv[1] == '--large':
        large_fixture(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == '--profile-large':
        profile_large(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == '--profile-large-warm':
        profile_large(sys.argv[2], warmed=True)
    elif len(sys.argv) > 1 and sys.argv[1] == '--inspect-large':
        inspect_large(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == '--cold-large':
        receipt = json.loads(Path(sys.argv[2], 'mesh-v3-reference.json').read_text(encoding='utf8'))
        cold(Path(sys.argv[2])/'catalog.json', receipt['reference'], progress=True)
    else:
        unittest.main()
