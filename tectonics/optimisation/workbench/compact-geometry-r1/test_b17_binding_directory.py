"""B17 (backlog item 17): the per-view binding directory.

Named lookups (SegmentView._entries(name=...)) are answered from the leaves the opening walk
authenticated, instead of re-walking from the root. These tests prove the answers are the
walk's answers (same entries, order and refusals), that no index page is read after open,
that the booking covers the real retained size, and that a declined booking falls back to the
walk. Synthetic data only (real native SQLite files under the tree's _t folder).
"""
import gc
from hashlib import sha256
import json
import threading
import tracemalloc
import unittest
from concurrent.futures import CancelledError
from unittest.mock import patch

import segment_store as S
import test_segment_store as fixture
from atlas_tectonics.resources import MemoryLimitError
from compact_contracts import ContractError

CHUNK = S.NATIVE_CHUNK_BYTES


def _names():
    # UTF-8 order is the publish order; include 2-, 3- and 4-byte characters.
    names = [f'a{i:03d}' for i in range(40)] + ['big', 'zé', 'zж', 'z\U0001d538']
    return sorted(names, key=lambda n: n.encode('utf-8'))


def _size(name):
    if name == 'big':
        return 21 * CHUNK + 7        # 22 leaves: spans two leaf pages
    index = int(name[1:]) if name[1:].isdigit() else 3
    return (0, 1, 3, CHUNK, 3 * CHUNK + 5, 17)[index % 6]


def _wire(entries):
    # Exact spelling, key order included (json.dumps without sort_keys).
    return [json.dumps(entry) for entry in entries]


def _outcome(call):
    # A call's answer, or its refusal by exception type and message.
    try:
        return ('ok', call())
    except Exception as error:  # noqa: BLE001 - compared, not handled
        return ('refused', type(error).__name__, str(error))


def _walk_only(view):
    directory, view._directory = view._directory, None
    if directory is not None:
        directory.close()
    return view


class BindingDirectoryTests(unittest.TestCase):
    setUp = fixture.SegmentStoreTests.setUp
    tearDown = fixture.SegmentStoreTests.tearDown
    publish = fixture.SegmentStoreTests.publish
    open = fixture.SegmentStoreTests.open
    promote = fixture.SegmentStoreTests.promote

    def mixed(self):
        sources = [fixture.GeneratedSource(self.scope, _size(name), name=name) for name in _names()]
        return self.publish(sources)

    def walk(self, view, **kwargs):
        return list(view._walk(view._owner.value['index'], **kwargs))

    def queries(self, view):
        for name in _names() + ['', 'a', 'a0005', 'zz', 'ÿ']:
            size = _size(name) if name in _names() else 5
            yield {'name': name}
            for start, stop in ((0, 0), (0, 1), (0, size), (1, size + 3), (CHUNK - 1, CHUNK + 1),
                                (CHUNK, 2 * CHUNK), (size, size), (size + 1, size + 9),
                                (5 * CHUNK + 3, 17 * CHUNK + 1), (21 * CHUNK, 21 * CHUNK + 7)):
                yield {'name': name, 'start': start, 'stop': stop}

    def assert_same_as_walk(self, view):
        self.assertIsNotNone(view._directory)
        compared = 0
        for query in self.queries(view):
            got = list(view._entries(**query))
            self.assertEqual(_wire(got), _wire(self.walk(view, **query)), query)
            compared += 1
        self.assertGreater(compared, 400)

    def test_named_lookups_equal_the_walk_on_candidate_and_sealed_views(self):
        ref = self.mixed()
        self.assert_same_as_walk(self.open(ref))
        self.promote(ref)
        sealed = self.open(ref, self.stores)
        with sealed.verified_read():
            self.assert_same_as_walk(sealed)

    def test_reads_and_info_need_no_index_page_after_open(self):
        ref = self.mixed()
        view = self.open(ref)
        before = view.read('big', 3 * CHUNK + 1, 19 * CHUNK + 2, max_owned_bytes=17 * CHUNK)
        with patch.object(self.candidate, 'resolve_manifest', side_effect=AssertionError('index page read')):
            again = view.read('big', 3 * CHUNK + 1, 19 * CHUNK + 2, max_owned_bytes=17 * CHUNK)
            self.assertEqual(again.value, before.value)
            info = view.info.array('z\U0001d538')
            self.assertEqual(info.value.shape, (_size('z\U0001d538'),))
            info.close()
            with self.assertRaises(KeyError):
                view.info.array('missing')
            empty = view.read('a000', 0, 0, max_owned_bytes=0)
            self.assertEqual(empty.value, b'')
            empty.close()
            again.close()
        before.close()

    def test_invalid_names_refuse_or_fall_back_exactly_as_the_walk(self):
        view = self.open(self.mixed())
        with self.assertRaises(ContractError):
            list(self.walk(view, name='\ud800'))
        with self.assertRaises(ContractError):
            list(view._entries(name='\ud800'))
        for bad in (123, None, b'big'):
            # Non-text names never use the directory: the walk answers (or refuses) them.
            try:
                expected = ('ok', _wire(self.walk(view, name=bad)))
            except ContractError as error:
                expected = ('refused', str(error))
            try:
                got = ('ok', _wire(view._entries(name=bad)))
            except ContractError as error:
                got = ('refused', str(error))
            self.assertEqual(got, expected, bad)
        empty = self.open(self.publish([], name='empty-record'))
        self.assertIsNotNone(empty._directory)
        self.assertEqual(list(empty._entries(name='\ud800')), list(self.walk(empty, name='\ud800')))
        self.assertEqual(list(empty._entries(name='x', start=0, stop=1)), [])
        # A start without a stop, or non-integer bounds, walk (b17 refuter F5): same
        # answer or the same refusal, by type and message.
        for name in ('big', 'a001', 'zé', 'zz', ''):
            for start, stop in ((3, None), (0, None), (None, 7), (True, 9), (2, 9.5)):
                query = {'name': name, 'start': start, 'stop': stop}
                self.assertEqual(_outcome(lambda q=query: _wire(view._entries(**q))),
                                 _outcome(lambda q=query: _wire(self.walk(view, **q))), query)

    def test_cancelled_view_refuses_named_lookups(self):
        event = threading.Event()
        ref = self.mixed()
        view = self.backend.open(self.candidate, ref, scope=self.scope, cancel=event)
        self.views.append(view)
        self.assertEqual(len(list(view._entries(name='big'))), 22)
        event.set()
        with self.assertRaises(CancelledError):
            list(view._entries(name='big'))

    def test_booking_covers_the_real_retained_size_and_is_released(self):
        ref = self.mixed()
        gc.collect()
        tracemalloc.start(1)
        try:
            view = self.open(ref)
            purposes = self.scope.stats().purpose_bytes
            booked = purposes['retained:segment-binding-directory']
            self.assertEqual(purposes.get('retained:segment-binding-directory-build', 0), 0)
            measured = S._directory_bytes(view._directory.value)
            gc.collect()
            held = tracemalloc.take_snapshot()
            directory, view._directory = view._directory, None
            directory.close()
            del directory
            gc.collect()
            released = tracemalloc.take_snapshot()
        finally:
            tracemalloc.stop()
        # held - released: the bytes that dropping the directory freed.
        real = sum(stat.size_diff for stat in held.compare_to(released, 'filename'))
        self.assertGreater(real, 0)
        self.assertGreaterEqual(measured, real, (measured, real))
        self.assertLessEqual(measured, int(1.35 * real) + S.DIRECTORY_FIXED_BYTES, (measured, real))
        self.assertGreaterEqual(booked, measured)
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:segment-binding-directory', 0), 0)
        # Named lookups still work after the directory is gone (the walk answers).
        self.assertEqual(len(list(view._entries(name='big'))), 22)
        MEASURED.update(real=real, measured=measured, booked=booked, leaves=view._owner.value['index']['leaf_count'],
                        arrays=view.ref.array_bindings.count)

    def test_close_releases_the_directory_booking(self):
        view = self.open(self.mixed())
        self.assertGreater(self.scope.stats().purpose_bytes['retained:segment-binding-directory'], 0)
        view.close()
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:segment-binding-directory', 0), 0)

    def test_refused_close_keeps_the_view_and_its_directory_usable(self):
        # An escaped result still borrows the view's owner, so close refuses and
        # the view stays open (test_record_views relies on this); its directory
        # must stay open with it (b17 suites, 16 Oct: it was closed first).
        view = self.open(self.mixed())
        escaped = view.info.array('big')
        with self.assertRaises(RuntimeError):
            view.close()
        self.assertIsNotNone(view._directory)
        self.assert_same_as_walk(view)
        with view.read('big', 21 * CHUNK, 21 * CHUNK + 7, max_owned_bytes=7) as owned:
            self.assertEqual(len(owned.value), 7)
        escaped.close()
        view.close()
        self.assertIsNone(view._directory)
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:segment-binding-directory', 0), 0)

    def test_declined_bookings_fall_back_to_the_walk(self):
        ref = self.mixed()
        original = self.scope.reserve
        for declined in ('segment-binding-directory-build', 'segment-binding-directory'):
            def reserve(spec, *, required=True, cancel=None, declined=declined):
                if spec.purpose == declined:
                    return None
                return original(spec, required=required, cancel=cancel)
            with patch.object(self.scope, 'reserve', side_effect=reserve):
                view = self.open(ref)
            self.assertIsNone(view._directory)
            purposes = self.scope.stats().purpose_bytes
            self.assertEqual(purposes.get('retained:segment-binding-directory-build', 0), 0)
            for query in list(self.queries(view))[:60]:
                self.assertEqual(_wire(view._entries(**query)), _wire(self.walk(view, **query)))

    def starve_walk(self, *, refusals):
        # Required bookings refuse while (after) the directory build booking is granted,
        # as when the accepted build booking leaves the walk too little headroom.
        original, state = self.scope.reserve, {'build': False, 'refused': 0}

        def reserve(spec, *, required=True, cancel=None):
            if required and state['build'] and state['refused'] < refusals:
                state['refused'] += 1
                raise MemoryLimitError('fixture: headroom taken by the directory build booking')
            if spec.purpose == 'segment-binding-directory-build':
                state['build'] = True
            return original(spec, required=required, cancel=cancel)
        return patch.object(self.scope, 'reserve', side_effect=reserve), state

    def test_walk_starved_by_the_build_booking_reopens_without_a_directory(self):
        # B17 refuter F2: an accepted build booking must never make the open refuse
        # where the walk alone fits; open releases it and validates as before.
        ref = self.mixed()
        starving, state = self.starve_walk(refusals=1)
        with starving:
            view = self.open(ref)
        self.assertEqual(state['refused'], 1)
        self.assertIsNone(view._directory)
        purposes = self.scope.stats().purpose_bytes
        self.assertEqual(purposes.get('retained:segment-binding-directory-build', 0), 0)
        self.assertEqual(purposes.get('retained:segment-binding-directory', 0), 0)
        for query in list(self.queries(view))[:60]:
            self.assertEqual(_wire(view._entries(**query)), _wire(self.walk(view, **query)))

    def test_walk_that_cannot_fit_at_all_still_refuses_and_releases(self):
        ref = self.mixed()
        starving, state = self.starve_walk(refusals=10 ** 9)
        with starving, self.assertRaises(MemoryLimitError):
            self.backend.open(self.candidate, ref, scope=self.scope)
        self.assertGreaterEqual(state['refused'], 2)
        gc.collect()
        purposes = self.scope.stats().purpose_bytes
        self.assertEqual(purposes.get('retained:segment-binding-directory-build', 0), 0)
        self.assertEqual(purposes.get('retained:segment-binding-directory', 0), 0)

    def test_lookups_keep_the_resolver_lifecycle_refusals(self):
        # B17 refuter F3: once the candidate is closed, sealed or failed, or the store set
        # is closed, directory lookups refuse exactly as the walk's page loads do.
        # R7: also once a promotion leaves the view's interval outside the head's
        # declared reference closure (interval 1 reads nothing from interval 0).
        probes = {
            'entries': lambda view: _wire(view._entries(name='big')),
            'entries-range': lambda view: _wire(view._entries(name='big', start=CHUNK, stop=2 * CHUNK)),
            'entries-empty-array': lambda view: _wire(view._entries(name='a000')),
            'entries-absent': lambda view: _wire(view._entries(name='a0005')),
            'entries-outside-root': lambda view: _wire(view._entries(name='0')),
            'info': lambda view: view.info.array('big').value.shape,
            'read-empty': lambda view: view.read('a000', 0, 0, max_owned_bytes=0).value,
        }
        for case in ('candidate-closed', 'candidate-sealed', 'candidate-failed', 'stores-closed',
                     'promoted-out-of-closure'):
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                ref = self.mixed()
                if case in ('stores-closed', 'promoted-out-of-closure'):
                    self.promote(ref)
                    views = self.open(ref, self.stores), _walk_only(self.open(ref, self.stores))
                    if case == 'stores-closed':
                        self.stores.close()
                    else:
                        self.candidate = self.stores.begin_interval(self.stores.head,
                            producer_identity='b' * 64, runtime_identity='d' * 64)
                        self.promote(self.publish([fixture.GeneratedSource(self.scope, 7, name='z', changed_last=True)],
                                                  name='second'))
                        self.assertEqual(self.stores.head.interval, 1)
                        self.assertNotIn(ref.root_key.interval, [i for i, _ in self.stores.head.references])
                else:
                    views = self.open(ref), _walk_only(self.open(ref))
                    if case == 'candidate-closed':
                        self.candidate.close()
                    elif case == 'candidate-sealed':
                        self.candidate.seal(ref)
                    else:
                        self.candidate._failed = True   # as _writing/_serial leave it after a failed call
                self.assertIsNotNone(views[0]._directory)
                for label, probe in probes.items():
                    got, expected = (_outcome(lambda v=view, p=probe: p(v)) for view in views)
                    self.assertEqual(got, expected, (case, label))
                    if label != 'entries-outside-root':
                        self.assertEqual(got[0], 'refused', (case, label))

    def test_index_pages_outside_the_root_interval_build_no_directory(self):
        # B17 refuter R7 note: directory lookups check only the root page's interval against
        # the head's reference closure, which covers every page only while all pages share
        # the root's interval (as _IndexBuilder writes them). A hand-built index whose root
        # page (interval 1) names pages written in interval 0 must build no directory, so its
        # named lookups walk and meet each page's own check; the answers stay the walk's.
        original = self.mixed()
        self.promote(original)
        self.candidate = self.stores.begin_interval(self.stores.head,
            producer_identity='b' * 64, runtime_identity='d' * 64)
        with self.candidate.resolve_manifest(original.array_bindings.root_key) as owned:
            root_page = json.loads(owned.value)['metadata']
        self.assertEqual(root_page['kind'], 'branch')
        tree = S._IndexBuilder(self.candidate, self.scope, None)._page(root_page['entries'], False)
        self.assertEqual(S.SnapshotLocator.from_wire(tree['locator']).interval, 1)
        identity = S.LogicalIdentity('fixture.record.v1', sha256(b'mixed-intervals').hexdigest(), 99)
        preimage = dict(identity=identity.to_wire(), producer='b' * 64,
                        representation_profile='fixture.columns.v1')
        locator = S.SnapshotLocator(self.candidate.workflow_id, 1, S.h(S.ROOT_SCHEMA, preimage))
        count = original.array_bindings.count
        ref = S.SegmentRef(S.SEGMENT_REF_SCHEMA, locator, identity, original.logical_bytes,
            S.BindingIndexRef(S.BINDING_INDEX_SCHEMA, S.SnapshotLocator.from_wire(tree['locator']),
                              tree['digest'], count),
            S.h('atlas.segment-content.v1', dict(identity=identity.to_wire(), array_count=count,
                logical_bytes=original.logical_bytes, tree_digest=tree['tree_digest'])))
        self.candidate.put_manifest(locator.snapshot_key, dict(schema=S.ROOT_SCHEMA, **preimage,
            metadata={}, reference=ref.to_wire(), index=tree))
        view = self.open(ref)
        self.assertIsNone(view._directory)
        self.assertTrue(view._page_outside_root_interval)
        compared = 0
        for query in self.queries(view):
            self.assertEqual(_wire(view._entries(**query)), _wire(self.walk(view, **query)), query)
            compared += 1
        self.assertGreater(compared, 400)
        purposes = self.scope.stats().purpose_bytes
        self.assertEqual(purposes.get('retained:segment-binding-directory-build', 0), 0)
        # The record as published (every page in its root's interval) keeps its directory.
        control = self.open(original)
        self.assertIsNotNone(control._directory)
        self.assertFalse(control._page_outside_root_interval)

    def test_tampered_index_refuses_open_and_releases_the_build_booking(self):
        ref = self.publish([fixture.GeneratedSource(self.scope, CHUNK * 17)])
        original = self.candidate.resolve_manifest

        def tampered(locator, **kwargs):
            owned = original(locator, **kwargs)
            raw = json.loads(owned.value)
            page = raw['metadata']
            if page.get('schema') == S.PAGE_SCHEMA and page['kind'] == 'leaves':
                page['entries'][-1]['content']['count'] = 1
                altered = S.canonical(raw)
                owned.close()
                return self.scope.reserve(fixture.ChargeSpec('tamper-fixture', len(altered))).commit(altered)
            return owned
        with patch.object(self.candidate, 'resolve_manifest', side_effect=tampered), \
                self.assertRaises(ContractError):
            self.backend.open(self.candidate, ref, scope=self.scope)
        gc.collect()
        purposes = self.scope.stats().purpose_bytes
        self.assertEqual(purposes.get('retained:segment-binding-directory-build', 0), 0)
        self.assertEqual(purposes.get('retained:segment-binding-directory', 0), 0)

    def test_worst_case_constants_cover_worst_case_objects(self):
        # Worst-case leaf rows (uint64-max ints, 64-char digests) and arrays: 256-byte
        # UTF-8 names that CPython stores as UCS-4 (one astral character, then ASCII:
        # 253 four-byte characters; b17 refuter F4) and 16 uint64-max dimensions. Both
        # the empty-array shape (one leaf per array) and the many-leaf shape. Collected
        # in lists, then frozen, as _validate does. Counted with the module's own
        # allocator accounting (_held) over every distinct object alive at the freeze;
        # tracemalloc's requested bytes are only a lower bound.
        for leaves, arrays in ((2000, 2000), (2000, 40)):
            collected = {}
            for a in range(arrays):
                name = '\U0001d538' + f'{a:05d}' + 'a' * 247
                self.assertEqual(len(name.encode('utf-8')), 256)
                dims = tuple(S.UINT64_MAX - i - a for i in range(16))
                current = collected[name] = (S.UINT64_MAX - a, '<f8', dims, [], [])
                for i in range(leaves // arrays):
                    start = S.UINT64_MAX - 3 * i - a
                    current[3].append(start)
                    current[4].append((S.UINT64_MAX - 2 * i - a, start, 65535 - i, f'{i * 977 + a:064x}',
                                       S.UINT64_MAX - i))
            frozen = {name: (v[0], v[1], v[2], tuple(v[3]), tuple(v[4])) for name, v in collected.items()}
            peak, retained = _held_total(collected, frozen), _held_total(frozen)
            del collected
            worst = S.DIRECTORY_FIXED_BYTES + leaves * S.DIRECTORY_LEAF_BYTES + arrays * S.DIRECTORY_ARRAY_BYTES
            self.assertGreaterEqual(worst, peak, (leaves, arrays, worst, peak))
            self.assertGreaterEqual(S._directory_bytes(frozen), retained, (leaves, arrays, retained))
            MEASURED[f'worst_case_{leaves}x{arrays}'] = {'bound': worst, 'peak_held': peak, 'retained_held': retained,
                                                         'committed': S._directory_bytes(frozen)}


def _held_total(*directories):
    """_held bytes of every distinct object reachable from collected/frozen directories."""
    seen = {}

    def add(obj):
        seen.setdefault(id(obj), S._held(obj))
    for directory in directories:
        add(directory)
        for name, array in directory.items():
            for obj in (name, array, *array[:3], *array[2], array[3], array[4], *array[3]):
                add(obj)
            for row in array[4]:
                add(row)
                for item in row:
                    add(item)
    return sum(seen.values())


MEASURED = {}


def tearDownModule():
    if MEASURED:
        print('B17 measured:', json.dumps(MEASURED, sort_keys=True))


if __name__ == '__main__':
    unittest.main()
