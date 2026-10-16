"""W1 segment_store fixes: exact output against the base module (w1ref_segment_store),
L8 canonical conflict checks, L11 lone surrogates, F8 empty-range reads, L13 builder
booking, L14 parse booking on crafted manifests; L15 page reuse is reverted, so
later-interval refs and pages stay byte-identical to base."""
import gc
import json
import sys
import tempfile
import tracemalloc
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
RUNTIME = HERE.parents[1] / 'runtime-integration-r1' / 'runtime-src'
sys.path[:0] = [str(HERE), str(RUNTIME), str(HERE.parent)]

import segment_store as S
import w1ref_segment_store as BASE
from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError, LogicalIdentity
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
from test_segment_store import GeneratedSource


def identity(name):
    return LogicalIdentity('fixture.record.v1', sha256(name.encode()).hexdigest(), 99)


def sources(scope, module):
    # Several arrays, one empty, unicode names in UTF-8 order, partial last chunk.
    return [GeneratedSource(scope, 0, name='a-empty'),
            GeneratedSource(scope, 3 * 65536 + 17, name='b-payload'),
            GeneratedSource(scope, 40, name='c-é', dtype='|u1'),
            GeneratedSource(scope, 16 * 65536 + 5, name='d-many')]


class Fixture:
    def __init__(self, root, label):
        self.budget = WorkBudget(512 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='w1-seg-' + label)
        self.root = root / label
        self.root.mkdir()
        self.stores = IntervalStoreSet.create_migration(self.root / 'catalog.json', workflow_id='a' * 64,
                                                       scope=self.scope)
        self.candidate = self.stores.begin_interval(None, producer_identity='b' * 64, runtime_identity='c' * 64)

    def publish(self, module, srcs, *, name='logical', metadata=b'{"k":1}', candidate=None):
        ident = identity(name)
        return module.SegmentBackend().publish(candidate or self.candidate, record_schema=ident.record_schema,
            identity=ident, metadata=metadata, arrays=lambda: iter(srcs), producer='b' * 64,
            representation_profile='fixture.columns.v1', scope=self.scope)

    def next_interval(self, ref):
        sealed = self.candidate.seal(ref)
        self.stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
        self.candidate = self.stores.begin_interval(self.stores.head, producer_identity='b' * 64,
                                                    runtime_identity='c' * 64)

    def manifests(self):
        # The writer's own connection sees its open transaction.
        return dict(self.candidate._db.execute('SELECT id, body FROM snapshots'))

    def close(self):
        self.candidate.close()
        self.stores.close()
        gc.collect()
        self.scope.close()


class W1SegmentTests(unittest.TestCase):
    def setUp(self):
        (TASK / '_t').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='w1-seg-', dir=TASK / '_t')
        self.root = Path(self.temp.name)
        self.fixtures = []

    def tearDown(self):
        for fixture in self.fixtures:
            fixture.close()
        self.temp.cleanup()

    def fixture(self, label):
        fixture = Fixture(self.root, label)
        self.fixtures.append(fixture)
        return fixture

    def test_first_interval_output_byte_identical_to_base(self):
        new, base = self.fixture('new'), self.fixture('base')
        ref_new = new.publish(S, sources(new.scope, S))
        ref_base = base.publish(BASE, sources(base.scope, BASE))
        self.assertEqual(ref_new.to_wire(), ref_base.to_wire())
        self.assertEqual(new.manifests(), base.manifests())
        # Every read returns the same bytes through the new single-walk read.
        view_new = S.SegmentBackend().open(new.candidate, ref_new, scope=new.scope)
        view_base = BASE.SegmentBackend().open(base.candidate, ref_base, scope=base.scope)
        try:
            for name, size in (('b-payload', 3 * 65536 + 17), ('c-é', 40), ('d-many', 16 * 65536 + 5)):
                for start, stop in ((0, size), (1, 2), (65535, 65537), (size - 1, size), (7, 7), (size, size)):
                    if stop > size:
                        continue
                    with view_new.read(name, start, stop, max_owned_bytes=size) as a, \
                            view_base.read(name, start, stop, max_owned_bytes=size) as b:
                        self.assertEqual(a.value, b.value)
            for module, view in ((S, view_new), (BASE, view_base)):
                with view.read('a-empty', 0, 0, max_owned_bytes=1) as empty:
                    self.assertEqual(empty.value, b'')
                for bad in ((0, size + 1), (5, 4)):
                    with self.assertRaises(ContractError):
                        view.read('d-many', *bad, max_owned_bytes=1 << 30)
                with self.assertRaises(KeyError):
                    view.read('missing', 0, 0, max_owned_bytes=1)
                with self.assertRaisesRegex(ContractError, 'allowance'):
                    view.read('d-many', 0, 100, max_owned_bytes=99)
        finally:
            view_new.close()
            view_base.close()

    def test_empty_range_read_decodes_no_chunk(self):
        new = self.fixture('empty')
        ref = new.publish(S, sources(new.scope, S))
        view = S.SegmentBackend().open(new.candidate, ref, scope=new.scope)
        calls = []
        original = S._chunk
        with patch.object(S, '_chunk', lambda *a: calls.append(a) or original(*a)):
            with view.read('b-payload', 5, 5, max_owned_bytes=1) as owned:
                self.assertEqual(owned.value, b'')
            self.assertEqual(calls, [])
            with view.read('b-payload', 5, 6, max_owned_bytes=1):
                pass
            self.assertEqual(len(calls), 1)
        view.close()

    def test_republish_conflict_compares_canonical_bytes(self):
        new = self.fixture('alias')
        first = new.publish(S, [GeneratedSource(new.scope, 64)], metadata=b'{"a":1}')
        self.assertEqual(new.publish(S, [GeneratedSource(new.scope, 64)], metadata=b'{"a":1}'), first)
        for alias in (b'{"a":true}', b'{"a":1.0}', b'{"a":2}'):
            with self.subTest(alias=alias), self.assertRaisesRegex(ContractError, 'invocation conflict'):
                new.publish(S, [GeneratedSource(new.scope, 64)], metadata=alias)

    def test_lone_surrogates_refuse_as_contract_error(self):
        with self.assertRaises(ContractError):
            S.ArrayInfo('bad-\ud800', '|u1', (1,), 1)
        new = self.fixture('surrogate')
        with self.assertRaises(ContractError):
            ident = identity('x')
            S.SegmentBackend().publish(new.candidate, record_schema=ident.record_schema, identity=ident,
                metadata=b'{}', arrays=lambda: iter(()), producer='b' * 64,
                representation_profile='bad-\udc00', scope=new.scope)

    def test_builder_books_run_budget_not_retained_scope(self):
        new = self.fixture('builder')
        seen = []
        original = S._workspace
        def spy(budget, size, purpose):
            seen.append((purpose, size))
            return original(budget, size, purpose)
        with patch.object(S, '_workspace', spy):
            new.publish(S, [GeneratedSource(new.scope, 4 * 65536)])
        self.assertIn(('segment-index-builder', S.BUILDER_WORK_BYTES), seen)
        self.assertNotIn('retained:segment-index-builder', new.scope.stats().purpose_bytes)
        self.assertLess(S.BUILDER_WORK_BYTES, 1 << 20)

    def test_crafted_manifest_parse_booking_covers_real_memory(self):
        # tracemalloc for memory only (nothing timed). Tamper-shaped canonical
        # JSON near the 256 KiB manifest bound and a legitimate leaf page.
        n = 70000
        shapes = {
            'empty-lists': b'[' + b','.join([b'[]'] * n) + b']',
            'empty-objects': b'[' + b','.join([b'{}'] * n) + b']',
            'many-keys': json.dumps({f'k{i:05d}': 0 for i in range(23000)}, sort_keys=True,
                                    separators=(',', ':')).encode(),
            'short-strings': json.dumps([f'{i % 97:02d}' for i in range(50000)], separators=(',', ':')).encode(),
            'one-key-objects': b'[' + b','.join([b'{"ab":0}'] * 28000) + b']',
        }
        results = {}
        for label, raw in shapes.items():
            self.assertLessEqual(len(raw), S.SEGMENT_MANIFEST_BYTES)
            gc.collect()
            tracemalloc.start()
            base = tracemalloc.get_traced_memory()[0]
            value = S.parse(raw)
            held = tracemalloc.get_traced_memory()[0] - base
            tracemalloc.stop()
            del value
            booked = S._parse_charge(raw)
            results[label] = {'raw': len(raw), 'held': held, 'booked': booked, 'old': 8 * len(raw) + 65536}
            self.assertLessEqual(held, booked, label)
        print(json.dumps(results, sort_keys=True))

    def test_later_interval_refs_and_pages_byte_identical_to_base(self):
        # x-storage-fix A1: L15 (ancestor index-page reuse) is reverted, so a
        # publish in interval 1 that shares byte-identical pages with interval
        # 0 re-stages them exactly as base: SegmentRef wire and every stored
        # manifest of the interval-1 candidate equal base.
        for case in ('changed', 'same'):
            with self.subTest(case=case):
                results = {}
                for label, module in (('new', S), ('base', BASE)):
                    fx = self.fixture(f'{case}-{label}')
                    ref0 = fx.publish(module, [GeneratedSource(fx.scope, 40 * 65536, name='payload')], name='r0')
                    fx.next_interval(ref0)
                    src = GeneratedSource(fx.scope, 40 * 65536, name='payload', changed_last=(case == 'changed'))
                    ref1 = fx.publish(module, [src], name='r1')
                    view = S.SegmentBackend().open(fx.candidate, ref1, scope=fx.scope)
                    try:
                        with view.read('payload', 0, 40 * 65536, max_owned_bytes=40 * 65536) as owned:
                            body = sha256(owned.value).hexdigest()
                    finally:
                        view.close()
                    results[label] = (ref1.to_wire(), fx.manifests(), body)
                self.assertEqual(results['new'][0], results['base'][0])
                self.assertEqual(results['new'][0]['array_bindings']['root_key']['interval'], 1)
                self.assertEqual(results['new'][1], results['base'][1])
                self.assertEqual(results['new'][2], results['base'][2])


if __name__ == '__main__':
    unittest.main()
