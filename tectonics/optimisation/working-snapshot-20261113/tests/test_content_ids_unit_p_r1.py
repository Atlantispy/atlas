"""Unit P (issue 96, content identifiers), T-2 for the private heat issuer: the heat call and heat result identifiers
leave out code identity through the table beside RESULT_EFFORT, keep the run mode, and move with physical input.
The issuer's re-maker and the call alias re-make give the snapshot's own identifier.
  python -B -I test_content_ids_unit_p_r1.py <package parent folder>"""
import sys
import unittest
from unittest import mock

import numpy as np

if __name__ == '__main__':
    sys.path.insert(0, sys.argv.pop(1))
from atlas_tectonics import regional_execution as RE  # noqa: E402
from atlas_tectonics.resources import WorkBudget  # noqa: E402

CALL, HEAT = 'atlas.private.composed-owner-call.r1', 'atlas.private.composed-heat-advance.r12'
A, B = 'a'*64, 'b'*64
ARRAYS = {'temperature': np.arange(6, dtype=np.float64).reshape(2, 3)}


def call_meta(code, mode='strict', plan='1'*64):
    return dict(schema=CALL, owner_id='2'*64, plan_id=plan, geometry_id='3'*64,
                execution={'execution_identity': code, 'execution_mode': mode},
                private_sources={'kernel': code, 'helpers': code},
                loaded_dependencies=dict(schema='atlas.private.loaded-dependencies.r1', identity=code,
                                         source_and_loaded_semantics_bound=True,
                                         source_matches_loaded_not_asserted=True),
                context=None, fixture_only=True)


def heat_meta(code, mode='strict', duration=10):
    call = call_meta(code, mode)
    return dict(schema=HEAT, plan_id=call['plan_id'], state_id='4'*64, duration_s=duration,
                call_id=RE.RegionalMechanicalSnapshot(call, ARRAYS).result_id, caller_snapshot=call,
                loaded_dependencies=call['loaded_dependencies'])


def rid(meta):
    return RE.RegionalMechanicalSnapshot(meta, ARRAYS).result_id


class HeatIdentifierTests(unittest.TestCase):
    def test_code_identity_leaves_both_identifiers(self):
        self.assertEqual(rid(call_meta(A)), rid(call_meta(B)))
        self.assertEqual(rid(heat_meta(A)), rid(heat_meta(B)))

    def test_run_mode_and_physical_input_stay(self):
        self.assertNotEqual(rid(call_meta(A)), rid(call_meta(A, mode='release')))
        self.assertNotEqual(rid(call_meta(A)), rid(call_meta(A, plan='5'*64)))
        self.assertNotEqual(rid(heat_meta(A)), rid(heat_meta(A, mode='release')))
        self.assertNotEqual(rid(heat_meta(A)), rid(heat_meta(A, duration=20.)))

    def test_without_a_table_row_code_moves_them(self):
        for schema, make in ((CALL, call_meta), (HEAT, heat_meta)):
            with self.subTest(schema=schema), mock.patch.dict(RE.CONTENT_DROPPED):
                del RE.CONTENT_DROPPED[schema]
                self.assertNotEqual(rid(make(A)), rid(make(B)))

    def test_stored_metadata_keeps_every_field(self):
        meta = call_meta(A)
        self.assertEqual(RE.RegionalMechanicalSnapshot(meta, ARRAYS).descriptor(), meta)

    def test_streamed_feed_equals_content_metadata(self):
        import hashlib
        from atlas_tectonics._private.content_cache import create_retained_scope
        from atlas_tectonics._private.record_tables import RecordCodec
        from atlas_tectonics._private.record_views import feed_result_metadata
        from atlas_tectonics._validation import TectonicsError
        scope = create_retained_scope(WorkBudget(256*1024**2), process_epoch='content-ids-t2')
        def streamed(meta):
            record = RecordCodec().pack_record(meta, record_schema='atlas.private.heat-ledger.logical.v1',
                                               scope=scope, check=lambda: None)
            digest = hashlib.sha256()
            feed_result_metadata((digest,), record)
            return digest.hexdigest()
        for meta in (call_meta(A), call_meta(B, mode='release'), heat_meta(A), heat_meta(B, duration=20)):
            with self.subTest(schema=meta['schema']):
                self.assertEqual(streamed(meta), hashlib.sha256(RE._json(RE.content_metadata(meta))).hexdigest())
        self.assertEqual(streamed(heat_meta(A)), streamed(heat_meta(B)))
        for bad in ('short', 7, ['a'*64]):
            with self.subTest(bad=bad), self.assertRaises(TectonicsError):
                streamed(dict(call_meta(A), context_id=bad))

    def test_issuer_and_call_alias_re_make_the_snapshot_identifier(self):
        from atlas_tectonics._private import heat_cold_patch as HC
        from atlas_tectonics._private import private_heat_native_issuer_r13 as I
        for meta in (call_meta(A), call_meta(B, mode='release')):
            snapshot = RE.RegionalMechanicalSnapshot(meta, ARRAYS)
            with self.subTest(code=meta['execution']['execution_identity']):
                self.assertEqual(I._legacy_snapshot_identity(snapshot, WorkBudget(64*1024**2)), snapshot.result_id)
                self.assertEqual(HC.call_identity(meta, ARRAYS, I.RESOURCES, None), snapshot.result_id)


if __name__ == '__main__':
    unittest.main()
