"""(b') G-R3-1: storage's five conditions for the compact, unpublished JC 408 mesh (16 Oct 2026).

The joined control builds its end thermal mesh compact and unpublished in the workflow
store's scope (publish_mesh_patch.mesh_context, used by the r8 joined helper);
CollarWorkflow._publish publishes it after its partition, from the support source of that
published partition (publish_mesh_patch.transform, a Step 10 chain stage).

1. The build shares every differential support with the partition: none is copied into
   'mesh-static-supports' (the native tuple's rows would be).
2. The v3 root _publish publishes is byte-identical to the one the build-time publish of
   option (a) writes for the same produced view, and the partition root is the same.
3. Nothing after publication opens the mesh by its reference: the publication check, the
   in-memory identity and stream reads pass with mesh_from_segment and
   CompactMeshStoreV3.open forbidden, and the only by-reference openers are restore paths.
4. The build writes nothing, so the store token stays current from inspect() to _publish.
5. One producer for both roots: the transformed _publish passes one expression, and
   published_support_source refuses a partition root with another producer.
"""
import ast
import gc
import importlib
import shutil
import sys
import tempfile
import unittest
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import exterior_mesh_patch
import mimetic_patch
import partition_native_patch

HERE = Path(__file__).resolve().parent
R = HERE.parent
TASK = HERE.parents[4]
BASE = HERE.parents[1]/'runtime-integration-r1'
CHAIN_R3 = (R.parents[2]/'claude-review-steps1-7-20261015'/'fixes'/'r3'/'final'/'generated'/'gen_r3'/
            'integration_regional_workflow.py')
SOURCE_PRODUCER = {'kind': 'test-publish-mesh-b-prime'}
_temporary = _old_path = PRODUCER = None
# Bound by setUpModule once the composed runtime is first on sys.path.
compact_store = L = M = N = P = SI = Y = CRS = PN = None


def setUpModule():
    """The runtime as test_live_mesh_published composes it: the base package with the exterior
    mesh and mimetic transforms (ExteriorMesh.from_compact), in a fresh process."""
    global _temporary, _old_path, PRODUCER, compact_store, L, M, N, P, SI, Y, CRS, PN
    if any(name == 'atlas_tectonics' or name.startswith('atlas_tectonics.') for name in sys.modules):
        raise RuntimeError('fresh process required; no live runtime patching')
    (TASK/'_t').mkdir(exist_ok=True)
    _temporary = tempfile.TemporaryDirectory(prefix='publish-mesh-', dir=TASK/'_t')
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(BASE/'runtime-src'/'atlas_tectonics', package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name, transform in (('integration_exterior_mesh.py', exterior_mesh_patch.transform),
                            ('integration_mimetic_heat.py', mimetic_patch.mimetic_source),
                            ('integration_differential_geometry.py', partition_native_patch.transform)):
        target = package/name
        target.write_text(transform(target.read_text(encoding='utf8')), encoding='utf8')
    _old_path = list(sys.path)
    sys.path[:0] = [str(Path(_temporary.name)), str(BASE/'ram'), str(BASE/'helpers'), str(R),
                    str(HERE.parents[3]/'heat-repair-20261007')]
    importlib.import_module('atlas_tectonics.integration_exterior_mesh')
    compact_store = importlib.import_module('compact_store')
    L, M = importlib.import_module('live_mesh_patch'), importlib.import_module('mesh_tables')
    N, P = importlib.import_module('native_transfer'), importlib.import_module('publish_mesh_patch')
    SI, Y = importlib.import_module('spatial_indexed_patch'), importlib.import_module('spatial_workflow_patch')
    CRS, PN = importlib.import_module('compact_restart_store'), importlib.import_module('partition_native_patch')
    PRODUCER = sha256(N._json(SOURCE_PRODUCER)).hexdigest()


def tearDownModule():
    if _old_path is not None:
        sys.path[:] = _old_path
    if _temporary is not None:
        _temporary.cleanup()


def runtime():
    """The composed runtime's constructors, imported after setUpModule put it first."""
    from atlas_tectonics.resources import WorkBudget
    from content_cache import create_retained_scope
    from interval_store_set import IntervalStoreSet
    from partition_store import publish_partition_v2
    from partition_tables import pack_partition_v2
    from support_source import support_source
    from test_mesh_tables import small_mesh_record
    from test_mesh_v3 import NativeSupport
    from test_partition_tables import tiny_partition
    return SimpleNamespace(WorkBudget=WorkBudget, create_retained_scope=create_retained_scope,
                           IntervalStoreSet=IntervalStoreSet, publish_partition_v2=publish_partition_v2,
                           pack_partition_v2=pack_partition_v2, support_source=support_source,
                           small_mesh_record=small_mesh_record, NativeSupport=NativeSupport,
                           tiny_partition=tiny_partition)


class Arm:
    """One candidate holding a published partition v2 and an end-mesh record over it.

    As test_mesh_v3.fixture, with the partition published under ``producer`` and the
    record's differential supports either compact (support_table of the _Supports
    sequence, what JC 408 builds from) or the native tuple's rows.
    """

    def __init__(self, stack, label, *, producer=None, count=3):
        rt = runtime()
        temp = tempfile.TemporaryDirectory(prefix='pm-'+label+'-', dir=TASK/'_t')
        stack.callback(temp.cleanup)
        self.budget = rt.WorkBudget(1 << 30)
        stack.callback(lambda: unittest.TestCase().assertEqual(self.budget.reserved_bytes, 0,
                                                               self.budget.statistics()))
        self.scope = rt.create_retained_scope(self.budget, process_epoch='publish-mesh-'+label)
        stack.callback(self.scope.close)
        stack.callback(gc.collect)
        self.stores = rt.IntervalStoreSet.create_migration(Path(temp.name)/'catalog.json', workflow_id='a'*64,
                                                           scope=self.scope)
        stack.callback(self.stores.close)
        self.candidate = self.stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        stack.callback(self.candidate.close)
        body, examples = rt.tiny_partition(self.budget, count=1, depth=0)
        base = examples[0]
        rows = [dict(base, voxel_index=[i, 0, 0]) for i in range(count)]
        identities = [M.digest(row) for row in rows]
        body['support_ids'] = identities[::-1]
        self.view = rt.pack_partition_v2(body, reversed(rows), expected_partition_id=M.digest(body), scope=self.scope)
        stack.callback(self.view.close)
        self.partition_ref = rt.publish_partition_v2(self.candidate, self.view, producer=producer or PRODUCER)
        self.source = rt.support_source(self.view)
        stack.callback(self.source.close)
        stack.callback(self.drop)
        record = rt.small_mesh_record(self.budget)
        record['support_tables']['radial_layers'] = {sha256(b'static-radial-id').hexdigest(): base['radial_layer']}
        record['support_ids'] = identities
        self.native_rows = {identity: rt.NativeSupport(row) for identity, row in zip(identities, rows, strict=True)}
        self.compact_rows = L.support_table(PN._Supports(self.view))
        self.record = record

    def drop(self):
        self.record = self.native_rows = self.compact_rows = None

    def held(self, *, compact=True):
        tables = dict(self.record['support_tables'],
                      differential_supports=self.compact_rows if compact else self.native_rows)
        return M.OwnedRow(dict(self.record, support_tables=tables), M._Allocation(self.budget, 65536))

    def build(self, context, *, compact=True):
        return L.finish(self.held(compact=compact), budget=self.budget, context=context)

    def option_a(self):
        return {'resolver': self.candidate, 'support_source': self.source, 'producer': PRODUCER}


def tripwire(*_, **__):
    raise AssertionError('mesh opened by its reference')


class MeshContextTests(unittest.TestCase):
    def test_native_or_same_scope_compact_supports_and_no_context_without_a_scope(self):
        with ExitStack() as stack:
            arm = Arm(stack, 'context')
            workflow = SimpleNamespace(_store=SimpleNamespace(scope=arm.scope))
            partition = SimpleNamespace(supports=PN._Supports(arm.view))
            self.assertEqual(P.mesh_context(workflow, partition), {'scope': arm.scope})
            self.assertIsNone(P.mesh_context(SimpleNamespace(_store=SimpleNamespace()), partition))
            # The selected partition route issues native proposals: their supports are copied in memory.
            native = SimpleNamespace(supports=tuple(arm.native_rows.values()))
            self.assertEqual(P.mesh_context(workflow, native), {'scope': arm.scope})
            with self.assertRaisesRegex(P.PublishMeshRefused, 'sealed proposal partition v2 in the store scope'):
                P.mesh_context(workflow, SimpleNamespace(supports=list(arm.native_rows.values())))
            rt = runtime()
            other = rt.create_retained_scope(rt.WorkBudget(1 << 20), process_epoch='publish-mesh-foreign')
            stack.callback(other.close)
            with self.assertRaisesRegex(P.PublishMeshRefused, 'sealed proposal partition v2 in the store scope'):
                P.mesh_context(SimpleNamespace(_store=SimpleNamespace(scope=other)), partition)

    def test_the_end_mesh_note_records_shared_or_copied_supports(self):
        P.END_MESH_SUPPORTS.clear()
        with ExitStack() as stack:
            arm = Arm(stack, 'note')
            compact = arm.build({'scope': arm.scope})
            shared = P.note_end_mesh(SimpleNamespace(supports=PN._Supports(arm.view)), compact, arm.budget)
            self.assertEqual((shared['supports'], shared['copied_support_bytes'], shared['compact_mesh']),
                             ('shared', 0, True))
            rows = tuple(SimpleNamespace(_json=b'x'*n) for n in (3, 5))
            copied = P.note_end_mesh(SimpleNamespace(supports=rows), compact, arm.budget)
            self.assertEqual((copied['supports'], copied['differential_supports'], copied['copied_support_bytes']),
                             ('copied', 2, 8))
            self.assertGreater(copied['mesh_static_supports_booked_bytes'], 0)
            self.assertEqual(P.END_MESH_SUPPORTS, [shared, copied])
            del compact
        P.END_MESH_SUPPORTS.clear()


class PartitionPublicationTests(unittest.TestCase):
    """Condition 2 (redefined): one conversion in _publish gives today's payload header and root."""

    def candidate(self, stack, label):
        rt = runtime()
        temp = tempfile.TemporaryDirectory(prefix='pp-'+label+'-', dir=TASK/'_t')
        stack.callback(temp.cleanup)
        budget = rt.WorkBudget(1 << 30)
        stack.callback(lambda: self.assertEqual(budget.reserved_bytes, 0, budget.statistics()))
        scope = rt.create_retained_scope(budget, process_epoch='partition-publication-'+label)
        stack.callback(scope.close)
        stack.callback(gc.collect)
        stores = rt.IntervalStoreSet.create_migration(Path(temp.name)/'catalog.json', workflow_id='a'*64, scope=scope)
        stack.callback(stores.close)
        candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        stack.callback(candidate.close)
        return budget, candidate

    def native_partition(self, budget):
        from atlas_tectonics import integration_differential_geometry as D
        body, supports = runtime().tiny_partition(budget)
        funding = SimpleNamespace(funding_id=body['funding_id'], _resource=budget,
                                  descriptor=lambda: {'source': body['source']})
        collar = SimpleNamespace(plan_id=body['collar_plan_id'], _budget=budget)
        interval = D._issue(D.DifferentialInterval, {'fixture': 'typed restore protocol only'}, budget)
        body.update(scope='physical-interval', current_geometry_id=None, interval_id=interval.interval_id)
        partition = D.DifferentialPartition.restore(dict(partition_id=D._record_hash(body), **body, supports=supports),
                                                    funding, collar, interval, budget=budget)
        return partition, interval, funding, collar

    def test_one_conversion_publishes_todays_header_and_root(self):
        import partition_workflow_patch as PW
        published = []
        for label, convert_first in (('today', False), ('bprime', True)):
            with ExitStack() as stack:
                budget, candidate = self.candidate(stack, label)
                partition, interval, funding, collar = self.native_partition(budget)
                calls = []
                with mock.patch.object(PW, 'convert_native', side_effect=PW.convert_native) as counted:
                    target = (P.compact_partition(partition, interval, funding, collar, budget, candidate)
                              if convert_first else partition)
                    with PW.payload(None, target, interval, funding, collar, budget, store=candidate,
                                    source_producer=SOURCE_PRODUCER) as (header, arrays):
                        result = {'header': dict(header), 'arrays': arrays}
                    if convert_first:
                        source = P.published_support_source(target, candidate, stack, source_producer=SOURCE_PRODUCER)
                        result['binding'] = source.binding.to_wire()
                    calls.append(counted.call_count)
                    counted.reset_mock()                    # the mock's call record holds the partition
                self.assertEqual(calls, [1])            # converted once either way: inside payload, or before it
                result['rows'] = candidate._db.execute('SELECT id, body FROM snapshots ORDER BY id').fetchall()
                result['chunks'] = candidate._db.execute('SELECT id, stored_sha FROM chunks ORDER BY id').fetchall()
                published.append(result)
                del partition, target, header, interval, funding, collar
        today, bprime = published
        self.assertEqual(bprime.pop('binding')['partition'], today['header']['compact_partition'])
        self.assertEqual(today, bprime)

    def test_a_scope_less_store_or_a_compact_partition_is_returned_unchanged(self):
        with ExitStack() as stack:
            budget, candidate = self.candidate(stack, 'unchanged')
            partition, interval, funding, collar = self.native_partition(budget)
            self.assertIs(P.compact_partition(partition, interval, funding, collar, budget, SimpleNamespace()), partition)
            compact = P.compact_partition(partition, interval, funding, collar, budget, candidate)
            self.assertIsNot(compact, partition)
            self.assertIs(P.compact_partition(compact, interval, funding, collar, budget, candidate), compact)
            self.assertEqual(compact.partition_id, partition.partition_id)
            del partition, compact, interval, funding, collar


class ConditionTests(unittest.TestCase):
    def test_1_the_build_shares_every_differential_support_with_the_partition(self):
        captured = []
        original = L._pack

        def capture(held, **kwargs):
            result = original(held, **kwargs)
            captured.append(set(result[4][0].value))
            return result
        with ExitStack() as stack:
            arm = Arm(stack, 'shared')
            ids = set(arm.compact_rows)
            with mock.patch.object(L, '_pack', capture):
                compact = arm.build({'scope': arm.scope})
                native = arm.build({'scope': arm.scope}, compact=False)
            self.assertEqual(len(captured), 2)
            self.assertFalse(captured[0] & ids, "a differential support was copied into 'mesh-static-supports'")
            self.assertEqual(captured[1] & ids, ids)       # the mutant: the native tuple's rows are copied
            self.assertEqual(compact.geometry_id, native.geometry_id)
            del compact, native

    def test_2_the_published_root_is_byte_identical_to_the_build_time_publish(self):
        with ExitStack() as stack:
            a, b = Arm(stack, 'a'), Arm(stack, 'b')
            self.assertEqual(a.partition_ref.to_wire(), b.partition_ref.to_wire())
            built = a.build(a.option_a())                   # option (a): published inside the build
            ref = built._compact._segment.info.ref
            produced = b.build({'scope': b.scope})          # (b'): unpublished, then _publish's route
            self.assertIsNone(produced._compact._segment)
            reference = Y.persist_mesh(b.candidate, produced._compact, SOURCE_PRODUCER, budget=b.budget,
                                       scope=b.scope, support_source=b.source)
            self.assertEqual(reference['segment'], ref.to_wire())
            key = ref.to_wire()['root_key']['snapshot_key']
            rows = [arm.candidate._db.execute('SELECT body FROM snapshots WHERE id=?', (key,)).fetchone()
                    for arm in (a, b)]
            self.assertIsNotNone(rows[0])
            self.assertEqual(rows[0], rows[1])
            for arm in (a, b):
                chunks = arm.candidate._db.execute('SELECT id, stored_sha FROM chunks ORDER BY id').fetchall()
                arm.chunks = chunks
            self.assertEqual(a.chunks, b.chunks)
            del built, produced, reference

    def test_2b_native_supports_publish_the_same_root_and_cost_a_copy(self):
        """The selected partition route issues native proposals: the mesh copies supports in memory only."""
        with ExitStack() as stack:
            a, b = Arm(stack, 'na'), Arm(stack, 'nb')
            built = a.build(a.option_a())
            ref = built._compact._segment.info.ref
            produced = b.build({'scope': b.scope}, compact=False)
            reference = Y.persist_mesh(b.candidate, produced._compact, SOURCE_PRODUCER, budget=b.budget,
                                       scope=b.scope, support_source=b.source)
            self.assertEqual(reference['segment'], ref.to_wire())
            for arm in (a, b):
                arm.chunks = arm.candidate._db.execute('SELECT id, stored_sha FROM chunks ORDER BY id').fetchall()
            self.assertEqual(a.chunks, b.chunks)
            del built, produced, reference

    def test_3_nothing_after_publication_opens_the_mesh_by_reference(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(M, 'mesh_from_segment', tripwire))
            stack.enter_context(mock.patch.object(compact_store.CompactMeshStoreV3, 'open', tripwire))
            arm = Arm(stack, 'trace')
            produced = arm.build({'scope': arm.scope})
            view = produced._compact
            reference = Y.persist_mesh(arm.candidate, view, SOURCE_PRODUCER, budget=arm.budget, scope=arm.scope,
                                       support_source=arm.source)
            Y.verify_reference(arm.candidate, dict(reference), budget=arm.budget)   # the publication check
            identity = view.identity()
            self.assertEqual((identity.sha256, view.geometry_id), (reference['geometry_id'],)*2)
            stream = b''.join(SI.iter_logical_json(view))
            self.assertEqual(sha256(stream).hexdigest(), view.geometry_id)
            del produced, view, reference, stream

    def test_3_by_reference_mesh_opens_are_restore_paths_only(self):
        found = set()
        for path in [*sorted(HERE.glob('*.py')), *sorted(R.glob('*.py'))]:
            if path.name.startswith(('test_', 'measure_', 'profile_', 'probe_')) or 'ref_' in path.name:
                continue
            tree = ast.parse(path.read_text(encoding='utf8'))
            for qualname, function in _functions(tree):
                for node in ast.walk(function):
                    if not isinstance(node, ast.Call):
                        continue
                    name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
                    receiver = getattr(node.func, 'value', None)
                    opens_v3 = (name == 'open' and isinstance(receiver, ast.Call) and
                                getattr(receiver.func, 'id', None) == 'CompactMeshStoreV3')
                    if name == 'mesh_from_segment' or opens_v3:
                        found.add((path.name, qualname))
        # CompactMeshStoreV3.open runs mesh_from_segment through its _prepare_open.
        self.assertEqual(found, {('compact_store.py', 'CompactMeshStoreV3._prepare_open'),
                                 ('spatial_records_patch.py', 'restore_records'),
                                 ('spatial_workflow_patch.py', 'restore_records'),
                                 ('materialise_endpoint.py', 'materialise')})
        if not CHAIN_R3.is_file():
            self.skipTest('Step 10 chain text moved')
        tree = ast.parse(P.transform(CHAIN_R3.read_text(encoding='utf8')))
        callers = {qualname for qualname, function in _functions(tree) for node in ast.walk(function)
                   if isinstance(node, ast.Call) and getattr(node.func, 'attr', None) == '_spatial_restore_records'}
        # Only the root open and a full _refresh restore spatial records by reference; after
        # _publish, R2's adopted token (or compact_restart_patch.postpublication) keeps _refresh short.
        self.assertEqual(callers, {'CollarWorkflow.open', 'CollarWorkflow._refresh'})

    def test_4_the_build_writes_nothing_so_the_token_stays_current(self):
        with ExitStack() as stack:
            arm = Arm(stack, 'token')
            store = stack.enter_context(CRS.CompactRestartStore(arm.candidate, scope=arm.scope))
            token, counters = store.change_token(), dict(arm.candidate.local_statistics())
            produced = arm.build({'scope': arm.scope})
            self.assertEqual((store.change_token(), arm.candidate.local_statistics()), (token, counters))
            built = arm.build(arm.option_a())               # the test can see a write: option (a)'s does move it
            self.assertNotEqual(store.change_token(), token)
            del produced, built

    def test_5_one_producer_names_both_roots(self):
        if not CHAIN_R3.is_file():
            self.skipTest('Step 10 chain text moved')
        tree = ast.parse(P.transform(CHAIN_R3.read_text(encoding='utf8')))
        publish = dict(_functions(tree))['CollarWorkflow._publish']
        producers = {}
        for node in ast.walk(publish):
            if isinstance(node, ast.Call):
                name = getattr(node.func, 'attr', None)
                for keyword in node.keywords:
                    if keyword.arg == 'source_producer' and name in ('_partition_payload', 'published_support_source',
                                                                     '_spatial_records'):
                        producers.setdefault(name, set()).add(ast.unparse(keyword.value))
        self.assertEqual(producers, {name: {'_COMPACT_SPATIAL.producer(self._collar)'} for name in
                                     ('_partition_payload', 'published_support_source', '_spatial_records')})
        with ExitStack() as stack:
            arm = Arm(stack, 'producer')
            partition = SimpleNamespace()
            with mock.patch.object(PN, 'compact_view', lambda _: arm.view):
                scratch = stack.enter_context(ExitStack())
                source = P.published_support_source(partition, arm.candidate, scratch, source_producer=SOURCE_PRODUCER)
                self.assertEqual(source.binding.to_wire(), arm.source.binding.to_wire())
                with self.assertRaisesRegex(P.PublishMeshRefused, 'partition and mesh producers differ'):
                    P.published_support_source(partition, arm.candidate, scratch, source_producer={'kind': 'other'})
            self.assertIsNone(P.published_support_source(partition, SimpleNamespace(), scratch,
                                                         source_producer=SOURCE_PRODUCER))
            del source


class JoinedHelperSeamTests(unittest.TestCase):
    """r8's JC 408 and JC 428 seams and its failure capture, on a compact, unpublished mesh."""

    def test_mesh_options_pass_no_keyword_for_a_native_store(self):
        with ExitStack() as stack:
            arm = Arm(stack, 'options')
            partition = SimpleNamespace(supports=PN._Supports(arm.view))
            self.assertEqual(P.mesh_options(SimpleNamespace(_store=SimpleNamespace(scope=arm.scope)), partition),
                             {'compact_context': {'scope': arm.scope}})
            self.assertEqual(P.mesh_options(SimpleNamespace(_store=SimpleNamespace()), partition), {})

    def test_required_boundary_faces_are_read_by_index_in_record_order(self):
        with ExitStack() as stack:
            arm = Arm(stack, 'required')
            faces = [row['face_id'] for row in arm.record['faces']]
            required = [faces[1], faces[0]]
            arm.record['required_thermal_boundary_faces'] = required
            mesh = arm.build({'scope': arm.scope})
            with self.assertRaisesRegex(Exception, 'compact mesh requires indexed access'):
                mesh.record()                                # JC 428's original read refuses
            self.assertEqual(P.required_boundary_faces(mesh), required)
            del arm.record['required_thermal_boundary_faces']
            bare = arm.build({'scope': arm.scope})
            with self.assertRaises(KeyError):
                P.required_boundary_faces(bare)              # as the native record lookup
            native = SimpleNamespace(_compact=None, record=lambda: {'required_thermal_boundary_faces': required})
            self.assertEqual(P.required_boundary_faces(native), required)
            del mesh, bare

    def test_failure_capture_records_a_compact_mesh_identity(self):
        import json
        with ExitStack() as stack:
            arm = Arm(stack, 'failure')
            mesh = arm.build({'scope': arm.scope})
            part, size = P.failure_mesh_operand(mesh)
            self.assertEqual((part, size), ({'compact_unpublished_mesh': {
                'geometry_id': mesh.geometry_id, 'cells': mesh.cell_count, 'faces': mesh.face_count}}, 4096))
            json.dumps(part)
            native = SimpleNamespace(_compact=None, record=dict, _json=b'{"x":1}')
            self.assertEqual(P.failure_mesh_operand(native), (native.record, 7))
            del mesh


class TransformTests(unittest.TestCase):
    def test_chain_text_changes_publish_and_spatial_records_only(self):
        if not CHAIN_R3.is_file():
            self.skipTest('Step 10 chain text moved')
        source = CHAIN_R3.read_text(encoding='utf8')
        self.assertEqual(sha256(source.encode()).hexdigest()[:8], '507942b2')
        result = P.transform(source)
        self.assertEqual(result.count(P.MARK), 2)
        self.assertEqual(result.count('support_source = _PUBLISH_MESH.published_support_source('), 1)
        with self.assertRaisesRegex(P.PublishMeshRefused, 'unapplied workflow source text required'):
            P.transform(result)
        with self.assertRaisesRegex(P.PublishMeshRefused, 'anchor missing or ambiguous: partition publication'):
            P.transform(source.replace(P.PARTITION, P.PARTITION.replace('header', 'header ', 1)))


def _functions(tree):
    found = []

    def walk(nodes, prefix):
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                walk(node.body, prefix+node.name+'.')
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.append((prefix+node.name, node))
    walk(tree.body, '')
    return found


if __name__ == '__main__':
    unittest.main()
