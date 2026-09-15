"""Cache metadata corruption must quarantine/rebuild without leaking type errors."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from ten_m_tile_engine import cache as module


class CacheMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cache-metadata-")
        self.addCleanup(self.temporary.cleanup)
        self.cache = module.ContentAddressedCache(Path(self.temporary.name))
        self.raw = b"recoverable-source"
        self.key = self.cache.put(self.raw)
        self.path = self.cache.object_path(self.key)
        packed = self.path.read_bytes()
        start = len(module.OBJECT_MAGIC) + module.UINT32.size
        end = start + module.UINT32.unpack_from(packed, len(module.OBJECT_MAGIC))[0]
        self.header = json.loads(packed[start:end])
        self.frame = packed[end:]

    def packed(self, header, frame=None):
        metadata = json.dumps(header, separators=(",", ":")).encode()
        return module.OBJECT_MAGIC + module.UINT32.pack(len(metadata)) + metadata + (
            self.frame if frame is None else frame
        )

    def assert_rejects(self, header):
        with self.assertRaises(module.CacheCorruptionError):
            self.cache._unpack_object(self.packed(header), self.key)

    def test_valid_writer_objects_including_empty_roundtrip(self):
        for raw in (b"", self.raw, bytes(range(256)) * 128):
            with self.subTest(length=len(raw)):
                key = self.cache.put(raw)
                self.assertEqual(self.cache.get(key), raw)

    def test_original_nonobject_regression_quarantines_then_rebuilds(self):
        self.path.write_bytes(module.OBJECT_MAGIC + module.UINT32.pack(2) + b"[]")
        self.assertEqual(self.cache.put(self.raw), self.key)
        self.assertEqual(self.cache.get(self.key), self.raw)
        self.assertEqual(len(list(self.cache.quarantine.iterdir())), 1)

    def test_nonobject_json_types_rejected(self):
        for value in (None, [], [1], "text", True, 7, 1.25):
            with self.subTest(value=value):
                self.assert_rejects(value)

    def test_each_required_field_is_required(self):
        for name in self.header:
            with self.subTest(name=name):
                value = dict(self.header)
                del value[name]
                self.assert_rejects(value)

    def test_unknown_field_rejected(self):
        self.assert_rejects(dict(self.header, unsupported_field=1))

    def test_duplicate_field_rejected_even_if_last_value_is_valid(self):
        metadata = json.dumps(self.header, separators=(",", ":"))
        metadata = ('{"raw_size":0,' + metadata[1:]).encode()
        bad = module.OBJECT_MAGIC + module.UINT32.pack(len(metadata)) + metadata + self.frame
        with self.assertRaises(module.CacheCorruptionError):
            self.cache._unpack_object(bad, self.key)

    def test_size_types_and_ranges_rejected_without_coercion(self):
        for name in ("raw_size", "frame_size"):
            for value in (None, False, True, -1, "17", 17.0, [], {}, sys.maxsize + 1):
                with self.subTest(name=name, value=value):
                    self.assert_rejects(dict(self.header, **{name: value}))

    def test_digest_types_and_formats_rejected(self):
        for name in ("content_hash", "frame_sha256"):
            for value in (None, False, [], 64, "", "g" * 64, "A" * 64, "a" * 63):
                with self.subTest(name=name, value=value):
                    self.assert_rejects(dict(self.header, **{name: value}))

    def test_wrong_codec_rejected(self):
        for value in (None, [], 3, "zstd", "gzip"):
            with self.subTest(value=value):
                self.assert_rejects(dict(self.header, codec=value))

    def test_truncated_or_invalid_header_lengths_rejected(self):
        for size in (0, 1, len(self.path.read_bytes()), 2**32 - 1):
            with self.subTest(size=size):
                packed = module.OBJECT_MAGIC + module.UINT32.pack(size) + b"{}" + self.frame
                with self.assertRaises(module.CacheCorruptionError):
                    self.cache._unpack_object(packed, self.key)

    def test_actual_compressed_size_is_checked(self):
        for size in (0, len(self.frame) - 1, len(self.frame) + 1):
            with self.subTest(size=size):
                self.assert_rejects(dict(self.header, frame_size=size))

    def test_false_content_size_rejected_before_decompression(self):
        decompressor = mock.Mock()
        with mock.patch.object(self.cache, "decompressor", decompressor):
            for size in (0, len(self.raw) - 1, len(self.raw) + 1):
                with self.subTest(size=size):
                    self.assert_rejects(dict(self.header, raw_size=size))
        decompressor.decompress.assert_not_called()

    def test_unknown_zstd_content_size_still_roundtrips(self):
        frame = module.zstd.ZstdCompressor(write_content_size=False, write_checksum=True).compress(self.raw)
        header = dict(self.header, frame_size=len(frame), frame_sha256=hashlib.sha256(frame).hexdigest())
        self.assertEqual(self.cache._unpack_object(self.packed(header, frame), self.key), self.raw)

    def test_extra_frame_data_rejected_even_with_updated_outer_checksum(self):
        frame = self.frame + b"trailing"
        header = dict(self.header, frame_size=len(frame), frame_sha256=hashlib.sha256(frame).hexdigest())
        with self.assertRaises(module.CacheCorruptionError):
            self.cache._unpack_object(self.packed(header, frame), self.key)

    def test_get_quarantines_missing_fields_and_removes_index_entry(self):
        header = dict(self.header)
        del header["raw_size"]
        self.path.write_bytes(self.packed(header))
        with self.assertRaises(module.CacheCorruptionError):
            self.cache.get(self.key)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.cache.entries(), [])
        self.assertEqual(len(list(self.cache.quarantine.iterdir())), 1)

    def test_has_with_verification_treats_malformed_metadata_as_miss(self):
        self.path.write_bytes(self.packed(dict(self.header, raw_size="invalid")))
        self.assertFalse(self.cache.has(self.key, verify=True))
        self.assertFalse(self.path.exists())

    def test_rebuild_index_isolates_bad_metadata_and_recovers_intact_peer(self):
        other = self.cache.put(b"unaffected-peer")
        self.path.write_bytes(self.packed([]))
        self.assertEqual(self.cache.rebuild_index(), {"recovered": 1, "corrupt": 1})
        self.assertEqual([entry.content_hash for entry in self.cache.entries()], [other])
        self.assertEqual(self.cache.get(other), b"unaffected-peer")


if __name__ == "__main__":
    unittest.main()
