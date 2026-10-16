"""Fresh composed native package, tiny synthetic partitions, real ArrayStore.

Persistence/ownership controls only: synthetic source authority, no historical
database, no solve. The package applies partition_native_patch.transform to the
frozen differential geometry, the exterior-mesh transform, and the workflow
chain nonzero cursor -> spatial -> partition. geometry_transfer is absent.
"""
import ast
from concurrent.futures import CancelledError
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import gc
from hashlib import sha256
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
INTEGRATION = HERE.parents[1]/'runtime-integration-r1'
BASE = INTEGRATION/'runtime-src'/'atlas_tectonics'
sys.path.insert(0, str(HERE.parent))

import exterior_mesh_patch as EMP
import partition_native_patch as PN
import partition_workflow_transform as PWT
import workflow_transfer as W

PRODUCER = {'execution_identity': 'd'*64, 'collar_plan_id': 'c'*64,
            'role': 'synthetic storage fixture; no scientific authority'}
CURSOR_SHA256 = '61888439a0acd5484279cce374f23939550e81b38da73991d4f82c7c5e3c9916'
temporary = None


def spatial_transform():
    """AST-extract require/transform; the module itself imports atlas_tectonics."""
    path = HERE/'spatial_workflow_patch.py'
    tree = ast.parse(path.read_bytes().decode('utf8'))
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('require', 'transform')]
    assert sorted(n.name for n in body) == ['require', 'transform']
    namespace = {'X': SimpleNamespace(IndexedSpatialRefused=ValueError)}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['transform']


def chains():
    frozen = (BASE/'integration_regional_workflow.py').read_bytes().decode('utf8')
    cursor = W.nonzero_cursor_source(frozen)
    spatial = spatial_transform()(cursor)
    cold_frozen = (BASE/'integration_private_heat_cold.py').read_bytes().decode('utf8')
    return frozen, cursor, spatial, cold_frozen, W.private_heat_cold_source(cold_frozen)


def setUpModule():
    global temporary, D, WF, CW, E, X, Y, M, P, PS, PW, TP, MT, N, H, EP, ArrayStore, StoreLimits, ArrayReference, WorkBudget
    if any(n == 'atlas_tectonics' or n.startswith('atlas_tectonics.') for n in sys.modules):
        raise RuntimeError('fresh process required; never patch a loaded production package')
    temporary = tempfile.TemporaryDirectory(prefix='pw-', dir=HERE.parents[4])
    package = Path(temporary.name)/'atlas_tectonics'
    shutil.copytree(BASE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    spatial = chains()[2]
    for name, text in (
            ('integration_differential_geometry.py',
             PN.transform((BASE/'integration_differential_geometry.py').read_bytes().decode('utf8'))),
            ('integration_exterior_mesh.py', EMP.transform((BASE/'integration_exterior_mesh.py').read_bytes().decode('utf8'))),
            ('integration_regional_workflow.py', PWT.transform(spatial))):
        (package/name).write_text(text, encoding='utf8', newline='\n')
    sys.path.insert(0, temporary.name)
    D = importlib.import_module('atlas_tectonics.integration_differential_geometry')
    WF = importlib.import_module('atlas_tectonics.integration_regional_workflow')
    CW = WF.CollarWorkflow
    E = importlib.import_module('atlas_tectonics.integration_exterior_mesh')
    storage = importlib.import_module('atlas_tectonics.storage')
    ArrayStore, StoreLimits, ArrayReference = storage.ArrayStore, storage.StoreLimits, storage.ArrayReference
    WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget
    X, Y = importlib.import_module('spatial_indexed_patch'), importlib.import_module('spatial_workflow_patch')
    M, P = importlib.import_module('mesh_tables'), importlib.import_module('partition_tables')
    PS, PW = importlib.import_module('partition_store'), importlib.import_module('partition_workflow_patch')
    TP, MT = importlib.import_module('test_partition_tables'), importlib.import_module('test_mesh_tables')
    N, H = importlib.import_module('native_transfer'), importlib.import_module('historical_admission')
    EP = importlib.import_module('materialise_endpoint')
    assert Path(WF.__file__).resolve().parent == package.resolve() and WF._COMPACT_PARTITION is PW
    assert TP.D is D and hasattr(E.ExteriorMesh, 'from_compact')


def tearDownModule():
    if temporary is not None:
        assert Path(temporary.name).resolve().parent == HERE.parents[4]
        temporary.cleanup()


def limits():
    return StoreLimits(chunk_bytes=256, max_array_bytes=2 << 20,
        max_store_bytes=16 << 20, max_manifest_bytes=256 << 10,
        sqlite_cache_bytes=65536, codec_workspace_bytes=65536)


def operands(body, budget, *, initial=False):
    """Restore-protocol controls, not assertions of real physical provenance."""
    funding = SimpleNamespace(funding_id=body['funding_id'], _resource=budget,
                              descriptor=lambda: {'source': body['source']})
    collar = SimpleNamespace(plan_id=body['collar_plan_id'], _budget=budget)
    geometry = D._issue(D.CurrentGeometry if initial else D.DifferentialInterval,
                        {'fixture': 'typed restore protocol only'}, budget)
    body['scope'] = 'initial-current' if initial else 'physical-interval'
    body['current_geometry_id'] = geometry.geometry_id if initial else None
    if not initial:
        body['interval_id'] = geometry.interval_id
    return funding, collar, geometry


def native(body, supports, ops, budget):
    return D.DifferentialPartition.restore(dict(partition_id=D._record_hash(body), **body, supports=supports),
                                           *ops, budget=budget)


@contextmanager
def no_whole_export():
    original = P.CompactPartition.legacy_record
    def selected_only(instance, ref=None):
        if ref is None or ref.index == instance._body:
            raise AssertionError('whole partition export forbidden')
        return original(instance, ref)
    with patch.object(P.CompactPartition, 'legacy_record', selected_only):
        yield


@contextmanager
def decoded(blob, *, budget, cancel=None):
    """Protocol stand-in for the unchanged R.decoded metadata view."""
    with budget.reserve(65536+8*len(blob), category='fixture-decoded-metadata'):
        yield SimpleNamespace(value=json.loads(blob))


def method(tree, cls, name):
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    return next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == name)


def dumps(nodes):
    return [ast.dump(n) for n in nodes]


class PartitionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='.pw-', dir=HERE.parents[4])
        self.budget = WorkBudget(128 << 20)
        self.store = ArrayStore(Path(self.temporary.name)/'working.sqlite', limits(), budget=self.budget)
        self.body, self.supports = TP.tiny_partition(self.budget)

    def tearDown(self):
        self.store.close()
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temporary.cleanup()

    def compact_roots(self):
        view = TP.opened(self.body, self.supports, self.budget)[0]
        partition = PS.CompactPartitionStore(self.store, budget=self.budget).publish(view, source_producer=PRODUCER)
        mesh = MT.compact_fixture(budget=self.budget)[0]
        return partition, Y.persist_mesh(self.store, mesh, {'fixture': 'bounded ownership only'}, budget=self.budget)

    def snapshot(self, key, pref, mref, *, location='nested', extra=None, partition_aliases=True):
        import numpy as np
        arrays = {'collar-field': np.arange(3, dtype=np.float64), 'exterior-fv:volume_m3': np.ones(2),
                  'spatial-record:state': np.frombuffer(b'{}', dtype=np.uint8)}
        if partition_aliases:
            arrays.update(PW._aliases(self.store, pref))
        arrays.update({Y.PREFIX+n: self.store.reference(mref['snapshot_key'], n) for n in mref['array_bindings']})
        arrays.update(extra or {})
        metadata = {'exterior_state': {'compact_mesh': mref}, 'differential_partition': {'partition_id': pref['partition_id']}}
        if location in ('nested', 'both'):
            metadata['differential_partition']['compact_partition'] = pref
        if location in ('top', 'both'):
            metadata['compact_partition'] = pref
        self.store.put(key, arrays, metadata, budget=self.budget)

    def test_descriptor_header_binding_parity(self):
        empty = deepcopy(self.body)
        empty['source'] = {'fixture_only': True, 'large_integer': 1 << 300}
        for body in (deepcopy(self.body), empty):
            ops = operands(body, self.budget)
            legacy = native(body, self.supports, ops, self.budget)
            view = TP.opened(body, self.supports, self.budget)[0]
            part = D.DifferentialPartition.from_compact(view, *ops, budget=self.budget)
            self.assertEqual(len(view._arrays['float.value']) == 0, body is empty)
            record = legacy.descriptor()
            raw = WF._json(record)
            refs = {'partition': dict(array='partition-record:partition', bytes=len(raw), sha256=sha256(raw).hexdigest())}
            ref = {'schema': PS.SCHEMA, 'fixture': 'reference placement only'}
            expected = (legacy.partition_id, record['parent_partition_id'], WF._hash(record['support_ids']),
                        legacy.partition_id)
            names = ('grid_id', 'start_time_s', 'parent_partition_id', 'current_geometry_id', 'source')
            with no_whole_export():
                self.assertEqual(b''.join(PW.iter_descriptor_json(view)), raw)
                self.assertEqual(PW.descriptor_stats(view), {'sha256': refs['partition']['sha256'], 'nbytes': len(raw)})
                self.assertEqual(PW.compact_header(view, refs), CW._partition_header(record, refs))
                self.assertEqual(PW.compact_header(view, {}, ref),
                                 dict(CW._partition_header(record, {}), compact_partition=ref))
                self.assertEqual(PW.binding(part, WF._hash), expected)
                for name in names:
                    self.assertEqual(PW.field(part, name).value, record[name], name)
            # The ordinary native expressions run unchanged, with no added reservation.
            with patch.object(M, '_Allocation', side_effect=AssertionError('ordinary path added a reservation')):
                self.assertEqual(PW.binding(legacy, WF._hash), expected)
                for name in names:
                    self.assertEqual(PW.field(legacy, name).value, record[name], name)
            with self.assertRaises(D.V.VolumeError):
                part.record()
            del view, part, legacy, ops

    def test_transform_and_cold_source_exact_seams(self):
        frozen, cursor, spatial, cold_frozen, cold = chains()
        digest = lambda text: sha256(text.encode()).hexdigest()
        self.assertEqual((digest(frozen), digest(cursor), digest(spatial), digest(cold)),
                         (W.BASE_SOURCE_SHA256, CURSOR_SHA256, PWT.WORKFLOW_INPUT_SHA256, PWT.COLD_INPUT_SHA256))
        self.assertEqual((len(PWT.WORKFLOW_SEAMS), len(PWT.COLD_SEAMS)), (9, 4))
        results = {}
        for source, seams, function, names in ((spatial, PWT.WORKFLOW_SEAMS, PWT.transform, PWT.WORKFLOW_FUNCTIONS),
                                               (cold, PWT.COLD_SEAMS, PWT.cold_source, PWT.COLD_FUNCTIONS)):
            for old, _ in seams:
                self.assertEqual((source.count(old), source.count('\n'+old)), (1, 1), old[:70])
            result = function(source)
            for _, new in seams:
                self.assertEqual(result.count(new), 1, new[:70])
            before, after = PWT.functions(ast.parse(source)), PWT.functions(ast.parse(result))
            self.assertEqual(set(before), set(after))
            self.assertEqual({n for n in before if before[n] != after[n]}, names)
            for bad in (result, source+'\n', source.replace('\n', '\r\n')):
                with self.assertRaises(PWT.PartitionWorkflowTransformRefused):
                    function(bad)
            results[function.__name__] = result
        self.assertEqual((digest(results['transform']), digest(results['cold_source'])),
                         (PWT.WORKFLOW_OUTPUT_SHA256, PWT.COLD_OUTPUT_SHA256))
        for wrong, function in ((cursor, PWT.transform), (frozen, PWT.transform), (cold_frozen, PWT.cold_source),
                                (spatial, PWT.cold_source), (cold, PWT.transform), (None, PWT.transform)):
            with self.assertRaises(PWT.PartitionWorkflowTransformRefused):
                function(wrong)
        for source, old in (('x\n        def f():\n', '    def f():\n'), ('\nx\nx\n', 'x\n')):
            with self.assertRaises(PWT.PartitionWorkflowTransformRefused):
                PWT._once(source, old, 'y\n')
        # Ordinary branches are the unchanged original statements.
        old, new = ast.parse(spatial), ast.parse(results['transform'])
        payload_old, payload_new = method(old, 'CollarWorkflow', '_partition_payload'), method(new, 'CollarWorkflow', '_partition_payload')
        self.assertEqual(dumps(payload_new.body[:1]+payload_new.body[2:]), dumps(payload_old.body))
        self.assertEqual(dumps(payload_new.decorator_list), dumps(payload_old.decorator_list))
        restore_old, restore_new = method(old, 'CollarWorkflow', '_restore_partition'), method(new, 'CollarWorkflow', '_restore_partition')
        self.assertEqual(dumps(restore_new.body[1:]), dumps(restore_old.body))
        gate = next(n for n in ast.walk(method(new, 'CollarWorkflow', '_publish')) if isinstance(n, ast.If) and
                    '_migration' in ast.dump(n.test))
        call = next(n for n in ast.walk(method(old, 'CollarWorkflow', '_publish')) if isinstance(n, ast.Assign) and
                    '_partition_payload' in ast.dump(n))
        self.assertEqual(dumps(gate.body), dumps([call]))
        cold_old, cold_new = ast.parse(cold), ast.parse(results['cold_source'])
        branch = next(n for n in ast.walk(next(f for f in cold_new.body if getattr(f, 'name', None) == 'restore_checkpoint'))
                      if isinstance(n, ast.If) and '_COMPACT_INDEXED' in ast.dump(n.test))
        original = next(n for n in ast.walk(next(f for f in cold_old.body if getattr(f, 'name', None) == 'restore_checkpoint'))
                        if isinstance(n, ast.With) and 'decoded' in ast.dump(n.items[0]))
        self.assertEqual(dumps(branch.orelse), dumps([original]))
        self.assertEqual(results['cold_source'].count("_BINDING_SHA = '84a7a048e73073f6cb41f5b5d50b5dcb0aacb9c5403dda99b8c5aa3b1ef7f592'"), 1)
        # The transform module itself imports only the standard library.
        module = ast.parse((HERE/'partition_workflow_transform.py').read_bytes().decode('utf8'))
        imported = {a.name for n in module.body if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module for n in module.body if isinstance(n, ast.ImportFrom)}
        self.assertEqual(imported, {'ast', 'hashlib'})
        probe = ('import sys; sys.path.insert(0, %r); import partition_workflow_transform; '
                 "bad = [n for n in sys.modules if n.split('.')[0] in ('atlas_tectonics', 'numpy', 'partition_workflow_patch')]; "
                 "assert not bad, bad; print('STDLIB_ONLY')") % str(HERE)
        completed = subprocess.run([sys.executable, '-B', '-I', '-c', probe], capture_output=True, text=True, timeout=60)
        self.assertEqual((completed.returncode, completed.stdout.strip()), (0, 'STDLIB_ONLY'), completed.stderr)

    def test_v2_transform_routes_both_publication_branches(self):
        legacy = PWT.transform(chains()[2])
        changed = PWT.transform_v2(legacy)
        before, after = PWT.functions(ast.parse(legacy)), PWT.functions(ast.parse(changed))
        self.assertEqual({name for name in before if before[name] != after[name]}, {'CollarWorkflow._publish'})
        publication = method(ast.parse(changed), 'CollarWorkflow', '_publish')
        calls = [node for node in ast.walk(publication) if isinstance(node, ast.Call) and
                 isinstance(node.func, ast.Attribute) and node.func.attr == '_partition_payload']
        self.assertEqual(len(calls), 1)
        self.assertEqual({item.arg for item in calls[0].keywords}, {'store', 'source_producer', 'cancel'})
        for bad in (changed, legacy+'\n', legacy.replace('\n', '\r\n')):
            with self.assertRaises(PWT.PartitionWorkflowTransformRefused):
                PWT.transform_v2(bad)

    def test_payload_restore_real_store_and_native_classes(self):
        import numpy as np
        ops = operands(self.body, self.budget)
        funding, collar, interval = ops
        legacy = native(self.body, self.supports, ops, self.budget)
        record = legacy.descriptor()
        raw = WF._json(record)
        # Ordinary route: the exact legacy blob and native restore are unchanged.
        with CW._partition_payload(legacy, interval, funding, collar, self.budget) as (old_header, old_arrays):
            self.assertEqual(old_header, CW._partition_header(record, {'partition': dict(
                array='partition-record:partition', bytes=len(raw), sha256=sha256(raw).hexdigest())}))
            self.assertEqual(set(old_arrays), {'partition-record:partition'})
            self.assertEqual(old_arrays['partition-record:partition'].tobytes(), raw)
            ordinary, same = CW._restore_partition(old_header, old_arrays, funding, collar, self.budget, interval=interval)
            self.assertIsNone(ordinary.compact_view())
            self.assertIs(same, interval)
            self.assertEqual(ordinary.partition_id, legacy.partition_id)
            del ordinary, same
        key = TP.ident('successor fixture')
        before = self.store.statistics()
        with no_whole_export():
            with CW._partition_payload(legacy, interval, funding, collar, self.budget, store=self.store,
                                       source_producer=PRODUCER) as (header, aliases):
                ref = header['compact_partition']
                self.assertEqual(header['record_blobs'], {})
                self.assertEqual({k: v for k, v in header.items() if k not in ('record_blobs', 'compact_partition')},
                                 {k: v for k, v in old_header.items() if k != 'record_blobs'})
                self.assertEqual(aliases, {})
                self.store.put(key, dict(aliases, **{'collar-field': np.arange(3, dtype=np.float64)}),
                               {'differential_partition': header}, budget=self.budget)
            saved = self.store.metadata(key)['differential_partition']
            self.assertEqual(saved, header)
            self.assertEqual(self.store.statistics()['snapshots'], before['snapshots']+2)
            token = self.store.change_token()
            arrays = PW.workflow_arrays(self.store, key, budget=self.budget)
            self.assertEqual(set(arrays), {'collar-field'})
            partition_arrays = {k: v for k, v in arrays.items() if k.startswith('partition-record:')}
            part, same = CW._restore_partition(saved, partition_arrays, funding, collar, self.budget,
                                               interval=interval, store=self.store)
            self.assertIs(same, interval)
            self.assertIs(type(part.compact_view()), P.CompactPartition)
            self.assertEqual(part.partition_id, legacy.partition_id)
            self.assertEqual([s._json for s in part.supports], [s._json for s in legacy.supports])
            self.assertEqual(PW.binding(part, WF._hash), PW.binding(legacy, WF._hash))
            # Republishing the same logical partition, native or compact, writes nothing;
            # a native partition with a stored root is found first, not converted again.
            with patch.object(PW, 'convert_native', side_effect=AssertionError('stored root converted again')):
                for source in (legacy, part):
                    gc.collect()
                    charged = self.budget.statistics()['categories'].get('compact-partition-header', 0)
                    with CW._partition_payload(source, interval, funding, collar, self.budget, store=self.store,
                                               source_producer=PRODUCER) as (again, again_aliases):
                        self.assertEqual(again, header)
                        self.assertIs(type(again), type(header))
                        self.assertEqual(set(again_aliases), set(aliases))
                        # The reused header carries its own charge.
                        self.assertGreater(self.budget.statistics()['categories'].get('compact-partition-header', 0),
                                           charged)
                    del again, again_aliases
            self.assertEqual(self.store.change_token(), token)
        other = D._issue(D.DifferentialInterval, {'fixture': 'another interval'}, self.budget)
        legacy_blob = {'partition-record:partition': np.frombuffer(raw, dtype=np.uint8)}
        for changed, blobs, geometry, store, kind in (
                (saved, legacy_blob, interval, self.store, PW.CompactPartitionWorkflowRefused),
                (dict(saved, grid_id=TP.ident('other grid')), {}, interval, self.store, PW.CompactPartitionWorkflowRefused),
                (dict(saved, record_blobs=old_header['record_blobs']), {}, interval, self.store, PW.CompactPartitionWorkflowRefused),
                (dict(saved, unreviewed='field'), {}, interval, self.store, PW.CompactPartitionWorkflowRefused),
                (saved, {}, other, self.store, D.V.VolumeError),
                (saved, {}, None, self.store, PW.CompactPartitionWorkflowRefused),
                (saved, {}, interval, None, PW.CompactPartitionWorkflowRefused)):
            with self.assertRaises(kind):
                CW._restore_partition(changed, blobs, funding, collar, self.budget, interval=geometry, store=store)
        wrong = SimpleNamespace(funding_id=TP.ident('other funding'), _resource=self.budget, descriptor=funding.descriptor)
        current = D._issue(D.CurrentGeometry, {'fixture': 'initial scope'}, self.budget)
        cancel = threading.Event()
        cancel.set()
        snapshots = self.store.statistics()['snapshots']
        for args, kwargs, kind in (
                ((legacy, interval, wrong, collar), dict(source_producer=PRODUCER), PW.CompactPartitionWorkflowRefused),
                ((legacy, interval, funding, collar), dict(source_producer=None), PW.CompactPartitionWorkflowRefused),
                ((legacy, current, funding, collar), dict(source_producer=PRODUCER), PW.CompactPartitionWorkflowRefused),
                ((legacy, interval, funding, collar), dict(source_producer=PRODUCER, cancel=cancel), CancelledError)):
            with self.assertRaises(kind):
                with CW._partition_payload(*args, self.budget, store=self.store, **kwargs):
                    pass
        self.assertEqual(self.store.statistics()['snapshots'], snapshots)
        del legacy, part, arrays, header, aliases, saved, ref, other, current, legacy_blob, ops, funding, collar, interval

    def test_workflow_arrays_alias_verification_and_funding(self):
        import numpy as np
        pref, mref = self.compact_roots()
        for location, key in (('nested', '5'*64), ('top', '6'*64)):
            self.snapshot(key, pref, mref, location=location)
            gc.collect()
            baseline = self.budget.reserved_bytes
            values = PW.workflow_arrays(self.store, key, budget=self.budget)
            self.assertEqual(set(values), {'collar-field', 'exterior-fv:volume_m3', 'spatial-record:state'})
            escaped = values['collar-field']
            del values
            gc.collect()
            self.assertGreater(self.budget.reserved_bytes, baseline)
            self.assertFalse(escaped.flags.writeable)
            self.assertEqual(escaped.tolist(), [0.0, 1.0, 2.0])
            del escaped
            gc.collect()
            self.assertEqual(self.budget.reserved_bytes, baseline)
        for location, key in (('both', '7'*64), ('neither', '8'*64)):
            self.snapshot(key, pref, mref, location=location)
            with self.assertRaisesRegex(PW.CompactPartitionWorkflowRefused, 'exactly one'):
                PW.workflow_arrays(self.store, key, budget=self.budget)
        first = sorted(pref['array_bindings'])[0]
        self.snapshot('9'*64, pref, mref, extra={PW.PREFIX+first: np.array([255], dtype=np.uint8)})
        gc.collect()
        baseline, held = self.budget.reserved_bytes, None
        try:
            PW.workflow_arrays(self.store, '9'*64, budget=self.budget)
        except PW.CompactPartitionWorkflowRefused as failure:
            self.assertIn('aliases differ', str(failure))
            held = failure.__traceback__
            failure.__traceback__ = None
        self.assertIsNotNone(held)
        gc.collect()
        self.assertGreaterEqual(self.budget.statistics()['categories'].get('compact-partition-workflow-manifest', 0),
                                8*self.store.limits.max_manifest_bytes)
        self.assertGreater(self.budget.reserved_bytes, baseline)
        del held
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, baseline)
        mesh_first = sorted(mref['array_bindings'])[0]
        self.snapshot('a'*64, pref, mref, extra={Y.PREFIX+mesh_first: np.array([255], dtype=np.uint8)})
        with self.assertRaisesRegex(PW.CompactPartitionWorkflowRefused, 'mesh aliases differ'):
            PW.workflow_arrays(self.store, 'a'*64, budget=self.budget)
        # Without partition aliases the tested spatial reader runs unchanged.
        self.snapshot('b'*64, pref, mref, location='neither', partition_aliases=False)
        real, calls = Y.workflow_arrays, []
        with patch.object(Y, 'workflow_arrays', side_effect=lambda *a, **k: calls.append(1) or real(*a, **k)):
            values = PW.workflow_arrays(self.store, 'b'*64, budget=self.budget)
        expected = real(self.store, 'b'*64, budget=self.budget)
        self.assertEqual(len(calls), 1)
        self.assertEqual(set(values), set(expected))
        self.assertTrue(all(np.array_equal(values[k], expected[k]) for k in values))
        # Without any alias the ordinary store.get runs once, after the manifest
        # workspace is released, and the spatial reader is not entered.
        plain = {'collar-field': np.arange(3, dtype=np.float64), 'spatial-record:state': np.frombuffer(b'{}', dtype=np.uint8)}
        self.store.put('e'*64, plain, {'fixture': 'ordinary alias-free workflow'}, budget=self.budget)
        real_get, held = self.store.get, []
        def get(*args, **kwargs):
            held.append(self.budget.statistics()['categories'].get('compact-partition-workflow-manifest', 0))
            return real_get(*args, **kwargs)
        with patch.object(Y, 'workflow_arrays', side_effect=AssertionError('alias-free read entered the spatial reader')), \
                patch.object(self.store, 'get', side_effect=get):
            values = PW.workflow_arrays(self.store, 'e'*64, budget=self.budget)
        self.assertEqual(held, [0])
        expected = self.store.get('e'*64, budget=self.budget)
        self.assertEqual(set(values), set(plain))
        self.assertTrue(all(values[k].dtype == expected[k].dtype and np.array_equal(values[k], expected[k]) for k in values))
        self.assertIsNone(PW.workflow_arrays(self.store, 'c'*64, budget=self.budget))
        del values, expected, pref, mref

    def test_historical_partition_conversion_and_reuse(self):
        import numpy as np
        ops = operands(self.body, self.budget)
        record = native(self.body, self.supports, ops, self.budget).descriptor()
        raw = WF._json(record)
        refs = {'partition': dict(array='partition-record:partition', bytes=len(raw), sha256=sha256(raw).hexdigest())}
        header = CW._partition_header(record, refs)
        head = {'key': TP.ident('historical head'), 'differential_partition': header}
        with ArrayStore(Path(self.temporary.name)/'original.sqlite', limits(), budget=self.budget) as original:
            original.put(head['key'], {'partition-record:partition': np.frombuffer(raw, dtype=np.uint8)},
                         {'differential_partition': header}, budget=self.budget)
            with original._read_scope():
                manifest = original._manifest(head['key'])
            capsule = {'snapshot_manifests': {head['key']: manifest}}
            encoded = (W.canonical(capsule), W.canonical({'capsule_sha256': H.digest(capsule),
                                                          'fixture': 'SYNTHETIC FIXTURE ONLY'}))
            allocation = N._Allocation(self.budget, sum(map(len, encoded))+4096, category='fixture-admission-retained')
            admission = object.__new__(W.HistoricalEndpointAdmission)
            object.__setattr__(admission, '_record', N._RecordBytes(encoded[0], allocation))
            object.__setattr__(admission, '_binding', N._RecordBytes(encoded[1], allocation))
            object.__setattr__(admission, '_source_audit', None)
            calls, phases, trackers, callbacks = [0], [], [], [0]
            def check():
                calls[0] += 1
            real = PW.throttled
            def spy(target, interval=PW.CHECK_INTERVAL_S):
                forwarded = [0]
                def inner():
                    forwarded[0] += 1
                    target()
                trackers.append(forwarded)
                bounded = real(inner, interval)
                def counted():
                    callbacks[0] += 1
                    bounded()
                return counted
            arguments = dict(original_store=original, working_store=self.store, admission=admission,
                             source_producer=PRODUCER, budget=self.budget, check=check)
            before, started = self.store.statistics(), time.monotonic()
            with patch.object(PW, 'throttled', spy):
                view = PW.historical_partition(head=head, phase=phases.append, **arguments)
            elapsed = time.monotonic()-started
            self.assertEqual(phases, ['convert-historical-partition', 'publish-compact-partition'])
            self.assertEqual(view.partition_id, header['partition_id'])
            self.assertEqual(self.store.statistics()['snapshots'], before['snapshots']+1)
            forwarded = sum(f[0] for f in trackers)
            self.assertGreater(callbacks[0], view.node_count)
            self.assertLessEqual(forwarded, len(trackers)*(2+int(elapsed/PW.CHECK_INTERVAL_S)))
            self.assertLess(forwarded*10, callbacks[0])
            del view
            bounded, hits = PW.throttled(lambda: hits.append(1), 60), []
            for _ in range(10000):
                bounded()
            self.assertEqual(len(hits), 1)
            # Reopen: no original partition JSON read, conversion or write.
            token = self.store.change_token()
            def forbidden(*args, **kwargs):
                raise AssertionError('reopen read, decoded or converted historical partition JSON')
            with patch.object(H, 'read_selected_arrays', forbidden), patch.object(EP, 'partition_record', forbidden), \
                    patch.object(P, 'pack_partition', forbidden), no_whole_export():
                again = PW.historical_partition(head=head, phase=phases.append, **arguments)
            self.assertEqual(self.store.change_token(), token)
            self.assertEqual(len(phases), 2)
            self.assertEqual(PW.descriptor_stats(again), {'sha256': refs['partition']['sha256'], 'nbytes': len(raw)})
            ref = PS.CompactPartitionStore(self.store, budget=self.budget).find(header['partition_id'], PRODUCER)
            del again
            for changed in (dict(header, grid_id=TP.ident('other grid')),
                            dict(header, record_blobs={'partition': dict(refs['partition'], sha256='0'*64)}),
                            dict(header, record_blobs={'partition': dict(refs['partition'], bytes=len(raw)+1)}),
                            dict(header, compact_partition=ref)):
                with self.assertRaises(PW.CompactPartitionWorkflowRefused):
                    PW.historical_partition(head=dict(head, differential_partition=changed), **arguments)
            with self.assertRaises(PW.CompactPartitionWorkflowRefused):
                PW.historical_partition(head=head, **dict(arguments, working_store=original))
            self.assertEqual(self.store.change_token(), token)
            del admission, allocation, arguments, ref, manifest, capsule
        del ops

    def test_historical_partition_converts_native_record_beyond_metadata_cap(self):
        """A ~19 MB native-schema parent passes the uncapped canonical check and converts.

        Synthetic native-schema supports (no historical database or solve). Before
        the caps fix, materialise_endpoint.partition_record refused any parent over
        workflow_transfer's 8 MiB metadata cap (the r9 head parent is 114 MB).
        """
        import numpy as np
        budget = WorkBudget(4 << 30)
        body, supports = TP.tiny_partition(budget, count=1500, depth=12)
        record = dict(partition_id=D._record_hash(body), **body, supports=supports)
        raw = WF._json(record)
        self.assertGreater(len(raw), 16 << 20)
        with self.assertRaisesRegex(W.WorkflowTransferRefused, 'exceeds 8 MiB'):
            W.canonical(record)
        refs = {'partition': dict(array='partition-record:partition', bytes=len(raw), sha256=sha256(raw).hexdigest())}
        header = CW._partition_header(record, refs)
        head = {'key': TP.ident('large historical head'), 'differential_partition': header}
        del record, supports, body
        sized = StoreLimits(chunk_bytes=65536, max_array_bytes=64 << 20, max_store_bytes=256 << 20,
                            max_manifest_bytes=1 << 20, sqlite_cache_bytes=65536, codec_workspace_bytes=65536)
        root = Path(self.temporary.name)
        with ArrayStore(root/'large-original.sqlite', sized, budget=budget) as original, \
                ArrayStore(root/'large-working.sqlite', sized, budget=budget) as working:
            original.put(head['key'], {'partition-record:partition': np.frombuffer(raw, dtype=np.uint8)},
                         {'differential_partition': header}, budget=budget)
            with original._read_scope():
                manifest = original._manifest(head['key'])
            capsule = {'snapshot_manifests': {head['key']: manifest}}
            encoded = (W.canonical(capsule), W.canonical({'capsule_sha256': H.digest(capsule),
                                                          'fixture': 'SYNTHETIC FIXTURE ONLY'}))
            allocation = N._Allocation(budget, sum(map(len, encoded))+4096, category='fixture-admission-retained')
            admission = object.__new__(W.HistoricalEndpointAdmission)
            object.__setattr__(admission, '_record', N._RecordBytes(encoded[0], allocation))
            object.__setattr__(admission, '_binding', N._RecordBytes(encoded[1], allocation))
            object.__setattr__(admission, '_source_audit', None)
            gc.collect()
            baseline = budget.reserved_bytes
            view = PW.historical_partition(original_store=original, working_store=working, admission=admission,
                head=head, source_producer=PRODUCER, budget=budget, check=lambda: None)
            self.assertEqual(view.partition_id, header['partition_id'])
            self.assertEqual(view.support_count, 1500)
            self.assertEqual(PW.descriptor_stats(view), {'sha256': refs['partition']['sha256'], 'nbytes': len(raw)})
            self.assertGreaterEqual(budget.statistics()['category_peaks']['restart-canonical-encode'], 5*len(raw)//2)
            self.assertEqual(budget.statistics()['categories'].get('restart-canonical-encode', 0), 0)
            del view
            gc.collect()
            self.assertEqual(budget.reserved_bytes, baseline)
            del admission, allocation, manifest, capsule, encoded
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    @unittest.skip('superseded stand-in, not M14 evidence: it substitutes json.loads for R.decoded with '
                   'plain-bytes metadata and reads COLD_OUTPUT_SHA256 from the module under test. The '
                   'real-encoding evidence is test_ram_context_indexed_patch.ColdSeam (W2-E; cold seam ed202b4b).')
    def test_cold_source_indexed_thermal_mesh(self):
        import numpy as np
        cold = chains()[4]
        result = PWT.cold_source(cold)
        tree = ast.parse(result)
        restore = next(f for f in tree.body if getattr(f, 'name', None) == 'restore_checkpoint')
        branch = next(n for n in ast.walk(restore) if isinstance(n, ast.If) and '_COMPACT_INDEXED' in ast.dump(n.test))
        original = next(n for n in ast.walk(next(f for f in ast.parse(cold).body if getattr(f, 'name', None) ==
                        'restore_checkpoint')) if isinstance(n, ast.With) and 'decoded' in ast.dump(n.items[0]))
        self.assertEqual(dumps(branch.orelse), dumps([original]))
        text = textwrap.dedent(ast.get_source_segment(result, branch, padded=True))
        namespace = dict(R=SimpleNamespace(decoded=decoded), B=SimpleNamespace(ExteriorMesh=E.ExteriorMesh),
                         _COMPACT_INDEXED=X)
        exec(compile('def seam(spatial_state, budget, cancel):\n'+textwrap.indent(text, '    ')+'\n    return mesh\n',
                     '<transformed-cold-thermal-seam>', 'exec'), namespace)
        seam = namespace['seam']
        record = MT.small_mesh_record(self.budget)
        view = MT.compact_fixture(record, self.budget)[0]
        small = dict(time_s=1.0, thermal_mesh_id=view.geometry_id, support_id=record['support_id'])
        def indexed(metadata, mesh_view=view):
            return SimpleNamespace(_snapshot=X.IndexedSpatialSnapshot(N._json(metadata), (), 'a'*64, mesh_view,
                                                                      ('b'*64, 1), 1.0, self.budget))
        with patch.object(M.CompactMesh, 'legacy_record', side_effect=AssertionError('expanded compact mesh forbidden')):
            mesh = seam(indexed(small), self.budget, None)
        old = seam(SimpleNamespace(_snapshot=SimpleNamespace(_metadata=N._json(dict(small, thermal_mesh=record)))),
                   self.budget, None)
        self.assertIs(type(mesh), E.ExteriorMesh)
        self.assertEqual((mesh.is_compact, old.is_compact), (True, False))
        self.assertEqual(mesh.geometry_id, old.geometry_id)
        self.assertEqual(mesh.geometry_id, M.digest(record))
        for state, message in ((indexed(dict(small, thermal_mesh=record)), 'expanded thermal mesh'),
                               (indexed(dict(small, thermal_mesh_id='f'*64)), 'committed geometry ID')):
            with self.assertRaisesRegex(ValueError, message):
                seam(state, self.budget, None)
        other = WorkBudget(128 << 20)
        foreign = MT.compact_fixture(record, other)[0]
        with self.assertRaisesRegex(ValueError, 'sealed on the workflow budget'):
            seam(indexed(small, foreign), self.budget, None)
        del foreign, mesh, old
        gc.collect()
        self.assertEqual(other.reserved_bytes, 0)
        # The transformed parent reader reaches collar.restore without either alias set.
        names = {'_PREFIXES', '_snapshot_charge', '_restore_parent'}
        nodes = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in names) or
                 (isinstance(n, ast.Assign) and any(getattr(t, 'id', None) in names for t in n.targets))]
        self.assertEqual(len(nodes), 3)
        reader = dict(np=np, _COMPACT_PARTITION=PW, R=SimpleNamespace(L=SimpleNamespace(_size=lambda n: n)),
                      _width=importlib.import_module('atlas_tectonics.integration_regional_inventory')._width)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<transformed-cold-parent>', 'exec'), reader)
        pref, mref = self.compact_roots()
        self.snapshot('d'*64, pref, mref)
        captured = {}
        @contextmanager
        def spatial_restore(header, advance, records, budget, *, store=None):
            captured.update(records=set(records), store=store)
            yield {'fixture': 'restored spatial header'}, None
        workflow = SimpleNamespace(_store=self.store, _spatial_restore_records=spatial_restore,
            _collar=SimpleNamespace(restore=lambda state, arrays: captured.update(collar=set(arrays)) or
                                    SimpleNamespace(native_state=SimpleNamespace(result_id='9'*64))),
            _exterior_owner=SimpleNamespace(restore=lambda state, arrays: captured.update(exterior=set(arrays)) or 'spatial',
                                            validate_parent=lambda spatial, collar: None))
        parent = {'key': 'd'*64, 'state': {'fixture': 'collar'}, 'native_state_id': '9'*64,
                  'exterior_state': {'fixture': 'spatial'}}
        with ExitStack() as stack:
            reader['_restore_parent'](workflow, parent, self.budget, SimpleNamespace(stack=stack))
        self.assertEqual(captured, dict(collar={'collar-field'}, exterior={'volume_m3'},
                                        records={'spatial-record:state'}, store=self.store))
        leaked = {k for k in self.store.get('d'*64, budget=self.budget) if not k.startswith(reader['_PREFIXES'])}
        self.assertTrue(any(k.startswith(PW.PREFIX) for k in leaked) and any(k.startswith(Y.PREFIX) for k in leaked))
        del view, pref, mref, workflow, reader, namespace


if __name__ == '__main__':
    unittest.main(verbosity=2)
