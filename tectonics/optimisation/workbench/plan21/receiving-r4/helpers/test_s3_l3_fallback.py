"""S3 fallback on an actual S1A stored segment with current L3 carried pages.

This is a bounded behavioural case for the combined gate, not an IV parity run.
No production switch is bypassed. The only planted runtime fault is a transient
MemoryLimitError raised inside the real admission stats batch after it has
adopted a real, charged L3 registry. The failure owns both run and retained
workspace in a traceback cycle, matching the lifetime the fallback must clear.
"""
from contextlib import contextmanager
import gc
from pathlib import Path
import shutil
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from content_cache import ChargeSpec, create_retained_scope
from interval_store_set import IntervalStoreSet
import record_tables as T
import record_views as RV
from segment_store import SegmentBackend
import spatial_validation_patch as V

SCHEMA = 'atlas.spatial-cells.v1'
REGISTRY = 'retained:record-batch-page-borrows'
FAULT = 'retained:s3-l3-fault-workspace'
EVIDENCE = []


def native_row(**changes):
    row = dict(cell_id='native:0', source_key=['synthetic', 0],
               volume_m3=['0x5', '0x1'], geometry_volume_error_m3=['0x0', '0x1'],
               exact={'enthalpy_j': ['0x7', '0x1']})
    row.update(changes)
    return row


def accounting(fx):
    stats, cols = fx.scope.stats(), fx.record._columns
    return dict(run=fx.budget.reserved_bytes,
                record_workspace=fx.budget.statistics()['categories'].get('record-workspace', 0),
                retained=fx.scope.retained_budget.reserved_bytes,
                pinned=stats.pinned_bytes,
                registry=stats.purpose_bytes.get(REGISTRY, 0),
                fault=stats.purpose_bytes.get(FAULT, 0),
                carried_booked=cols._carried_booked,
                carried_raw=cols._carried_raw,
                carried_pages=0 if cols._carried is None else len(cols._carried.value),
                process_booked=RV.carry_stats()['booked'])


def outcome(read):
    try:
        return ('OK', read())
    except Exception as error:  # exact semantic and budget errors are compared
        return ('RAISE', type(error), error.args)


@contextmanager
def stored(test, rows):
    directory = Path(tempfile.mkdtemp(prefix='s3-l3-'))
    budget = WorkBudget(256 << 20)
    scope = create_retained_scope(budget, process_epoch='s3-l3-fallback')
    stores = candidate = segment = record = root = None
    mappings = []
    try:
        stores = IntervalStoreSet.create_migration(str(directory/'catalog.json'),
                                                   workflow_id='1'*64, scope=scope)
        candidate = stores.begin_interval(None, producer_identity='2'*64, runtime_identity='3'*64)
        packed = T.RecordCodec().pack_record(rows, record_schema=SCHEMA,
                                             scope=scope, check=lambda: None)
        backend = SegmentBackend()
        try:
            with packed.metadata_bytes() as metadata:
                ref = backend.publish(candidate, record_schema=SCHEMA, identity=packed.identity(),
                                      metadata=metadata.value, arrays=packed.array_sources,
                                      producer='2'*64, representation_profile=T.SCHEMA, scope=scope)
        finally:
            packed.close()
        del packed, metadata
        promoted = candidate.seal(ref)
        stores.promote(promoted, expected_catalog_digest=promoted.expected_catalog_digest)
        del promoted
        segment = backend.open(stores, ref, scope=scope)
        record = RV.CompactRecord.from_segment(segment)
        root = record.root()
        test.assertIsInstance(record._columns, RV._Segment)
        start = V.start_rows(root)
        mappings.append(start)
        carried = V.carried_rows(start)
        mappings.append(carried)
        V.carry(carried, 'child:0', 'native:0', None)
        fx = SimpleNamespace(directory=directory, budget=budget, scope=scope, stores=stores,
                             segment=segment, record=record, root=root, start=start, carried=carried)
        yield fx
    finally:
        for mapping in reversed(mappings):
            mapping._owned.close()
        if root is not None:
            root.close()
        if record is not None:
            record.close()
        if segment is not None:
            segment.close()
        if candidate is not None:
            candidate.close()
        if stores is not None:
            stores.close()
        gc.collect()
        scope.close()
        test.assertEqual((budget.reserved_bytes, scope.retained_budget.reserved_bytes), (0, 0))
        # S1A owns handles in its store set: close it before removing the directory.
        if directory.resolve().parent != Path(tempfile.gettempdir()).resolve():
            raise AssertionError('fixture cleanup escaped its temporary parent')
        def remove_readonly(function, path, error):
            if not isinstance(error, PermissionError):
                raise error
            Path(path).chmod(stat.S_IWRITE)
            function(path)
        shutil.rmtree(directory, onexc=remove_readonly)
        test.assertFalse(directory.exists())


def prime(test, fx):
    """Reset optional pages, then carry a real authenticated node page."""
    gc.collect()
    cols = fx.record._columns
    cols._drop_batch_pages()
    fx.scope.evict_unpinned(requested_bytes=1 << 40)
    fx.start._admitted = None
    fx.durable = accounting(fx)
    with fx.record._read_batch():
        cols.value('node.kind', 0)
    test.assertIsNotNone(cols._carried, 'the fixture did not carry a stored page')
    test.assertGreater(len(cols._carried.value), 0)
    test.assertGreater(cols._carried_raw, 0)
    booked = cols._carried.charged_bytes + sum(p._owner.charged_bytes for p in cols._carried.value.values())
    test.assertEqual(cols._carried_booked, booked)
    test.assertEqual(RV.carry_stats()['booked'], booked)
    test.assertGreater(fx.scope.stats().pinned_bytes, 0)
    return accounting(fx)


def limited(fx, budget, free, read):
    hold = budget.max_bytes-budget.reserved_bytes-free
    if hold < 0:
        raise AssertionError('free point exceeds current budget')
    with budget.reserve(hold, category='s3-l3-test-hold'):
        return outcome(read)


class S3L3FallbackTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        gc.collect()
        self.assertEqual(RV.carry_stats()['booked'], 0)

    def test_budget_fallback_adopts_carried_pages_and_releases_failure_frames(self):
        """Both start and carried maps fall back after a real stored-page batch fails."""
        for which in ('start', 'carried'):
            with self.subTest(mapping=which), stored(self, [native_row()]) as fx:
                mapping, key = (fx.start, 'native:0') if which == 'start' else (fx.carried, 'child:0')
                expected = mapping.get(key)['volume_m3']
                before = prime(self, fx)
                durable = fx.durable
                registry_id = id(fx.record._columns._carried)
                counters = RV.carry_stats()
                real_stats, real_row = RV._node_stats, V._StartRows._row
                events = []
                failed = False

                def fail_once(*args, **kwargs):
                    nonlocal failed
                    if failed:
                        return real_stats(*args, **kwargs)
                    failed = True
                    cols = fx.record._columns
                    self.assertIsNotNone(cols._batch_pages)
                    self.assertEqual(id(cols._batch_pages), registry_id)
                    self.assertGreater(len(cols._batch_pages.value), 0)
                    # Execute the actual stats walk before the bounded injected refusal.
                    real_stats(*args, **kwargs)
                    run_workspace = T.Scratch(fx.budget, 8192)
                    with fx.scope.reserve(ChargeSpec('s3-l3-fault-workspace', 8192), required=True) as reservation:
                        retained_workspace = reservation.commit(bytearray(8192))
                    events.append(('fault', accounting(fx)))
                    failure = MemoryLimitError('injected S3 admission refusal after L3 adoption')
                    workspace = [run_workspace, retained_workspace, failure]
                    workspace.append(workspace)
                    failure.workspace = workspace
                    raise failure

                def whole(this, at):
                    # This boundary is reached by S3's actual fallback, before export.
                    snapshot = accounting(fx)
                    events.append(('whole', snapshot))
                    self.assertTrue(failed)
                    self.assertEqual(snapshot['record_workspace'], 0, 'failed run workspace reached fallback')
                    self.assertEqual(snapshot['fault'], 0, 'failed retained workspace reached fallback')
                    self.assertEqual(snapshot['registry'], 0, 'failed batch registry reached fallback')
                    self.assertEqual(snapshot['pinned'], 0, 'failed page pins reached fallback')
                    self.assertEqual(snapshot['process_booked'], 0)
                    return real_row(this, at)

                gc.disable()
                try:
                    with patch.object(RV, '_node_stats', fail_once), patch.object(V._StartRows, '_row', whole):
                        got = mapping[key]['volume_m3']
                    # No external collection is allowed between the read and this check.
                    after = accounting(fx)
                    self.assertEqual(after['fault'], 0)
                finally:
                    gc.enable()
                self.assertEqual(got, expected)
                self.assertEqual([name for name, _ in events], ['fault', 'whole'])
                self.assertGreater(events[0][1]['fault'], 8192)
                self.assertGreater(events[0][1]['run'], before['run'])
                self.assertGreater(events[0][1]['retained'], before['retained'])
                self.assertGreater(RV.carry_stats()['adopted']-counters['adopted'], 0)
                self.assertGreater(RV.carry_stats()['dropped_exception']-counters['dropped_exception'], 0)
                # Drop optional state to compare the same durable state before/after.
                fx.record._columns._drop_batch_pages()
                fx.scope.evict_unpinned(requested_bytes=1 << 40)
                settled = accounting(fx)
                self.assertEqual((settled['run'], settled['retained']),
                                 (durable['run'], durable['retained']))
                self.assertEqual(settled['registry'], 0)
                self.assertEqual(settled['pinned'], 0)
                self.assertEqual(settled['fault'], 0)
                EVIDENCE.append(dict(case='budget-fallback', mapping=which, durable=durable, before=before,
                                     events=events, after=after, settled=settled))
                del mapping

    def test_sealed_semantic_fallbacks_match_whole_rows_under_both_budgets(self):
        """Absent field/name and non-object exact fallbacks keep whole-row outcomes."""
        missing_field = native_row()
        del missing_field['volume_m3']
        shapes = (
            ('absent-field', missing_field, lambda row: row['volume_m3']),
            ('absent-name', native_row(), lambda row: row['exact']['absent']),
            ('exact-none', native_row(exact=None), lambda row: row['exact']['enthalpy_j']),
            ('exact-zero', native_row(exact=0), lambda row: row['exact']['enthalpy_j']),
            ('exact-list', native_row(exact=[]), lambda row: row['exact']['enthalpy_j']),
        )
        # Fixed bounded sweep includes funding refusal, pressure, and ample states.
        points = (0, 256 << 10, 4 << 20, 16 << 20, 32 << 20, 64 << 20)
        for label, row, read in shapes:
            with self.subTest(shape=label), stored(self, [row]) as fx:
                for which, mapping, key in (('start', fx.start, 'native:0'), ('carried', fx.carried, 'child:0')):
                    for budget_name, budget in (('run', fx.budget), ('retained', fx.scope.retained_budget)):
                        answers = 0
                        for free in points:
                            prime(self, fx)
                            expected = limited(fx, budget, free, lambda m=mapping, k=key, r=read: r(m.get(k)))
                            prime(self, fx)
                            actual = limited(fx, budget, free, lambda m=mapping, k=key, r=read: r(m[k]))
                            self.assertEqual(actual, expected, (label, which, budget_name, free))
                            answers += actual[1] is not MemoryLimitError
                        self.assertGreater(answers, 0, 'sweep never reached the semantic fallback')
                        EVIDENCE.append(dict(case=label, mapping=which, budget=budget_name,
                                             free_points=list(points), semantic_answers=answers))
                del mapping


if __name__ == '__main__':
    unittest.main()
