"""S9: an unscoped compact metric reuses its in-process seal; anything else streams in full.

Runs on the owner's fixture (test_private_heat_indexed_runtime's module setup builds the
source-selected heat package). Run with the candidate or base runtime first on sys.path.
"""
from contextlib import contextmanager
import gc
from types import MappingProxyType
import unittest
from unittest.mock import patch

import mesh_tables as MT
import private_heat_indexed_runtime as P
import test_private_heat_indexed_runtime as TP
from test_private_heat_indexed_runtime import setUpModule, tearDownModule  # noqa: F401  (module fixture)


class Source:
    def __init__(self):
        self.changed, self.calls = False, 0

    def check_unchanged(self):
        self.calls += 1
        if self.changed:
            raise ValueError('support source changed on disk')


class Reader:
    """A blob reader that also carries a file-like source (the shape the scoped store readers have).

    Real unscoped readers are plain closures with no source (compact_store.CompactMeshStore.open's
    read_support, the convert_mesh lambdas): see closure_view.
    """
    def __init__(self, blobs, source):
        self.blobs, self.source = blobs, source

    def __call__(self, identity, size):
        raw = self.blobs[identity]
        if len(raw) != size:
            raise AssertionError('fixture reader length mismatch')
        return raw


def unscoped(record, budget, source=None):
    if source is None:
        return TP.FIXTURE.T.compact_fixture(record, budget)
    blobs = {}
    metadata, arrays = MT.pack_mesh(record, support_writer=blobs.__setitem__, budget=budget)
    return MT.CompactMesh(metadata, arrays, support_reader=Reader(blobs, source),
                          expected_geometry_id=TP.FIXTURE.T.E._hash(record), budget=budget)


def closure_view(record, budget):
    """An unscoped view whose reader is a plain closure over blobs, as compact_store's read_support."""
    blobs, calls = {}, []
    metadata, arrays = MT.pack_mesh(record, support_writer=blobs.__setitem__, budget=budget)

    def read_support(identity, size):
        calls.append(identity)
        return blobs[identity]
    view = MT.CompactMesh(metadata, arrays, support_reader=read_support,
                          expected_geometry_id=TP.FIXTURE.T.E._hash(record), budget=budget)
    calls.clear()
    return view, blobs, calls


def no_stream():
    return patch.object(MT.CompactMesh, 'iter_legacy_json', side_effect=AssertionError('second full stream'))


def counted_stream():
    return patch.object(MT.CompactMesh, 'iter_legacy_json', autospec=True,
                        side_effect=MT.CompactMesh.iter_legacy_json)


class SealReuse(unittest.TestCase):
    def setUp(self):
        self.budget = TP.WorkBudget(256 << 20)
        self.record = TP.FIXTURE.two_cell_record(self.budget)
        self.expected = P.metric_identity(TP.M.MimeticGeometry(self.record, budget=self.budget))

    def tearDown(self):
        del self.record
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def metric(self, view):
        return TP.M.MimeticGeometry.from_compact(view, budget=self.budget)

    def test_unscoped_view_reuses_seal_without_a_second_stream(self):
        view = unscoped(self.record, self.budget)
        self.assertIsNone(view.scope)
        metric = self.metric(view)
        with no_stream():
            self.assertEqual(P.metric_identity(metric), self.expected)
            self.assertEqual(P.metric_identity(metric), self.expected)
        del metric, view

    def test_frozen_arrays_cannot_be_made_writable(self):
        view = unscoped(self.record, self.budget)
        for name, array in view._arrays.items():
            with self.assertRaises(ValueError, msg=name):
                array.flags.writeable = True
        with self.assertRaises(TypeError):
            view._arrays['s.id'] = None
        with self.assertRaises(AttributeError):
            view._arrays = {}
        del view

    def test_changed_file_source_refuses(self):
        source = Source()
        view = unscoped(self.record, self.budget, source)
        metric = self.metric(view)
        with no_stream():
            self.assertEqual(P.metric_identity(metric), self.expected)
            self.assertEqual(source.calls, 1)
            source.changed = True
            with self.assertRaisesRegex(ValueError, 'support source changed'):
                P.metric_identity(metric)
        del metric, view

    def test_closure_reader_rereads_every_support_once_per_call(self):
        view, blobs, calls = closure_view(self.record, self.budget)
        metric = self.metric(view)
        supports = len(view._arrays['s.id'])
        self.assertGreater(supports, 0)
        with no_stream():
            self.assertEqual(P.metric_identity(metric), self.expected)
            self.assertEqual(len(calls), supports)
            self.assertEqual(P.metric_identity(metric), self.expected)
            self.assertEqual(len(calls), 2*supports)
        del metric, view, blobs

    def test_changed_or_missing_support_blob_refuses_as_before(self):
        # Same refusals as the base's full stream (this test passes on base and candidate).
        view, blobs, _ = closure_view(self.record, self.budget)
        metric = self.metric(view)
        ident = next(iter(blobs))
        original = blobs[ident]
        blobs[ident] = bytes(len(original))     # same length, different bytes
        with self.assertRaisesRegex(MT.MeshTablesRefused, 'support blob length/hash differs'):
            P.metric_identity(metric)
        del blobs[ident]                        # evicted or deleted
        with self.assertRaises(KeyError):
            P.metric_identity(metric)
        blobs[ident] = original
        self.assertEqual(P.metric_identity(metric), self.expected)
        del metric, view, blobs

    def test_source_without_freshness_check_streams(self):
        view = unscoped(self.record, self.budget, source=object())
        metric = self.metric(view)
        with counted_stream() as stream:
            self.assertEqual(P.metric_identity(metric), self.expected)
        self.assertEqual(stream.call_count, 1)
        del metric, view

    def test_substituted_array_streams_in_full(self):
        view = unscoped(self.record, self.budget)
        metric = self.metric(view)
        arrays = dict(view._arrays)
        arrays['s.id'] = arrays['s.id'].copy()  # same values, but no longer the frozen allocation
        object.__setattr__(view, '_arrays', MappingProxyType(arrays))
        with counted_stream() as stream:
            self.assertEqual(P.metric_identity(metric), self.expected)
        self.assertEqual(stream.call_count, 1)
        del metric, view, arrays

    def test_seal_not_naming_geometry_id_streams_in_full(self):
        from compact_contracts import LogicalIdentity
        view = unscoped(self.record, self.budget)
        metric = self.metric(view)
        sealed = view._logical_identity
        object.__setattr__(view, '_logical_identity',
                           LogicalIdentity(sealed.record_schema, 'f'*64, sealed.canonical_bytes))
        with counted_stream() as stream:
            # The full stream is authoritative: it re-derives this geometry_id.
            self.assertEqual(P.metric_identity(metric), self.expected)
        self.assertEqual(stream.call_count, 1)
        del metric, view

    def test_view_is_checked_before_every_support_read(self):
        # As _support_blob: view._check() immediately before each reader call (passes on base and candidate).
        # _check is an instance slot holding this view's freshness callable, so it is wrapped on the view itself.
        view, blobs, events = closure_view(self.record, self.budget)
        metric = self.metric(view)
        original = view._check

        def check():
            events.append('check')
            return original()
        object.__setattr__(view, '_check', check)
        self.assertEqual(P.metric_identity(metric), self.expected)
        reads = [index for index, event in enumerate(events) if event != 'check']
        self.assertGreater(len(reads), 1)
        self.assertTrue(all(index > 0 and events[index-1] == 'check' for index in reads), events)
        del metric, view, blobs

    def test_reader_with_iter_json_or_export_streams_in_full(self):
        view = unscoped(self.record, self.budget, Source())
        metric = self.metric(view)
        reader = view._reader

        class Held:
            def __init__(self, value):
                self.value = value

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        supports = {index: reader.blobs[view.ident(int(view._arrays['s.blob'][index]))]
                    for index in range(len(view._arrays['s.id']))}

        @contextmanager
        def iter_json(index):
            yield iter([Held(supports[index])])

        def export(index):
            raise AssertionError('export not expected on the identity route')
        for name, value in (('iter_json', iter_json), ('export', export)):
            setattr(reader, name, value)
            try:
                with counted_stream() as stream:
                    self.assertEqual(P.metric_identity(metric), self.expected)
                self.assertEqual(stream.call_count, 1, name)
            finally:
                delattr(reader, name)
        del metric, view, reader

    def test_arrays_from_two_allocations_stream_in_full(self):
        view, other = unscoped(self.record, self.budget), unscoped(self.record, self.budget)
        metric = self.metric(view)
        arrays = dict(view._arrays)
        arrays['s.id'] = other._arrays['s.id']  # frozen and _Bytes-backed, but another live allocation
        object.__setattr__(view, '_arrays', MappingProxyType(arrays))
        with counted_stream() as stream:
            self.assertEqual(P.metric_identity(metric), self.expected)
        self.assertEqual(stream.call_count, 1)
        del metric, view, other, arrays

    def test_cancel_is_still_honoured(self):
        view = unscoped(self.record, self.budget)
        metric = self.metric(view)
        import private_heat_issuer_resources_r4 as R
        with no_stream():
            calls = []
            with patch.object(R, 'check', side_effect=lambda cancel: calls.append(cancel)):
                self.assertEqual(P.metric_identity(metric, cancel='token'), self.expected)
            supports = len(view._arrays['s.id'])
            # Before, once per verified support read, and after: the stream's polling, kept.
            self.assertEqual(calls, ['token']*(supports+2))
            with patch.object(R, 'check', side_effect=[None, RuntimeError('cancelled')]):
                with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                    P.metric_identity(metric, cancel='token')
        del metric, view


if __name__ == '__main__':
    unittest.main()
