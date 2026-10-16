"""W3 Decision 3: validate_exchange streams a large compact transport once.

exchange_identity feeds the transport's canonical bytes into the exchange
digest and the RegionalMechanicalSnapshot digest in one pass; snapshot()
uses that digest only when the arrays head built from the native snapshot's
own fields equals the head hashed in front of it. Proof:
- identities equal the legacy dictionary identities and the unchanged
  single-digest route (base module w3ref_spatial_validation_patch) on
  census-shaped IV1 records (root, LogicalExchange, overlay), on exotic keys
  sorting around result_id, and with changed/foreign arrays (fallback);
- the full transformed validate_exchange reaches the legacy decision with
  the teed snapshot actually used;
- memory: traced peak of identity+snapshot is not above the base route's.
"""
import gc
import sys
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_wp6_streamed_validation as W  # runtime path, census fixture, routes

# isort: split
import record_tables as T
import spatial_validation_patch as V
import w3ref_spatial_validation_patch as BASE
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.resources import WorkBudget
from content_cache import create_retained_scope
from record_views import LogicalExchange
from test_spatial_validation_patch import digest


def transport_arrays(arrays):
    return {k.removeprefix('spatial-transport:'): v for k, v in arrays.items() if k.startswith('spatial-transport:')}


class StreamOnceTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(8 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='w3-stream-once')

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def pack(self, exchange):
        with W.lifted_builder():  # fixture packing only, as in test_wp6_streamed_validation
            return T.RecordCodec().pack_record(exchange, record_schema='a2.exchange.v1', scope=self.scope,
                                               check=lambda: None)

    def identities(self, module, ref, state_id, arrays, *, tee):
        """(exchange identity, snapshot identity, teed?) through `module`'s accessors."""
        with module.access(ref) as value:
            lazy = value['transport']
            self.assertIsInstance(lazy, module._Lazy)
            ident = (module.exchange_identity(value, state_id, digest, arrays) if tee
                     else module.exchange_identity(value, state_id, digest))
            teed = getattr(lazy, '_tee', None) is not None
            snap = module.snapshot(lazy, transport_arrays(arrays), RegionalMechanicalSnapshot).result_id
            self.assertIsNone(getattr(lazy, '_tee', None))  # consumed once
            del lazy, value
        return ident, snap, teed

    def check_all(self, label, exchange, state, arrays, refs, *, expect_tee=True, legacy_snapshot=None,
                  plain=True):
        legacy_ident = exchange['result_id']
        legacy_snap = legacy_snapshot or exchange['global_transport_id']
        for kind, ref in refs:
            with self.subTest(label=label, kind=kind):
                new = self.identities(V, ref, state.state_id, arrays, tee=True)
                base = self.identities(BASE, ref, state.state_id, arrays, tee=False)
                self.assertEqual(new[:2], (legacy_ident, legacy_snap))
                self.assertEqual(base[:2], new[:2])
                self.assertEqual(new[2], expect_tee)
                if plain:  # the new module without arrays: the unchanged single-digest route
                    untouched = self.identities(V, ref, state.state_id, arrays, tee=False)
                    self.assertEqual(untouched[:2], new[:2])
                    self.assertFalse(untouched[2])
            gc.collect()

    def refs(self, record, overlay=True):
        root = record.root()
        logical = LogicalExchange(record, root.index)

        if not overlay:
            return [('root', root), ('LogicalExchange', logical)]
        return [('root', root), ('LogicalExchange', logical), ('overlay', root.without(('nothing-removed',)))]

    def close(self, refs, record):
        for _, ref in reversed(refs):  # the overlay borrows the root
            ref.close()
        record.close()

    def test_census_iv1_identities_equal_legacy_and_base(self):
        _owner, state, exchange, arrays, _saved, _fake = W.census_exchange(1.0, self.budget)
        self.assertGreater(len(T.canonical(exchange['transport'])), 6_000_000)
        record = self.pack(exchange)
        refs = self.refs(record, overlay=False)
        self.check_all('iv1', exchange, state, arrays, refs, plain=False)
        self.close(refs, record)

    def test_exotic_keys_and_array_variants(self):
        _owner, state, exchange, arrays, _saved, _fake = W.census_exchange(0.1, self.budget)
        transport = exchange['transport']
        # Keys sorting immediately before/after result_id, escapes and a non-BMP key.
        for key in ('result_ic', 'result_id0', 'resultid', 'résult"\\', '\U0001F600', '\x01'):
            transport[key] = [['0x1', '0x3'], 'text ']
        transport['result_id'] = RegionalMechanicalSnapshot(
            {k: v for k, v in transport.items() if k != 'result_id'}, transport_arrays(arrays)).result_id
        exchange['global_transport_id'] = transport['result_id']
        exchange['joined_heat']['state_id'] = transport['result_id']
        W.seal(exchange, state)
        self.assertEqual(exchange['result_id'], digest({'state_id': state.state_id, 'exchange': {
            k: v for k, v in exchange.items() if k not in ('state_id', 'result_id')}}))
        record = self.pack(exchange)
        refs = self.refs(record)
        self.check_all('exotic-keys', exchange, state, arrays, refs[:1])
        self.check_all('exotic-keys', exchange, state, arrays, refs[1:], plain=False)
        meta = {k: v for k, v in transport.items() if k != 'result_id'}
        variants = {
            # Different values: the teed head still describes the given arrays.
            'other-values': (dict(arrays, **{'spatial-transport:stock': np.array([5., -0.])}), True),
            'two-d': (dict(arrays, **{'spatial-transport:stock': np.arange(6.).reshape(2, 3)}), True),
            'zero-size': (dict(arrays, **{'spatial-transport:stock': np.zeros((3, 0))}), True),
            'extra-field': (dict(arrays, **{'spatial-transport:zz': np.ones(3)}), True),
            # Not plain binary64: no tee; the unchanged stream decides.
            'int-array': (dict(arrays, **{'spatial-transport:stock': np.arange(2)}), False),
            'strided': (dict(arrays, **{'spatial-transport:stock': np.arange(4.)[::2]}), False),
            'not-dict': (None, False),
        }
        for label, (variant, tee) in variants.items():
            if variant is None:
                for kind, ref in refs[:1]:
                    with self.subTest(label=label, kind=kind), V.access(ref) as value:
                        value['transport']
                        self.assertEqual(V.exchange_identity(value, state.state_id, digest, None), exchange['result_id'])
                        self.assertIsNone(value['transport']._tee)
                continue
            try:
                expected = RegionalMechanicalSnapshot(meta, transport_arrays(variant)).result_id
            except Exception as error:  # noqa: BLE001  (any native refusal type; asserted identical on every route)
                for kind, ref in refs[:1]:
                    for module, teeing in ((V, True), (BASE, False)):
                        with self.subTest(label=label, kind=kind, module=module.__name__), \
                                self.assertRaises(type(error)) as caught:
                            self.identities(module, ref, state.state_id, variant, tee=teeing)
                        self.assertEqual(str(caught.exception), str(error))
                continue
            self.check_all(label, exchange, state, variant, refs[:1], expect_tee=tee, legacy_snapshot=expected, plain=False)
        self.close(refs, record)

    def test_validate_exchange_uses_tee_and_keeps_decisions(self):
        routes = W.Routes()
        legacy = W.census_exchange(1.0, self.budget)
        owner, state, exchange, arrays, _saved, fake = legacy
        record = self.pack(exchange)
        root = record.root()
        used = []
        original = V.snapshot

        def spy(metadata, arrays_, native):
            used.append(getattr(metadata, '_tee', None) is not None)
            return original(metadata, arrays_, native)
        expected = routes.run(False, owner, state, exchange, arrays, fake)
        self.assertEqual(expected, ('accepted', None))
        with patch.object(V, 'snapshot', spy):
            self.assertEqual(routes.run(True, owner, state, root, arrays, fake), expected)
            self.assertEqual(used, [True])
            # Changed transport array bytes: refusal identical to legacy (the
            # teed head describes the given arrays; the identity then differs).
            changed = dict(arrays, **{'spatial-transport:stock': np.array([1., 2.5])})
            self.assertEqual(routes.run(True, owner, state, root, changed, fake),
                             routes.run(False, owner, state, exchange, changed, fake))
            # A float32 array: no tee, native refusal or decision unchanged.
            single = dict(arrays, **{'spatial-transport:stock': np.array([1., 2.], dtype=np.float32)})
            self.assertEqual(routes.run(True, owner, state, root, single, fake),
                             routes.run(False, owner, state, exchange, single, fake))
        root.close()
        record.close()

    def test_traced_peak_not_above_base(self):
        _owner, state, exchange, arrays, _saved, _fake = W.census_exchange(0.25, self.budget)
        record = self.pack(exchange)
        root = record.root()
        peaks = {}
        for label, module, tee in (('base', BASE, False), ('new', V, True), ('base2', BASE, False)):
            gc.collect()
            tracemalloc.start()
            try:
                self.identities(module, root, state.state_id, arrays, tee=tee)
                peaks[label] = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
        print('W3 stream-once traced peaks', peaks, flush=True)
        self.assertLessEqual(peaks['new'], max(peaks['base'], peaks['base2'])+(64 << 10))
        root.close()
        record.close()


if __name__ == '__main__':
    unittest.main()
