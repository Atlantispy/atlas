"""Compact historical parent materialisation (X-7), M7 verify dispatch, M23 wiring.

Actual tiny native transfer, collar, funding and spatial owners come from the
w1a CompactParentFixture; the parent is test_partition_tables' native-schema
record carrying the synthetic historical header. SYNTHETIC FIXTURE INPUTS ONLY:
no historical database, admission issuer, runtime compatibility or solve. Real
ArrayStores, the original-blob decoder, codec, partition store, geometry
transfer and native admission run unpatched; patches only forbid a route or
count calls. The package is composed exactly as in
R/test_geometry_transfer_compact: partition_native_patch -> endpoint seam
(staged) -> geometry_transfer(compact=True).
"""
import ast
from contextlib import contextmanager, ExitStack
import gc
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[4]
sys.path.insert(0, str(HERE.parent))
import test_geometry_transfer_compact as GC

# The unchanged legacy parent statements (materialise_endpoint c660ad6d, lines 231-238).
LEGACY_PARENT = '''
parent_arrays = H.read_selected_arrays(original_store, head['key'], ['partition-record:partition'],
    admission=admission, budget=budget, check=check)
with partition_record(head['differential_partition'], parent_arrays, budget) as decoded:
    bridge = G.bind_parent_geometry(native_transfer=transferred, partition_descriptor=decoded.value,
        geometry=interval, funding=spatial.funding, collar=collar, budget=budget)
    partition = D.DifferentialPartition.restore(decoded.value, spatial.funding, collar, interval,
                                               budget=budget, _runtime_transfer=bridge)
del decoded, parent_arrays
'''


def setUpModule():
    global np, E, W, H, G, N, M, MT, PT, PS, PW, Y, CW, ArrayStore, StoreLimits, Compression
    GC.install('pm-')
    import numpy as np
    import materialise_endpoint as E
    import workflow_transfer as W
    import historical_admission as H
    import geometry_transfer as G
    import native_transfer as N
    import mesh_tables as M
    import partition_tables as PT
    import partition_store as PS
    import partition_workflow_patch as PW
    import spatial_workflow_patch as Y
    import test_mesh_tables as MT
    from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow as CW
    assert PT is GC.PT and G is GC.G and Path(E.__file__).parent == HERE.parent


def tearDownModule():
    GC.uninstall()


def limits():
    return StoreLimits(chunk_bytes=256, max_array_bytes=2 << 20, max_store_bytes=16 << 20,
                       max_manifest_bytes=256 << 10, sqlite_cache_bytes=65536, codec_workspace_bytes=65536)


def fixture_admission(capsule, budget):
    """Test-only issuance carrying only the original manifest; never a public issuer."""
    encoded = (W.canonical(capsule), W.canonical({'capsule_sha256': H.digest(capsule),
                                                  'fixture': 'SYNTHETIC FIXTURE ONLY'}))
    allocation = N._Allocation(budget, sum(map(len, encoded))+4096, category='fixture-admission-retained')
    admission = object.__new__(W.HistoricalEndpointAdmission)
    object.__setattr__(admission, '_record', N._RecordBytes(encoded[0], allocation))
    object.__setattr__(admission, '_binding', N._RecordBytes(encoded[1], allocation))
    object.__setattr__(admission, '_source_audit', None)
    return admission


@contextmanager
def forbidden(*targets):
    """Refuse a route outright; the code under test itself is never replaced."""
    with ExitStack() as stack:
        for owner, name in targets:
            stack.enter_context(mock.patch.object(owner, name,
                side_effect=AssertionError('forbidden route: '+name)))
        yield


@contextmanager
def no_whole_export():
    original = PT.CompactPartition.legacy_record
    def selected_only(instance, ref=None):
        if ref is None or ref.index == instance._body:
            raise AssertionError('whole partition export forbidden')
        return original(instance, ref)
    with mock.patch.object(PT.CompactPartition, 'legacy_record', selected_only):
        yield


def keywords(call):
    return {k.arg: ast.unparse(k.value) for k in call.keywords}


class PartitionMaterialiseTests(GC.CompactParentFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.temporary = tempfile.TemporaryDirectory(prefix='.pm-', dir=WORKSPACE)
        root = Path(self.temporary.name)
        self.descriptor = GC.descriptor(self.body, self.supports)
        self.raw = W.canonical(self.descriptor)
        self.refs = {'partition': dict(array='partition-record:partition', bytes=len(self.raw),
                                       sha256=sha256(self.raw).hexdigest())}
        self.header = CW._partition_header(self.descriptor, self.refs)
        self.head = {'key': GC.T.ident('historical head'), 'differential_partition': self.header}
        self.original = ArrayStore(root/'original.sqlite', limits(), budget=self.budget)
        self.original.put(self.head['key'], {'partition-record:partition': np.frombuffer(self.raw, dtype=np.uint8)},
                          {'differential_partition': self.header}, budget=self.budget)
        with self.original._read_scope():
            manifest = self.original._manifest(self.head['key'])
        self.admission = fixture_admission({'snapshot_manifests': {self.head['key']: manifest}}, self.budget)
        self.working = ArrayStore(root/'working.sqlite', limits(), budget=self.budget)
        self.producer = Y.producer(self.collar)

    def tearDown(self):
        self.working.close()
        self.original.close()
        self.admission = None
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline, self.budget.statistics())
        self.temporary.cleanup()
        super().tearDown()

    def arguments(self, store, **changes):
        return dict(dict(original_store=self.original, working_store=store, admission=self.admission,
            head=self.head, native_transfer=self.fixture.native_owned, interval=self.geometry,
            funding=self.funding, collar=self.collar, budget=self.budget, check=lambda: None, phase=None), **changes)

    def readonly(self, path):
        pin = sha256(Path(path).read_bytes()).hexdigest()
        return H.open_successor_readonly(path, expected_sha256=pin, limits=limits(), compression=Compression(),
                                         budget=self.budget), pin

    def test_conversion_exact_transfer_and_reuse_without_partition_json(self):
        checks, phases, calls = [0], [], []
        def check():
            checks[0] += 1
        real = PW.historical_partition
        def spy(**kwargs):
            calls.append(dict(kwargs))
            return real(**kwargs)
        before = self.working.statistics()['snapshots']
        with mock.patch.object(PW, 'historical_partition', spy):
            bridge, part = E.compact_parent_partition(**self.arguments(self.working, check=check, phase=phases.append))
        # One conversion and root publication; the runner's forced check passes unwrapped.
        self.assertEqual(phases, ['convert-historical-partition', 'publish-compact-partition'])
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0]['check'], check)
        self.assertEqual(calls[0]['phase'], phases.append)
        self.assertEqual(calls[0]['source_producer'], self.producer)
        self.assertGreater(checks[0], 0)
        self.assertEqual(self.working.statistics()['snapshots'], before+1)
        view = part.compact_view()
        self.assertIs(type(view), PT.CompactPartition)
        self.assertIs(view.budget, self.budget)
        self.assertIs(type(bridge), G.ParentGeometryTransfer)
        self.assertEqual(part.partition_id, self.header['partition_id'])
        with no_whole_export():
            self.assertEqual(PW.compact_header(view, self.refs), self.header)
            self.assertEqual(PW.descriptor_stats(view), {'sha256': self.refs['partition']['sha256'],
                                                         'nbytes': len(self.raw)})
        # The unchanged legacy statements on the same authenticated blob give a
        # byte-identical transfer record: base and root IDs are representation-free.
        arrays = H.read_selected_arrays(self.original, self.head['key'], ['partition-record:partition'],
                                        admission=self.admission, budget=self.budget, check=check)
        with E.partition_record(self.header, arrays, self.budget) as decoded:
            legacy_bridge = G.bind_parent_geometry(native_transfer=self.fixture.native_owned,
                partition_descriptor=decoded.value, geometry=self.geometry, funding=self.funding,
                collar=self.collar, budget=self.budget)
            legacy = GC.D.DifferentialPartition.restore(decoded.value, self.funding, self.collar, self.geometry,
                                                        budget=self.budget, _runtime_transfer=legacy_bridge)
        del decoded, arrays
        record = bytes(bridge._record)
        self.assertEqual(record, bytes(legacy_bridge._record))
        self.assertEqual(W.digest(bridge.record()), W.digest(legacy_bridge.record()))
        self.assertIsNone(legacy.compact_view())
        self.assertEqual(legacy.partition_id, part.partition_id)
        self.assertEqual([s._json for s in part.supports], [s._json for s in legacy.supports])
        # M7: a compact parent takes the bounded route only; a legacy one the record route.
        operands = dict(funding=self.funding, collar=self.collar, budget=self.budget)
        with forbidden((G.ParentGeometryTransfer, 'matches'), (PT.CompactPartition, '_hash'),
                       (PT.CompactPartition, 'iter_legacy_json')):
            for transfer in (bridge, legacy_bridge):
                self.assertTrue(W._parent_geometry_matches(transfer, part, **operands))
                self.assertFalse(W._parent_geometry_matches(transfer, part, **dict(operands, funding=object())))
                self.assertFalse(W._parent_geometry_matches(transfer, part, **dict(operands, collar=object())))
        with forbidden((G.ParentGeometryTransfer, 'matches_compact')):
            for transfer in (bridge, legacy_bridge):
                self.assertTrue(W._parent_geometry_matches(transfer, legacy, **operands))
                self.assertFalse(W._parent_geometry_matches(transfer, legacy, **dict(operands, funding=object())))
        del bridge, part, view, legacy, legacy_bridge, transfer
        gc.collect()
        # Reopen in the same working copy: no partition JSON read, decode, pack or write.
        token = self.working.change_token()
        routes = ((H, 'read_selected_arrays'), (E, 'partition_record'), (PT, 'pack_partition'),
                  (PW, 'convert_native'), (PS.CompactPartitionStore, 'publish'))
        with forbidden(*routes), no_whole_export():
            again_bridge, again = E.compact_parent_partition(**self.arguments(self.working, check=check,
                                                                              phase=phases.append))
        self.assertEqual(self.working.change_token(), token)
        self.assertEqual(len(phases), 2)
        self.assertEqual(again.partition_id, self.header['partition_id'])
        self.assertEqual(bytes(again_bridge._record), record)
        del again_bridge, again
        # Header drift refuses after the find, without writing.
        changed = dict(self.head, differential_partition=dict(self.header, grid_id=GC.T.ident('other grid')))
        with self.assertRaises(PW.CompactPartitionWorkflowRefused):
            E.compact_parent_partition(**self.arguments(self.working, head=changed))
        self.assertEqual(self.working.change_token(), token)
        with self.assertRaisesRegex(E.EndpointMaterialisationRefused, 'distinct actual working copy'):
            E.compact_parent_partition(**self.arguments(self.original))
        # W1-F reader route: a readonly successor view finds the root and writes nothing.
        path = Path(self.working.path)
        self.working.close()
        gc.collect()
        store, pin = self.readonly(path)
        with store:
            with forbidden(*routes), no_whole_export():
                found_bridge, found = E.compact_parent_partition(**self.arguments(store, phase=phases.append))
            self.assertEqual(found.partition_id, self.header['partition_id'])
            self.assertEqual(bytes(found_bridge._record), record)
            self.assertEqual(len(phases), 2)
            del found_bridge, found
            gc.collect()
        self.assertEqual(sha256(path.read_bytes()).hexdigest(), pin)
        # A readonly view without the converted root refuses before any original read.
        empty = Path(self.temporary.name)/'empty.sqlite'
        ArrayStore(empty, limits(), budget=self.budget).close()
        store, pin = self.readonly(empty)
        with store:
            with forbidden(*routes):
                with self.assertRaisesRegex(E.EndpointMaterialisationRefused, 'lacks its converted compact partition'):
                    E.compact_parent_partition(**self.arguments(store, phase=phases.append))
        self.assertEqual(len(phases), 2)
        self.assertEqual(sha256(empty.read_bytes()).hexdigest(), pin)

    def test_materialise_branches_verify_dispatch_and_m23_wiring(self):
        tree = ast.parse(Path(E.__file__).read_text(encoding='utf8'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'materialise')
        def named(node, name):
            return isinstance(node, ast.Call) and ast.unparse(node.func) == name
        branches = [n for n in ast.walk(function) if isinstance(n, ast.If) and
                    ast.unparse(n.test) == 'working_store is not None' and
                    any(named(c, 'compact_parent_partition') for c in ast.walk(n))]
        self.assertEqual(len(branches), 1)
        # Legacy route: the eight original statements, unchanged.
        legacy = ast.parse(textwrap.dedent(LEGACY_PARENT)).body
        self.assertEqual([ast.dump(n) for n in branches[0].orelse], [ast.dump(n) for n in legacy])
        self.assertEqual(len(branches[0].body), 1)
        call = next(c for c in ast.walk(branches[0]) if named(c, 'compact_parent_partition'))
        self.assertEqual(keywords(call), dict(original_store='original_store', working_store='working_store',
            admission='admission', head='head', native_transfer='transferred', interval='interval',
            funding='spatial.funding', collar='collar', budget='budget', check='check', phase='phase',
            scope='scope', compact_partition='compact_partition'))
        # M23: the mesh conversion and the reused-mesh open see the throttled check.
        assigned = {ast.unparse(n) for n in ast.walk(function) if isinstance(n, ast.Assign) and
                    'conversion_check' in ast.unparse(n.targets[0])}
        self.assertEqual(assigned, {'compact_mesh, compact_partition, source_producer, conversion_check = (None, None, None, check)',
                                    'conversion_check = PW.throttled(check)'})
        throttle = next(n for n in ast.walk(function) if isinstance(n, ast.If) and
                        ast.unparse(n.test) == 'working_store is not None' and
                        any(isinstance(s, ast.Assign) and ast.unparse(s) == 'conversion_check = PW.throttled(check)'
                            for s in n.body))
        self.assertIsNot(throttle, branches[0])
        records = next(c for c in ast.walk(function) if named(c, 'spatial_records'))
        self.assertEqual(keywords(records)['check'], 'conversion_check')
        opened = next(c for c in ast.walk(throttle) if isinstance(c, ast.Call) and
                      isinstance(c.func, ast.Attribute) and c.func.attr == 'open')
        self.assertEqual(keywords(opened)['cancel'], 'X._token(conversion_check)')
        self.assertFalse([c for c in ast.walk(function) if named(c, 'PW.historical_partition')])
        self.assertIn('phase', [a.arg for a in function.args.kwonlyargs])
        # M7: verify() dispatches through the helper and never exports the partition.
        workflow = ast.parse(Path(W.__file__).read_text(encoding='utf8'))
        base = next(n for n in workflow.body if isinstance(n, ast.ClassDef) and n.name == 'MigratedWorkflowBase')
        verify = next(n for n in base.body if isinstance(n, ast.FunctionDef) and n.name == 'verify')
        matches = [c for c in ast.walk(verify) if named(c, '_parent_geometry_matches')]
        self.assertEqual(len(matches), 1)
        self.assertEqual([ast.unparse(a) for a in matches[0].args], ['self._bridge', 'self._partition'])
        self.assertEqual(keywords(matches[0]), dict(funding='self._spatial.funding', collar='collar',
                                                    budget='self._budget'))
        self.assertFalse([c for c in ast.walk(verify) if isinstance(c, ast.Call) and
                          ast.unparse(c.func) in ('self._partition.record', 'self._bridge.matches')])
        # The actual entry gates refuse a non-callable marker and a non-distinct copy
        # before any read, conversion or write.
        native = self.collar._native
        self.assertIs(native._resource, self.budget)
        token = (self.original.change_token(), self.working.change_token())
        for changes, message in ((dict(phase='convert-historical-partition'), 'callable phase marker'),
                                 (dict(working_store=self.original), 'distinct actual working copy')):
            arguments = dict(dict(original_store=self.original, admission=self.admission, native=native,
                collar=self.collar, execution=None, compatibility={}, budget=self.budget,
                check=lambda: None, working_store=self.working, phase=None), **changes)
            with forbidden((H, 'read_selected_arrays'), (H, 'derive_historical_plan_graph')):
                with self.assertRaisesRegex(E.EndpointMaterialisationRefused, message):
                    with E.materialise(**arguments):
                        self.fail('materialised past a refused entry gate')
        self.assertEqual((self.original.change_token(), self.working.change_token()), token)

    def test_throttled_check_bounds_actual_mesh_conversion(self):
        record = MT.small_mesh_record(self.budget)
        forced, callbacks = [0], [0]
        def check():
            forced[0] += 1
        bounded = PW.throttled(check)
        def counted():
            callbacks[0] += 1
            bounded()
        started = time.monotonic()
        view, ref = Y.convert_mesh(self.working, record, expected_geometry_id=M.digest(record),
            source_producer=self.producer, budget=self.budget, check=counted)
        elapsed = time.monotonic()-started
        self.assertEqual(view.geometry_id, M.digest(record))
        self.assertGreaterEqual(forced[0], 1)
        self.assertLessEqual(forced[0], 1+int(elapsed/PW.CHECK_INTERVAL_S)+1)
        self.assertGreater(callbacks[0], 10*forced[0])
        # A raising guard check is not swallowed by the throttle.
        def abort():
            raise RuntimeError('guard abort')
        with self.assertRaisesRegex(RuntimeError, 'guard abort'):
            Y.convert_mesh(self.working, record, expected_geometry_id=M.digest(record),
                source_producer=self.producer, budget=self.budget, check=PW.throttled(abort))
        del view, ref, record


if __name__ == '__main__':
    unittest.main(verbosity=2)
