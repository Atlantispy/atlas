"""Focused byte-codec tests, without native terrain imports or model runs."""
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import unittest
from unittest.mock import patch

from . import compression as codec


class CompressionTests(unittest.TestCase):
    def test_exact_roundtrip_for_empty_json_binary_and_repeated_records(self):
        random_source = random.Random(32764)
        samples = (b'', b'{}', '"\u2603 exact UTF-8"'.encode('utf-8'),
                   bytes(range(256)), random_source.randbytes(65536),
                   b'{"mass_kg":"67/9223372036854775808","source":"unchanged"}\n' * 8192)
        for raw in samples:
            with self.subTest(raw_size=len(raw)):
                frame = codec.encode(raw)
                self.assertEqual(codec.decode(frame, len(raw)), raw)
                self.assertEqual(codec.encode(raw), frame)
        self.assertLess(len(codec.encode(samples[-1])), len(samples[-1]))

    def test_full_limit_roundtrip_and_oversize_rejection(self):
        raw = b'x' * codec.MAX_RAW_BYTES
        frame = codec.encode(raw)
        self.assertEqual(codec.decode(frame, len(raw)), raw)
        with self.assertRaises(codec.CompressionError):
            codec.encode(raw + b'x')
        with self.assertRaises(codec.CompressionError):
            codec.decode(frame, codec.MAX_RAW_BYTES + 1)

    def test_wrong_types_expected_size_and_missing_header_rejected(self):
        frame = codec.encode(b'{}')
        for raw in (None, '', bytearray(b'{}'), memoryview(b'{}')):
            with self.subTest(raw_type=type(raw)), self.assertRaises(codec.CompressionError):
                codec.encode(raw)
        for size in (None, -1, True, 2.0, 0, 1, 3):
            with self.subTest(size=size), self.assertRaises(codec.CompressionError):
                codec.decode(frame, size)
        for invalid in (None, '', bytearray(frame), b'', b'abcde'):
            with self.subTest(frame_type=type(invalid)), self.assertRaises(codec.CompressionError):
                codec.decode(invalid, 2)
        with self.assertRaises(codec.CompressionError):
            codec.decode(b'x' * (codec.MAX_FRAME_BYTES + 1), 0)

    def test_truncation_checksum_corruption_and_trailing_data_rejected(self):
        raw = b'unchanged accepted record ' * 100
        frame = codec.encode(raw)
        for end in range(len(frame)):
            with self.subTest(end=end), self.assertRaises(codec.CompressionError):
                codec.decode(frame[:end], len(raw))
        corrupt = frame[:-1] + bytes([frame[-1] ^ 1])
        with self.assertRaises(codec.CompressionError):
            codec.decode(corrupt, len(raw))
        for suffix in (b'\x00', b'ignored?', codec.encode(b''), frame):
            with self.subTest(suffix_size=len(suffix)), self.assertRaisesRegex(
                    codec.CompressionError, 'trailing|concatenated'):
                codec.decode(frame + suffix, len(raw))

    def test_missing_checksum_content_size_dictionary_and_skippable_frame_rejected(self):
        raw = b'a' * 1024
        frame = codec.encode(raw)
        missing_checksum = frame[:4] + bytes([frame[4] & ~4]) + frame[5:-4]
        with self.assertRaisesRegex(codec.CompressionError, 'checksum'):
            codec.decode(missing_checksum, len(raw))
        dictionary = frame[:4] + bytes([frame[4] | 1]) + frame[5:]
        with self.assertRaisesRegex(codec.CompressionError, 'dictionary'):
            codec.decode(dictionary, len(raw))
        # Valid unknown-content-size frame header, a final empty raw block and
        # dummy checksum. Rejected at the header before decompression/allocation.
        unknown_size = b'\x28\xb5\x2f\xfd\x04\x00\x01\x00\x00\x00\x00\x00\x00'
        with self.assertRaisesRegex(codec.CompressionError, 'content size'):
            codec.decode(unknown_size, 0)
        skippable = b'\x50\x2a\x4d\x18\x00\x00\x00\x00'
        with self.assertRaisesRegex(codec.CompressionError, 'standard Zstandard frame'):
            codec.decode(skippable, 0)

    def test_forged_smaller_content_size_cannot_grow_destination(self):
        raw = bytes(range(256)) * 4
        frame = codec.encode(raw)
        self.assertEqual(frame[4] >> 6, 1)  # Two-byte size, offset by 256.
        offset = 5 if frame[4] & 32 else 6
        expected = len(raw) - 1
        forged = frame[:offset] + (expected - 256).to_bytes(2, 'little') + frame[offset + 2:]
        allocate = codec.ct.create_string_buffer
        with patch.object(codec.ct, 'create_string_buffer', wraps=allocate) as allocation:
            with self.assertRaisesRegex(codec.CompressionError, 'bounded decompression'):
                codec.decode(forged, expected)
        allocation.assert_called_once_with(expected)

    def test_identity_pins_installed_library_and_detects_changed_backing_bytes(self):
        identity = codec.identity()
        self.assertEqual(identity['codec'], 'zstandard')
        self.assertEqual(identity['version'], '1.5.7')
        self.assertEqual(identity['workers'], 0)
        path = Path(identity['library_path'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), identity['library_sha256'])
        frame = codec.encode(b'unchanged')
        with patch.object(codec, '_digest', return_value='0' * 64):
            with self.assertRaisesRegex(codec.CompressionError, 'differs'):
                codec.identity()
            with self.assertRaises(codec.CompressionError):
                codec.encode(b'unchanged')
            with self.assertRaises(codec.CompressionError):
                codec.decode(frame, len(b'unchanged'))

    def test_fresh_process_reproduces_frame_and_codec_identity(self):
        raw = b'{"immutable":"original bytes","fraction":"1/18446744073709551616"}' * 128
        frame = codec.encode(raw)
        script = ('import hashlib,json; from work.native_terrain_r3 import compression as c; '
                  'raw=' + repr(raw) + '; frame=c.encode(raw); '
                  'print(json.dumps({"frame_sha256":hashlib.sha256(frame).hexdigest(),'
                  '"same":c.decode(frame,len(raw))==raw,"identity":c.identity()},sort_keys=True))')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        child = subprocess.run([sys.executable, '-B', '-c', script], check=True,
            capture_output=True, text=True, timeout=30,
            cwd=Path(__file__).resolve().parents[2], **options)
        actual = json.loads(child.stdout)
        self.assertTrue(actual['same'])
        self.assertEqual(actual['frame_sha256'], hashlib.sha256(frame).hexdigest())
        self.assertEqual(actual['identity'], codec.identity())


if __name__ == '__main__':
    unittest.main(verbosity=2)
