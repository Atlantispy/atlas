"""E-22 (issue 96, content identifiers): bounds_id and geometry_id are the digest of the record's content form; the
byte identity (holder_identity) still guards the stored bytes. Packed and bytes forms of one record agree.
  python -B -I test_content_ids_e22_r2.py <package parent folder>"""
import copy
import hashlib
import json
import sys
import unittest

if __name__ == '__main__':
    sys.path.insert(0, sys.argv.pop(1))

from atlas_tectonics.integration.coupling import spatial_ale as ALE  # noqa: E402
from atlas_tectonics._private.integration.geometry import live_spatial_patch as LIVE_SPATIAL  # noqa: E402
from atlas_tectonics._private.integration.geometry import spatial_validation_patch as SV  # noqa: E402
from atlas_tectonics.integration.resources import WorkBudget  # noqa: E402

RECORD = {'schema': 'atlas.spatial-ale-bounds.v1', 'cells': [{'cell_id': 'c1', 'volume_m3': 12}, {'cell_id': 'c2', 'volume_m3': 7}],
          'physical_measure_receipts': [{'measure_id': 'a'*64, 'source_sha256': 'b'*64, 'area_m2': 5},
                                        {'measure_id': 'c'*64, 'source_sha256': None, 'area_m2': 9}],
          'parent_state_id': 'd'*64}


def plain(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class E22(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(256*1024**2)

    def bytes_holder(self, cls, record):
        return ALE._legacy_issue(cls, record, self.budget)

    def packed_holder(self, cls, record):
        from atlas_tectonics._private.codecs.content_cache import create_retained_scope
        from atlas_tectonics._private.codecs.record_tables import RecordCodec
        scope = create_retained_scope(self.budget, process_epoch='content-ids-e22')
        packed = RecordCodec().pack_record(record, record_schema='atlas.spatial-working-record.v1', scope=scope,
                                           check=lambda: None)
        holder = object.__new__(cls)  # as live_spatial_patch.issue() does for a packed record
        object.__setattr__(holder, '_json', packed)
        object.__setattr__(holder, '_resource', self.budget)
        return holder

    def test_code_digest_moves_bytes_not_identifier(self):
        moved = copy.deepcopy(RECORD)
        moved['physical_measure_receipts'][0]['source_sha256'] = 'e'*64
        for make in (self.bytes_holder, self.packed_holder):
            for cls, prop in ((ALE.SpatialALEBounds, 'bounds_id'), (ALE.SpatialALEGraph, 'geometry_id')):
                with self.subTest(make=make.__name__, cls=cls.__name__):
                    a, b = make(cls, RECORD), make(cls, moved)
                    self.assertEqual(getattr(a, prop), getattr(b, prop))
                    self.assertNotEqual(LIVE_SPATIAL.holder_identity(a), LIVE_SPATIAL.holder_identity(b))

    def test_number_moves_identifier(self):
        moved = copy.deepcopy(RECORD)
        moved['cells'][1]['volume_m3'] = 8
        for make in (self.bytes_holder, self.packed_holder):
            with self.subTest(make=make.__name__):
                self.assertNotEqual(make(ALE.SpatialALEBounds, RECORD).bounds_id,
                                    make(ALE.SpatialALEBounds, moved).bounds_id)

    def test_packed_and_bytes_agree(self):
        content = {k: v for k, v in RECORD.items() if k != 'physical_measure_receipts'}
        content['physical_measure_receipts'] = [{k: v for k, v in r.items() if k != 'source_sha256'}
                                                for r in RECORD['physical_measure_receipts']]
        expected = plain(content)
        self.assertEqual(self.bytes_holder(ALE.SpatialALEGraph, RECORD).geometry_id, expected)
        self.assertEqual(self.packed_holder(ALE.SpatialALEGraph, RECORD).geometry_id, expected)
        self.assertEqual(LIVE_SPATIAL.graph_content_identity(RECORD, plain), expected)
        self.assertEqual(SV.content_identity(content, plain), expected)

    def test_no_code_field_keeps_byte_identity(self):
        record = {k: v for k, v in RECORD.items() if k != 'physical_measure_receipts'}
        holder = self.bytes_holder(ALE.SpatialALEBounds, record)
        self.assertEqual(holder.bounds_id, LIVE_SPATIAL.holder_identity(holder))
        self.assertEqual(holder.bounds_id, holder.bounds_id)  # cached value read again

    def test_packed_streamed_once_per_bytes(self):
        from unittest import mock
        from atlas_tectonics._private.codecs import record_views as RV
        holder = self.packed_holder(ALE.SpatialALEGraph, dict(RECORD, schema='atlas.e22-once.v1'))
        with holder._json.root() as root, mock.patch.object(RV, 'feed_without', wraps=RV.feed_without) as feed:
            first = SV.content_identity(root, None)
            streamed = feed.call_count  # feed_without recurses: calls of one stream
            self.assertGreater(streamed, 0)
            self.assertEqual(SV.content_identity(root, None), first)
            self.assertEqual(feed.call_count, streamed)


if __name__ == '__main__':
    unittest.main()
