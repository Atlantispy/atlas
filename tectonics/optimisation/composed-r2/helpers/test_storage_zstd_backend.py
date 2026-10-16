"""Native acceptance checks; set WP10_ZSTD_TEST_DLL to the built private DLL.

Set WP10_ZSTD_TEST_DICTIONARY to an actually trained dictionary to exercise the
reusable-dictionary path. Skipped native/dictionary cases are not acceptance.
"""
from __future__ import annotations

import ctypes as C
import hashlib
import os
from pathlib import Path
import random
import sys
from types import SimpleNamespace
import unittest
import weakref
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'composed-r1' / 'runtime-src'))
from atlas_tectonics.resources import MemoryLimitError, WorkBudget

from storage_zstd_backend import (
    DICTIONARY_BOOKKEEPING_BYTES, DICTIONARY_ENTRY_BYTES,
    MAX_WORKSPACE_BYTES, ZstdBackend, _pointer,
)


DLL = os.environ.get('WP10_ZSTD_TEST_DLL')
DICTIONARY = os.environ.get('WP10_ZSTD_TEST_DICTIONARY')


def rule(shuffle='byte', level=1, dictionary_sha256=None):
    return SimpleNamespace(codec='trained-zstd-v1' if dictionary_sha256 else 'zstd',
        enabled=True, level=level, shuffle=shuffle, dictionary_sha256=dictionary_sha256)


@unittest.skipUnless(DLL, 'private native DLL was not supplied; not native acceptance')
class NativeZstdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.digest = hashlib.sha256(Path(DLL).read_bytes()).hexdigest()

    def backend(self, **kwargs):
        if kwargs.get('dictionaries') and 'dictionary_budget' not in kwargs:
            kwargs['dictionary_budget'] = WorkBudget(8 * 1024 * 1024)
        return ZstdBackend(DLL, expected_sha256=self.digest, **kwargs)

    def test_configuration_is_immutable(self):
        backend = self.backend()
        for name, value in (('dictionary_sha256', 'a'*64), ('max_workspace_bytes', 1),
                            ('max_chunk_bytes', 1), ('_dictionary_owner', None), ('_frozen', False)):
            with self.subTest(name=name):
                with self.assertRaisesRegex(AttributeError, 'immutable'):
                    setattr(backend, name, value)
                with self.assertRaisesRegex(AttributeError, 'immutable'):
                    delattr(backend, name)

    def test_library_identity_before_load(self):
        with patch('storage_zstd_backend.C.CDLL', side_effect=AssertionError('must not load')):
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                ZstdBackend(DLL, expected_sha256='0' * 64)

    def test_byte_exact_roundtrips_all_filters_and_numeric_types(self):
        backend = self.backend()
        samples = [
            (np.dtype('|b1'), bytes([0, 1, 1, 0]) * 1537),
            (np.dtype('|u1'), bytes(range(64)) * 101),
            (np.dtype('<i2'), np.array([-32768, -1, 0, 1, 32767] * 713, dtype='<i2').tobytes()),
            (np.dtype('<u4'), np.array([0, 1, 2**32-1, 1234567] * 1025, dtype='<u4').tobytes()),
            (np.dtype('<i8'), np.array([-(2**63), -1, 0, 2**63-1] * 1023, dtype='<i8').tobytes()),
            # Test actual float bit patterns, including distinct NaN payloads.
            (np.dtype('<f4'), np.array([0, 0x80000000, 0x7f800000, 0xff800000,
                0x7fc01234, 0x7f800001, 1] * 511, dtype='<u4').tobytes()),
            (np.dtype('<f8'), np.array([0, 0x8000000000000000, 0x7ff0000000000000,
                0xfff0000000000000, 0x7ff8000000001234, 0x7ff0000000000001, 1]
                * 401, dtype='<u8').tobytes()),
        ]
        for shuffle in ('none', 'byte', 'bit'):
            for dt, raw in samples:
                with self.subTest(shuffle=shuffle, dtype=dt.str):
                    selected = rule(shuffle)
                    self.assertLessEqual(backend.encode_workspace_bound(len(raw), dt, selected), MAX_WORKSPACE_BYTES)
                    label, payload = backend.encode(raw, dt, selected)
                    self.assertTrue(backend.owns_label(label))
                    self.assertLess(len(payload), len(raw))
                    self.assertLessEqual(backend.inspect_decode(label, payload, dt, len(raw)//dt.itemsize), MAX_WORKSPACE_BYTES)
                    self.assertEqual(backend.decode(label, payload, dt, len(raw)//dt.itemsize), raw)

    def test_all_supported_levels_at_maximum_chunk(self):
        backend = self.backend()
        raw = np.arange(8192, dtype='<u8').tobytes()
        for level in range(10):
            with self.subTest(level=level):
                label, payload = backend.encode(raw, '<u8', rule('byte', level))
                self.assertEqual(backend.decode(label, payload, '<u8', 8192), raw)

    def test_incompressible_returns_original_object(self):
        backend = self.backend()
        raw = random.Random(10831).randbytes(65536)
        label, payload = backend.encode(raw, '|u1', rule('none'))
        self.assertEqual(label, 'raw')
        self.assertIs(payload, raw)

    def test_small_chunks_return_raw_without_an_error(self):
        backend = self.backend()
        for width in (1, 2, 4, 8):
            for count in (1, 3, 7, 9):
                raw = bytes(range(width*count))
                for shuffle in ('none', 'byte', 'bit'):
                    label, payload = backend.encode(raw, f'<u{width}', rule(shuffle))
                    actual = payload if label == 'raw' else backend.decode(label, payload, f'<u{width}', count)
                    self.assertEqual(actual, raw)

    def test_filters_have_stable_known_layout_and_odd_count_inverse(self):
        backend = self.backend()
        self.assertEqual(backend.transform_for_training(bytes([1, 2, 3, 4, 5, 6]), '<u2', 'byte'),
                         bytes([1, 3, 5, 2, 4, 6]))
        self.assertEqual(backend.transform_for_training(bytes([1, 2, 4]), '|u1', 'bit'), bytes([17, 1, 0]))
        for width in (1, 2, 4, 8):
            for count in (1, 3, 7, 9, 81):
                raw = random.Random(width*1000+count).randbytes(width*count)
                for shuffle, number in (('byte', 1), ('bit', 2)):
                    transformed = backend.transform_for_training(raw, f'<u{width}', shuffle)
                    allocation, output = backend._allocate_arena(len(raw))
                    backend._check(backend._lib.wp10_zstd_transform(_pointer(transformed), output,
                        len(raw), width, number, 1))
                    self.assertEqual(C.string_at(output, len(raw)), raw)
                    del allocation

    def test_inspection_and_invalid_frame_refusal_allocate_no_arena(self):
        backend = self.backend()
        raw = bytes(4096)
        label, payload = backend.encode(raw, '<u4', rule())
        with patch.object(ZstdBackend, '_allocate_arena', side_effect=AssertionError('must not allocate')):
            self.assertGreater(backend.inspect_decode(label, payload, '<u4', 1024), 0)
            cases = [(label, payload[:-1], '<u4', 1024), (label, payload+b'junk', '<u4', 1024),
                     (label, payload+payload, '<u4', 1024), (label, payload, '<u4', 1023),
                     (label.replace(':1:', ':99:'), payload, '<u4', 1024),
                     (label, b'not a frame', '<u4', 1024), (label, payload, '>u4', 1024)]
            for args in cases:
                with self.subTest(label=args[0], payload_n=len(args[1]), count=args[3]):
                    with self.assertRaises(ValueError):
                        backend.inspect_decode(*args)

    def test_corrupt_frame_checksum_fails_decode(self):
        backend = self.backend()
        label, payload = backend.encode(bytes(4096), '<u4', rule())
        damaged = payload[:-1] + bytes([payload[-1] ^ 1])
        with self.assertRaises(ValueError):
            backend.decode(label, damaged, '<u4', 1024)

    def test_retained_failure_tracebacks_do_not_retain_native_arenas(self):
        backend = self.backend()
        raw = bytes(4096)
        label, payload = backend.encode(raw, '<u4', rule())
        damaged = payload[:-1] + bytes([payload[-1] ^ 1])
        allocate = backend._allocate_arena
        references, failures = [], []

        def track(nbytes):
            allocation, pointer = allocate(nbytes)
            references.append(weakref.ref(allocation))
            return allocation, pointer

        def retain_failure(function):
            try:
                function()
            except ValueError as failure:
                failures.append(failure)
            else:
                self.fail('expected a native/output validation failure')
            self.assertIsNotNone(failures[-1].__traceback__)
            self.assertTrue(references)
            self.assertTrue(all(reference() is None for reference in references))

        with patch.object(ZstdBackend, '_allocate_arena', side_effect=track):
            # Actual checksum failure after the arena has been allocated.
            retain_failure(lambda: backend.decode(label, damaged, '<u4', 1024))
            # Native refusal and successful-status/invalid-output branches.
            for status in (1, 0):
                with patch.object(backend._lib, 'wp10_zstd_encode', return_value=status):
                    retain_failure(lambda: backend.encode(raw, '<u4', rule()))
                with patch.object(backend._lib, 'wp10_zstd_decode', return_value=status):
                    retain_failure(lambda: backend.decode(label, payload, '<u4', 1024))
            with patch.object(backend._lib, 'wp10_zstd_transform', return_value=1):
                retain_failure(lambda: backend.transform_for_training(raw, '<u4', 'byte'))
        self.assertEqual(len(references), 6)
        self.assertEqual(len(failures), 6)

    def test_bound_refusal_happens_before_arena_allocation(self):
        backend = self.backend(max_workspace_bytes=1024)
        with patch.object(ZstdBackend, '_allocate_arena', side_effect=AssertionError('must not allocate')):
            with self.assertRaisesRegex(ValueError, 'aggregate workspace'):
                backend.encode(bytes(4096), '<u4', rule())

    def test_native_arena_underallocation_is_refused_without_writes(self):
        backend = self.backend()
        raw = bytes(4096)
        arena_n, output_cap = C.c_size_t(), C.c_size_t()
        backend._check(backend._lib.wp10_zstd_plan_encode(len(raw), 4, 1, 1, None, 0,
            C.byref(arena_n), C.byref(output_cap)))
        allocation, pointer = backend._allocate_arena(arena_n.value)
        C.memset(pointer, 0xA5, arena_n.value)
        output, output_n = C.c_void_p(), C.c_size_t()
        status = backend._lib.wp10_zstd_encode(pointer, arena_n.value-1, _pointer(raw), len(raw),
            4, 1, 1, None, 0, C.byref(output), C.byref(output_n))
        self.assertNotEqual(status, 0)
        self.assertIsNone(output.value)
        self.assertEqual(output_n.value, 0)
        self.assertEqual(C.string_at(pointer, arena_n.value), b'\xA5' * arena_n.value)
        del allocation

    def test_trained_rule_never_silently_becomes_plain_zstd(self):
        backend = self.backend()
        with self.assertRaisesRegex(ValueError, 'not retained'):
            backend.encode(bytes(4096), '<u4', rule(dictionary_sha256='a'*64))

    def test_dictionary_retention_requires_funded_lifetime(self):
        dictionary = bytes(8192)
        sha = hashlib.sha256(dictionary).hexdigest()
        dictionaries = {sha: dictionary}
        with self.assertRaisesRegex(ValueError, 'dictionary_budget'):
            ZstdBackend(DLL, expected_sha256=self.digest, dictionaries=dictionaries)
        budget = WorkBudget(65536)
        with budget.reserve(len(dictionary), category='source-owner'):
            backend = self.backend(dictionaries=dictionaries, dictionary_budget=budget)
            expected = len(dictionary) + DICTIONARY_BOOKKEEPING_BYTES + DICTIONARY_ENTRY_BYTES
            self.assertEqual(budget.reserved_bytes, len(dictionary) + expected)
        # Source owner released independently; backend still funds every byte.
        self.assertEqual(budget.reserved_bytes, expected)
        self.assertIs(backend._dictionary(sha), dictionary)
        reference = weakref.ref(backend)
        retained_view = backend._dictionaries
        del backend
        self.assertIsNone(reference())
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(dict(retained_view), {})

    def test_dictionary_admission_refusal_and_entry_cap(self):
        dictionary = bytes(8192)
        sha = hashlib.sha256(dictionary).hexdigest()
        budget = WorkBudget(8192)
        with patch('storage_zstd_backend.C.CDLL', side_effect=AssertionError('must not load')):
            with self.assertRaises(MemoryLimitError):
                self.backend(dictionaries={sha: dictionary}, dictionary_budget=budget)
            over = {hashlib.sha256(bytes([i])*256).hexdigest(): bytes([i])*256 for i in range(65)}
            with self.assertRaisesRegex(ValueError, 'at most 64'):
                self.backend(dictionaries=over, dictionary_budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_failed_constructor_retains_charge_with_traceback(self):
        dictionary = bytes(8192)
        sha = hashlib.sha256(dictionary).hexdigest()
        budget = WorkBudget(65536)
        failures = []
        with patch('storage_zstd_backend.C.CDLL', side_effect=ValueError('synthetic library load failure')):
            try:
                self.backend(dictionaries={sha: dictionary}, dictionary_budget=budget)
            except ValueError as failure:
                failures.append(failure)
            else:
                self.fail('expected constructor failure')
        expected = len(dictionary) + DICTIONARY_BOOKKEEPING_BYTES + DICTIONARY_ENTRY_BYTES
        self.assertIsNotNone(failures[0].__traceback__)
        self.assertEqual(budget.reserved_bytes, expected)
        failures[0].__traceback__ = None
        failures.clear()
        self.assertEqual(budget.reserved_bytes, 0)

    @unittest.skipUnless(DICTIONARY, 'trained dictionary was not supplied; not dictionary acceptance')
    def test_reusable_dictionary_identity_and_fresh_backend(self):
        dictionary = Path(DICTIONARY).read_bytes()
        sha = hashlib.sha256(dictionary).hexdigest()
        backend = self.backend(dictionaries={sha: dictionary})
        raw = (b'WP10 exact reusable trained dictionary example. ' * 700)[:32768]
        for shuffle in ('none', 'byte', 'bit'):
            with self.subTest(shuffle=shuffle):
                label, payload = backend.encode(raw, '|u1', rule(shuffle, dictionary_sha256=sha))
                self.assertTrue(backend.owns_label(label))
                self.assertIn(sha, label)
                reopened = self.backend(dictionaries={sha: dictionary})
                self.assertEqual(reopened.decode(label, payload, '|u1', len(raw)), raw)
                with self.assertRaisesRegex(ValueError, 'not retained'):
                    self.backend().inspect_decode(label, payload, '|u1', len(raw))
                with self.assertRaises(ValueError):
                    reopened.inspect_decode(label.replace(sha, '-'), payload, '|u1', len(raw))
        with self.assertRaisesRegex(ValueError, 'bytes/hash'):
            self.backend(dictionaries={sha: dictionary[:-1] + bytes([dictionary[-1] ^ 1])})


if __name__ == '__main__':
    unittest.main()
