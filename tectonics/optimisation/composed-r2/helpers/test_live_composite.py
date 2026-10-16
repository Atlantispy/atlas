"""Step 8 composite issuance: exact bytes, no re-import, paid lifetimes."""
import gc
import json
import sys
import unittest
from concurrent.futures import CancelledError
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parent
I = R.parent/'runtime-integration-r1'/'runtime-src'
for directory in (I, R):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import live_composite as LC
import record_tables as T
from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from content_cache import create_retained_scope
from record_views import RecordRef


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def stream(value):
    output = []
    with value.iter_json() as blocks:
        for block in blocks:
            with block:
                output.append(block.value)
    return b''.join(output)


def lender_value(rows=40):
    """Every lexical class the codec distinguishes, including non-ASCII keys."""
    receipts = [{'cell_id': sha256(str(i).encode()).hexdigest(), 'label': 'é€'+str(i),
                 'exact': ['-0x1f', '0x3'], 'volume': 1.0/(i+1), 'count': i-7, 'flag': i % 2 == 0,
                 'empty': None, 'nested': {'ß': [i, 'x'*i]}}
                for i in range(rows)]
    return {'schema': 'lender', 'physical_measure_receipts': {r['cell_id']: r for r in receipts},
            'face_intervals': [{'face': i, 'bounds': ['0x1', '0x2']} for i in range(rows)],
            'cells': receipts[:5], 'big': '0x'+'f'*600, 'tokens': ['t'*n for n in range(30)]}


class _Closed:
    def close(self):
        pass


class CompositeTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='step8-live-composite-test')
        self.initial = self.budget.reserved_bytes
        self.native = lender_value()
        self.lender = T.RecordCodec().pack_record(self.native, record_schema='atlas.test-lender.v1',
                                                  scope=self.scope, check=lambda: None)
        self.root = self.lender.root()

    def tearDown(self):
        self.root.close()
        self.lender.close()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def borrowed(self, *names):
        return {name: self.root.field(name) for name in names}

    def compose(self, value, check=lambda: None):
        return LC.compose_record(value, record_schema='atlas.test-composite.v1',
                                 scope=self.scope, check=check)

    def test_native_value_returns_none(self):
        self.assertIsNone(self.compose({'a': 1, 'b': [1, 2]}))
        self.assertIsNone(self.compose([1, 2]))

    def test_disabled_route_sends_every_value_to_the_import_pack(self):
        refs = self.borrowed('cells')
        LC.ENABLED = False
        try:
            self.assertIsNone(self.compose({**refs, 'schema': 'x'}))
        finally:
            LC.ENABLED = True
        live = self.compose({**refs, 'schema': 'x'})
        self.assertIsInstance(live, LC.LiveRecord)
        live.close()
        refs['cells'].close()

    def test_exact_bytes_identity_and_no_reimport(self):
        refs = self.borrowed('physical_measure_receipts', 'face_intervals', 'big')
        value = {**refs, 'schema': 'graph', 'cells': [{'cell_id': 'a'*64, 'end': ['0x5', '0x7']}],
                 'selection': 'exact – deterministic', 'bounds_id': 'b'*64}
        expected = {**value, **{k: self.native[k] for k in refs}}
        live = self.compose(value)
        self.assertIsInstance(live, LC.LiveRecord)
        raw = canonical(expected)
        self.assertEqual(live.identity().sha256, sha256(raw).hexdigest())
        self.assertEqual(live.identity().canonical_bytes, len(raw))
        self.assertEqual(live.identity().record_schema, 'atlas.test-composite.v1')
        self.assertEqual(stream(live), raw)
        # Old route: the same value packed by import gives the same identity.
        packed = T.RecordCodec().pack_record(value, record_schema='atlas.test-composite.v1',
                                             scope=self.scope, check=lambda: None)
        self.assertEqual(packed.identity(), live.identity())
        with packed.root() as whole:
            imported_nodes = whole._view._n('node.kind')
        packed.close()
        # The composite's own tables hold only the native skeleton.
        skeleton_nodes = live._ref._view._n('node.kind')
        self.assertLess(skeleton_nodes, imported_nodes // 5)
        self.assertEqual(live.imports.count, 0)
        with live.root() as root, root.field('physical_measure_receipts') as receipts:
            self.assertIs(receipts._view, self.lender)
        for ref in refs.values():
            ref.close()
        live.close()

    def test_nested_dicts_compose_and_lists_are_counted_imports(self):
        refs = self.borrowed('cells', 'tokens')
        value = {'schema': 'proposal', 'graph': {'cells': refs['cells'], 'finite_inventory': {'owner': 'x'},
                 'transfers': [{'face': 1}]}, 'stocks': {'a': ['0x1', '0x2']},
                 'listed': [refs['tokens'], 3]}
        expected = {'schema': 'proposal', 'graph': {'cells': self.native['cells'],
                    'finite_inventory': {'owner': 'x'}, 'transfers': [{'face': 1}]},
                    'stocks': {'a': ['0x1', '0x2']}, 'listed': [self.native['tokens'], 3]}
        live = self.compose(value)
        raw = canonical(expected)
        self.assertEqual(stream(live), raw)
        self.assertEqual(live.identity().sha256, sha256(raw).hexdigest())
        self.assertEqual(live.imports.count, 1)
        self.assertEqual(live.imports.logical_bytes, len(canonical(self.native['tokens'])))
        with live.root() as root, root.field('graph') as graph, graph.field('cells') as cells:
            self.assertIs(cells._view, self.lender)
        for ref in refs.values():
            ref.close()
        live.close()

    def test_callers_close_handles_and_composite_releases_without_collection(self):
        gc.disable()
        try:
            refs = self.borrowed('physical_measure_receipts')
            live = self.compose({**refs, 'schema': 'x'})
            # Callers close their own handles exactly as before composition.
            for ref in refs.values():
                ref.close()
            del refs
            self.root.close()
            self.root = _Closed()
            # The lender cannot be closed while the composite borrows it.
            with self.assertRaises(RuntimeError):
                self.lender.close()
            with live.root() as root, root.field('physical_measure_receipts') as child:
                self.assertEqual(child.kind, 'object')
            live.close()
            del live, root, child
            self.lender.close()
            self.lender = _Closed()
            self.assertEqual(self.budget.reserved_bytes, self.initial)
        finally:
            gc.enable()

    def test_composite_children_close_with_borrowed_composite_inputs(self):
        # An input that is itself an overlay (transport/proposal records) is
        # rebuilt over independent borrows, so its caller can also close it.
        refs = self.borrowed('cells', 'big')
        overlay = LC.compose_record({**refs, 'schema': 'inner'}, record_schema='atlas.inner.v1',
                                    scope=self.scope, check=lambda: None)
        for ref in refs.values():
            ref.close()
        handle = overlay.root()
        live = self.compose({'schema': 'outer', 'inner': handle})
        handle.close()
        overlay.close()
        expected = {'schema': 'outer', 'inner': {'schema': 'inner', 'cells': self.native['cells'],
                                                 'big': self.native['big']}}
        self.assertEqual(stream(live), canonical(expected))
        live.close()

    def test_cancellation_in_pack_and_identity_keeps_traceback_funding(self):
        refs = self.borrowed('physical_measure_receipts', 'face_intervals')
        value = {**refs, 'schema': 'x', 'native': [{'a': i} for i in range(50)]}
        calls = 0
        def counting():
            nonlocal calls
            calls += 1
        dry = self.compose(value, check=counting)
        dry.close()
        total = calls
        initial = self.budget.reserved_bytes
        # Early: inside the skeleton pack. Late: inside the identity stream.
        for stop in (3, total-1):
            calls, caught = 0, []
            def check(stop=stop):
                nonlocal calls
                calls += 1
                if calls == stop:
                    raise CancelledError('composite cancelled at '+str(stop))
            try:
                self.compose(value, check=check)
            except CancelledError as error:
                caught.append(error)
            self.assertEqual(len(caught), 1, stop)
            self.assertGreater(self.budget.reserved_bytes, initial, stop)
            caught.clear()
            gc.collect()
            self.assertEqual(self.budget.reserved_bytes, initial, stop)
        for ref in refs.values():
            ref.close()

    def test_foreign_scope_and_bad_inputs_refuse(self):
        other_budget = WorkBudget(1 << 26)
        other = create_retained_scope(other_budget, process_epoch='foreign')
        foreign = T.RecordCodec().pack_record({'a': [1]}, record_schema='atlas.test.v1',
                                              scope=other, check=lambda: None)
        with foreign.root() as root, root.field('a') as child, self.assertRaises(ContractError):
            self.compose({'x': child})
        foreign.close()
        other.close()
        with self.assertRaises(ContractError):
            LC.compose_record({'a': 1}, record_schema='', scope=self.scope, check=lambda: None)
        refs = self.borrowed('cells')
        with self.assertRaises(ContractError):
            self.compose({1: refs['cells']})
        refs['cells'].close()

    def test_record_ref_api_on_composite(self):
        refs = self.borrowed('face_intervals', 'cells')
        live = self.compose({**refs, 'schema': 'graph', 'small': {'k': 'v'}})
        with live.root() as root:
            self.assertIsInstance(root, RecordRef)
            self.assertEqual(root.kind, 'object')
            self.assertEqual(root.size, 4)
            with root.keys() as keys:
                self.assertEqual(keys.value, ('cells', 'face_intervals', 'schema', 'small'))
            with root.field('small') as small, small.export(max_logical_bytes=4096,
                                                             max_owned_bytes=1 << 20) as held:
                self.assertEqual(held.value, {'k': 'v'})
            with root.select(('schema', 'small')) as selected, selected.export(
                    max_logical_bytes=4096, max_owned_bytes=1 << 20) as held:
                self.assertEqual(held.value, {'schema': 'graph', 'small': {'k': 'v'}})
        for ref in refs.values():
            ref.close()
        live.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
