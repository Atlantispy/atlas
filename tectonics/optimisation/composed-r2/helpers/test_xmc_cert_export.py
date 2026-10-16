"""x-mesh-cert (M17): export_record proves and decodes ONE stream of the exact bytes.

Before: open_records streamed each child for its identity, then export decoded
the compact DAG node by node through paid references. Now the child is streamed
once into a paid buffer, its length and SHA-256 compared with the authenticated
descriptor, and json.loads decodes exactly those bytes. Values (including dict
key order) must equal the structural export of the base module
(xmref_spatial_records_patch, byte copy of origin f5bd50cc...), on v1 bundle and
v2 recipe descriptors; forged descriptors and changed bodies must refuse; the
decode bound must cover the traced decode. tracemalloc measures memory only.
"""
import gc
import json
import random
import sys
import tempfile
import tracemalloc
import unittest
from copy import deepcopy
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
sys.path[:0] = [str(HERE.parent), str(HERE.parents[1]/'runtime-integration-r1/runtime-src')]

import record_views as RV
import spatial_record_recipes as RECIPES
import spatial_records_patch as P
import xmref_spatial_records_patch as BASE
from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
from record_tables import canonical
from test_spatial_record_recipes import RecipeFixture

PRODUCER = {'execution_identity': 'b'*64, 'role': 'x-mesh-cert export fixture'}


def ordered(value):
    """Exact Python value including dict key order (json.dumps without sorting)."""
    return json.dumps(value, ensure_ascii=False)


def certification_like(objects, seed=7):
    rng = random.Random(seed)
    rows = {}
    for o in range(objects):
        rows[f'row{o:04d}'] = {
            'a': [[hex(rng.getrandbits(48)), hex(rng.getrandbits(44) | 1)] for _ in range(12)],
            'n': [rng.getrandbits(14) for _ in range(9)], 'm': [[rng.getrandbits(10)] for _ in range(6)],
            'k': f'label-{o}', 'f': False, 'z': None, 'x': -0.0 if o % 2 else 1e-300, 'e': {}, 'l': []}
    return {'force': {'schema': 'synthetic.force', 'rows': rows, 'time_s': 0.0},
            'solution': {'solution_id': 'a'*64, 'text': 'réçu   \U0001f642 "q" \\ \x00\x1f\x7f'},
            'proposal': {'big': (1 << 9000)+12345, 'neg': -(1 << 200), 'z': 0}, 'iteration': {},
            'bindings': {'b': [True, None]}}


class ExportOnceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='xmc-cert-', dir=TASK/'_t')
        self.budget = WorkBudget(2 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='xmc-cert-export')
        self.stores = IntervalStoreSet.create_migration(str(Path(self.temp.name)/'catalog.json'),
                                                        workflow_id='1'*64, scope=self.scope)
        self.candidate = self.stores.begin_interval(None, producer_identity='2'*64, runtime_identity='3'*64)

    def tearDown(self):
        self.candidate.close(); self.stores.close(); gc.collect(); self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())
        self.temp.cleanup()

    def sealed(self, rows):
        refs = P.publish_records(self.candidate, rows, budget=self.budget, source_producer=PRODUCER)
        self.stores.promote(self.candidate.seal(P.primary_segment(refs)),
                            expected_catalog_digest=self.stores.catalog_digest)
        return refs

    def exported(self, module, refs, kind, store=None):
        with module.export_record(self.stores if store is None else store, refs[kind], kind,
                                  budget=self.budget) as value:
            return ordered(value), value == json.loads(canonical(value))

    def test_v1_values_and_key_order_equal_base_and_original(self):
        rows = {'certification': certification_like(60), 'differential': {'interval': {'a': ['0x1', '0x2']},
                'endpoint_network': {'network_id': 'c'*64}}, 'empty': {}}
        refs = self.sealed(rows)
        for kind, value in rows.items():
            with self.subTest(kind=kind):
                new, _ = self.exported(P, refs, kind)
                old, _ = self.exported(BASE, refs, kind)
                self.assertEqual(new, old)
                self.assertEqual(json.loads(new), json.loads(ordered(value)))
                with P.export_record(self.stores, refs[kind], kind, budget=self.budget) as got:
                    self.assertEqual(canonical(got), canonical(value))

    def test_v2_recipe_values_equal_base(self):
        with patch.object(RECIPES, 'SMALL_IMPORT_BYTES', 16 << 10):
            fixture = RecipeFixture(self.scope, rows=300)
            rows, native, handles = fixture.rows()
            refs = P.publish_records(self.candidate, rows, budget=self.budget, source_producer=PRODUCER)
            for handle in handles:
                handle.close()
            del rows, handles
        self.stores.promote(self.candidate.seal(P.primary_segment(refs)),
                            expected_catalog_digest=self.stores.catalog_digest)
        self.assertTrue(any(RECIPES.is_v2(ref) for ref in refs.values()))
        for kind in sorted(refs):
            with self.subTest(kind=kind, v2=RECIPES.is_v2(refs[kind])):
                new, _ = self.exported(P, refs, kind)
                old, _ = self.exported(BASE, refs, kind)
                self.assertEqual(new, old)
                self.assertEqual(canonical(json.loads(new)), canonical(native[kind]))
        del fixture, native
        gc.collect()

    def test_one_stream_no_structural_decode(self):
        refs = self.sealed({'certification': certification_like(40)})
        original = RV.RecordRef.iter_json
        streams = []
        def counted(ref, *args, **kwargs):
            streams.append(ref.index)
            return original(ref, *args, **kwargs)
        with patch.object(RV.RecordRef, 'iter_json', counted), \
                patch.object(RV, '_export_ref', side_effect=AssertionError('structural export')), \
                patch.object(RV.RecordRef, 'identity', side_effect=AssertionError('second identity stream')):
            self.exported(P, refs, 'certification')
        self.assertEqual(len(streams), 1)

    def _refused(self, call, regex, base_call=None):
        """Refuses with ContractError; whatever a refusal leaves held (sealed
        reads keep retained metadata caches) is exactly what the base
        module's refusal of the same input leaves."""
        def held():
            gc.collect()
            return self.budget.statistics()['categories']
        def growth(attempt):
            with self.assertRaisesRegex(ContractError, regex):
                attempt()
            before = held()
            with self.assertRaisesRegex(ContractError, regex):
                attempt()
            after = held()
            return {k: after.get(k, 0)-before.get(k, 0) for k in set(before) | set(after)
                    if after.get(k, 0) != before.get(k, 0)}
        new = growth(call)
        if base_call is not None:
            self.assertEqual(new, growth(base_call))
        else:
            self.assertEqual(new, {})

    def test_forged_descriptor_and_changed_body_refuse(self):
        records = certification_like(20)
        refs = self.sealed({'certification': records})
        def export(module, ref):
            with module.export_record(self.stores, ref, 'certification', budget=self.budget):
                self.fail('forged record exported')
        # A descriptor forged consistently with a forged bundle index: only
        # the logical stream can refuse it (as open_records' proof did).
        for field, forged in (('sha256', 'a'*64), ('bytes', refs['certification']['bytes']+1),
                              ('bytes', refs['certification']['bytes']-1)):
            bad = deepcopy(refs)
            bad['certification'][field] = forged
            def forging(module, bad=bad):
                original = module._bundle_metadata
                def forged_index(segment, selected, source_producer=None):
                    metadata = deepcopy(original(segment, refs))
                    metadata['records']['certification'] = {k: bad['certification'][k] for k in ('bytes', 'sha256')}
                    return metadata
                def attempt():
                    with patch.object(module, '_bundle_metadata', side_effect=forged_index):
                        export(module, bad['certification'])
                return attempt
            with self.subTest(field=field, value=forged):
                self._refused(forging(P), 'logical identity differs', forging(BASE))
        # Unforged descriptor, changed compact body below the identity.
        parts = RV.CompactRecord._parts
        def changed(record, node, depth=0, memo=None):
            for part in parts(record, node, depth, memo):
                yield part.replace(b'label-1', b'label-9', 1) if type(part) is bytes else part
        with patch.object(RV.CompactRecord, '_parts', changed):
            self._refused(lambda: export(P, refs['certification']), 'differs',
                          lambda: export(BASE, refs['certification']))
        # Index-only forgery is still refused by the authenticated index check.
        bad = deepcopy(refs)
        bad['certification']['sha256'] = 'b'*64
        self._refused(lambda: export(P, bad['certification']), 'authenticated bundle index',
                      lambda: export(BASE, bad['certification']))

    def test_bounds_and_fallback_keep_base_outcomes(self):
        refs = self.sealed({'certification': certification_like(30)})
        with patch.object(P, 'EXPORT_LOGICAL_BYTES', 1024), patch.object(BASE, 'EXPORT_LOGICAL_BYTES', 1024):
            self._refused(lambda: self.exported(P, refs, 'certification'), 'logical export bound',
                          lambda: self.exported(BASE, refs, 'certification'))
        # Owned bound below the fast decode charge: the structural export runs
        # with its own admission, exactly as before (same value or same failure,
        # including record_views' own failure type under a tight bound).
        size = refs['certification']['bytes']
        for owned in (8*size, 20*size, 60*size):
            outcomes = []
            for module in (P, BASE):
                with patch.object(module, 'EXPORT_OWNED_BYTES', owned):
                    try:
                        outcomes.append(self.exported(module, refs, 'certification')[0])
                    except (ContractError, RuntimeError) as error:
                        outcomes.append(f'failed: {type(error).__name__}: {error}')
                gc.collect()
            with self.subTest(owned=owned):
                self.assertEqual(outcomes[0], outcomes[1])

    def test_export_booking_covers_traced_peak(self):
        refs = self.sealed({'certification': certification_like(200)})
        gc.collect()
        base_booked = self.budget.reserved_bytes
        self.budget._peak = self.budget._used
        tracemalloc.start()
        base = tracemalloc.get_traced_memory()[0]
        try:
            with P.export_record(self.stores, refs['certification'], 'certification', budget=self.budget) as value:
                held = tracemalloc.get_traced_memory()[0]-base
            real = tracemalloc.get_traced_memory()[1]-base
        finally:
            tracemalloc.stop()
        del value
        booked = self.budget.peak_reserved_bytes-base_booked
        self.assertLessEqual(real, booked)
        self.assertGreater(held, 0)


class DecodeChargeTests(unittest.TestCase):
    SHAPES: ClassVar[dict] = {
        'certification': certification_like(50),
        'empty-objects': [{} for _ in range(20000)],
        'empty-lists': [[] for _ in range(20000)],
        'nested-lists': [[[[[]]]] for _ in range(5000)],
        'small-ints': list(range(300, 40000)),
        'big-ints': [(1 << 4000)+i for i in range(200)],
        'floats': [i/7 for i in range(20000)],
        'literals': [None, True, False]*10000,
        'short-strings': [f'x{i}' for i in range(20000)],
        'one-char-strings': ['a']*30000,
        'long-string': 'y'*(1 << 20),
        'escapes': ['\x00\n"\\'*50]*200,
        'latin1': ['é'*100]*500,
        'emoji-widens': ['a'*1000+'\U0001f642']*100,
        'wide-dict': {f'k{i:06d}': i for i in range(20000)},
        'distinct-keys': [{f'key{i}': None} for i in range(10000)],
        'many-small-dicts': [{'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5, 'f': 6} for _ in range(5000)],
        'deep': json.loads('['*120+']'*120),
        'rationals': [[hex(random.Random(i).getrandbits(800)), '0x1'] for i in range(3000)],
    }

    def test_bound_covers_traced_buffers_and_objects(self):
        for name, value in self.SHAPES.items():
            raw = bytearray(canonical(value))
            gc.collect()
            tracemalloc.start()
            base = tracemalloc.get_traced_memory()[0]
            try:
                decoded = json.loads(raw)
                _current, peak = (v-base for v in tracemalloc.get_traced_memory())
            finally:
                tracemalloc.stop()
            self.assertEqual(canonical(decoded), bytes(raw))
            charge = P._decode_charge(raw)
            with self.subTest(shape=name, real=peak+len(raw), charge=charge):
                self.assertLessEqual(peak+len(raw), charge)
            del decoded


if __name__ == '__main__':
    unittest.main()
