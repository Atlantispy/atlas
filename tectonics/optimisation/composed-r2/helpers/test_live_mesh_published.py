"""The produced mesh stays in memory, bound to its own v3 publication (R2 principle).

live_mesh_patch.finish used to close the produced view after publishing it and
reopen the unsealed candidate (CompactMeshStoreV3.open), whose cold admission
validates and streams every scalar through a candidate page walk: more than
24 minutes for the authentic IV1 mesh (profile r5, 16 Oct 2026). The produced
view is now kept and bound to the published root, which must describe exactly
its columns. These tests run the actual producer seam on a real candidate.
"""
import gc
import importlib
import importlib.machinery
import importlib.util
import shutil
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import exterior_mesh_patch
import mimetic_patch

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
BASE = HERE.parents[1]/'runtime-integration-r1'
OLD_BODY = HERE.parent/'probes'/'step8'/'claude-20261015'/'before-src'/'live_mesh_patch.py.before-r2mesh'
_temporary = None
_old_path = None


def setUpModule():
    global _temporary, _old_path
    if any(name == 'atlas_tectonics' or name.startswith('atlas_tectonics.') for name in sys.modules):
        raise RuntimeError('fresh process required; no live runtime patching')
    _temporary = tempfile.TemporaryDirectory(prefix='mesh-published-', dir=TASK/'_t')
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(BASE/'runtime-src'/'atlas_tectonics', package,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name, transform in (('integration_exterior_mesh.py', exterior_mesh_patch.transform),
                            ('integration_mimetic_heat.py', mimetic_patch.mimetic_source)):
        target = package/name
        target.write_text(transform(target.read_text(encoding='utf8')), encoding='utf8')
    _old_path = list(sys.path)
    sys.path[:0] = [str(Path(_temporary.name)), str(BASE/'ram'), str(BASE/'helpers'),
                   str(HERE.parent), str(HERE.parents[3]/'heat-repair-20261007')]
    importlib.import_module('atlas_tectonics.integration_exterior_mesh')


def tearDownModule():
    if _old_path is not None:
        sys.path[:] = _old_path
    if _temporary is not None:
        _temporary.cleanup()


def old_live_mesh():
    """The pre-16-Oct finish (close, then reopen the candidate): the mutant."""
    loader = importlib.machinery.SourceFileLoader('live_mesh_patch_before_r2mesh', str(OLD_BODY))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def no_candidate_reads(*_, **__):
    raise AssertionError('candidate column read')


class PublishedMeshTests(unittest.TestCase):
    def setUp(self):
        import native_transfer as N
        from atlas_tectonics.resources import WorkBudget
        from content_cache import create_retained_scope
        from interval_store_set import IntervalStoreSet
        from test_mesh_v3 import fixture
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='published-mesh')
        self.path = Path(tempfile.mkdtemp(prefix='store-', dir=_temporary.name))
        self.stores = IntervalStoreSet.create_migration(self.path/'catalog.json', workflow_id='a'*64, scope=self.scope)
        self.candidate = self.stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        self.old, self.record, self.source, self.partition, _ = fixture(self.scope, self.candidate, count=1)
        self.source_producer = {'kind': 'test-live-mesh-published'}
        self.producer = sha256(N._json(self.source_producer)).hexdigest()
        from atlas_tectonics import integration_differential_mesh as D
        self.expected = sha256(D._encode_mesh_record(self.record)).hexdigest()

    def tearDown(self):
        for name in ('old', 'record'):
            setattr(self, name, None)
        gc.collect()
        self.source.close(); self.partition.close()
        self.candidate.close(); self.stores.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())

    def context(self):
        return {'resolver': self.candidate, 'support_source': self.source, 'producer': self.producer}

    def produce(self, module=None):
        import live_mesh_patch as L
        import mesh_tables as M
        held = M.OwnedRow(self.record, M._Allocation(self.budget, 65536))
        return (module or L).finish(held, budget=self.budget, context=self.context())

    def adapter(self):
        from compact_store import CompactMeshStoreV3
        return CompactMeshStoreV3(self.candidate, scope=self.scope, support_source=self.source)

    def test_bound_view_reads_nothing_from_the_candidate(self):
        from heat_ledger_tables import _ordered_mesh_binding
        from segment_store import SegmentView
        with patch.object(SegmentView, 'read', no_candidate_reads):
            issued = self.produce()
            view = issued._compact
            self.assertIsNotNone(view._segment)
            self.assertIs(view._reader.source, self.source)
            stream = b''.join(view.iter_legacy_json())
            view.identity()
            for index in range(view.cell_count):
                view.cell(index)
            for index in range(view.face_count):
                view.face(index)
            ids = {'cell_ids': [view.cell_id(i) for i in range(view.cell_count)],
                   'face_ids': [view.face_id(i) for i in range(view.face_count)]}
            bound_binding = _ordered_mesh_binding(ids, view)
        self.assertEqual(sha256(stream).hexdigest(), self.expected)
        self.assertEqual(issued.geometry_id, self.expected)
        ref = view._segment.info.ref
        self.assertEqual(bound_binding['segment'], ref.to_wire())
        # The former route: the cold candidate admission reads every column.
        with patch.object(SegmentView, 'read', no_candidate_reads), self.assertRaisesRegex(AssertionError, 'candidate column read'):
            self.adapter().open(ref, expected_geometry_id=self.expected)
        gc.collect()
        reopened = self.adapter().open(ref, expected_geometry_id=self.expected)
        self.assertEqual(b''.join(reopened.iter_legacy_json()), stream)
        self.assertEqual(_ordered_mesh_binding(ids, reopened), bound_binding)
        self.assertEqual(reopened.identity(), view.identity())
        reopened.close()
        del issued, reopened
        gc.collect()
        view.close()

    def test_republication_and_persist_take_the_reference_route(self):
        import spatial_workflow_patch as SW
        from segment_store import SegmentBackend, SegmentView
        issued = self.produce()
        view = issued._compact
        ref = view._segment.info.ref
        with patch.object(SegmentBackend, 'publish', side_effect=AssertionError('second publication')), \
                patch.object(SegmentView, 'read', no_candidate_reads):
            self.assertEqual(self.adapter().publish(view, producer=self.producer), ref)
            # As spatial_records_patch calls it: no explicit support source.
            persisted = SW.persist_mesh(self.candidate, view, self.source_producer, budget=self.budget)
        self.assertEqual(persisted.value['segment'] if hasattr(persisted, 'value') else persisted['segment'],
                         ref.to_wire())
        del persisted, issued
        gc.collect()
        view.close()

    def test_root_that_does_not_describe_the_view_is_refused(self):
        import live_mesh_patch as L
        import mesh_tables as M
        issued = self.produce()
        view = issued._compact
        ref = view._segment.info.ref
        del issued
        gc.collect()
        before = self.budget.reserved_bytes
        produced = M.CompactMesh(*M.pack_mesh(self.record, support_writer=lambda *_: None, budget=self.budget),
            support_reader=self.old._reader, expected_geometry_id=self.expected, budget=self.budget,
            scope=self.scope)
        original = L._expected_root
        def altered(*args):
            inline, moved = original(*args)
            for root in (inline, moved):
                root['arrays']['static.bytes'] = dict(root['arrays']['static.bytes'], sha256='0'*64)
            return inline, moved
        with patch.object(L, '_expected_root', altered), \
                self.assertRaisesRegex(ValueError, 'published mesh root differs from the produced mesh'):
            L._published(self.context(), self.scope, produced, ref)
        # Unaltered, the same produced view binds to the same root.
        bound = L._published(self.context(), self.scope, produced, ref)
        self.assertEqual(b''.join(bound.iter_legacy_json()), b''.join(view.iter_legacy_json()))
        bound.close()
        del bound, produced
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)
        view.close()

    def test_old_body_reopens_through_the_candidate(self):
        """The mutant: the pre-change finish fails the no-candidate-read guard."""
        from segment_store import SegmentView
        old = old_live_mesh()
        with patch.object(SegmentView, 'read', no_candidate_reads), \
                self.assertRaisesRegex(AssertionError, 'candidate column read'):
            self.produce(old)
        gc.collect()


if __name__ == '__main__':
    unittest.main()
