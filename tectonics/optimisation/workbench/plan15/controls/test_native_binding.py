"""Authored, unexecuted controls for the actual native-binding source.

Future cleared execution uses synthetic PE bytes and a mocked private Windows
API factory. No H3/MPFR DLL or scientific module is loaded by these controls.
"""
import copy
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import sys
import unittest
from unittest import mock


SOURCE = Path(__file__).with_name('native_binding.py')
SPEC = importlib.util.spec_from_file_location('plan15_native_binding_controls', SOURCE)
NB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NB)


def pe_fixture():
    """A small PE64 DLL with 14 distinct code exports and a backed export table."""
    data = bytearray(0x1600)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 0x84, 0x8664, 2, 0, 0, 0, 0xf0, 0x2022)
    optional = 0x98
    struct.pack_into('<H', data, optional, 0x20b)
    struct.pack_into('<II', data, optional + 56, 0x4000, 0x400)
    struct.pack_into('<I', data, optional + 108, 16)
    struct.pack_into('<II', data, optional + 112, 0x2000, 0x800)
    table = optional + 0xf0
    for i, (name, va, raw, flags) in enumerate((
            (b'.text', 0x1000, 0x400, 0x60000020),
            (b'.edata', 0x2000, 0xa00, 0x40000040))):
        base = table + i * 40
        data[base:base + len(name)] = name
        struct.pack_into('<IIII', data, base + 8, 0x800 if i else 0x600,
                         va, 0x800 if i else 0x600, raw)
        struct.pack_into('<I', data, base + 36, flags)
    struct.pack_into('<IIHHIIIIIII', data, 0xa00, 0, 0, 0, 0, 0x20e0, 1,
                     14, 14, 0x2040, 0x2080, 0x20c0)
    data[0xae0:0xae0 + 14] = b'libmpfr-6.dll\0'
    cursor = 0xb00
    for i, name in enumerate(NB.EXPORT_NAMES):
        struct.pack_into('<I', data, 0xa40 + 4 * i, 0x1100 + i * 8)
        struct.pack_into('<I', data, 0xa80 + 4 * i, 0x2000 + cursor - 0xa00)
        struct.pack_into('<H', data, 0xac0 + 2 * i, i)
        encoded = name.encode('ascii') + b'\0'
        data[cursor:cursor + len(encoded)] = encoded
        cursor += len(encoded)
    return bytes(data)


def expected_fixture():
    return dict(schema='plan15.mpfr-exports.r1', path=str(Path(NB._PINNED_PATH)),
                sha256=NB._PINNED_SHA256, size=0x4000,
                exports={name: 0x1100 + i * 8 for i, name in enumerate(NB.EXPORT_NAMES)})


def receipt_fixture(expected=None, pid=200, creation=20):
    expected = expected or expected_fixture()
    return dict(schema='plan15.native-binding.r1', pid=pid, creation_filetime=creation,
                module=dict(path=expected['path'], sha256=expected['sha256'],
                            base=0x10000000, size=expected['size']),
                exports={n: dict(address=0x10000000 + rva, rva=rva)
                         for n, rva in expected['exports'].items()})


class FakeAPI:
    def __init__(self, actual=200, launch=100):
        self.actual, self.launch = actual, launch
        self.identities = {900: (launch, 10)}
        self.closed, self.opens, self.module_calls = [], [], 0
        self.parent = launch
        self.members = sorted({os.getpid(), actual, launch})
        self.module_info = dict(path=str(Path(NB._PINNED_PATH)), base=0x10000000, size=0x4000)
        self.next_handle = 1000
        self.fail_open = None
        self.fail_close = set()
        self.dead = set()

    def open(self, pid):
        if pid == self.fail_open:
            raise NB.BindingRefused('PROCESS_OPEN', 'planted open failure')
        self.next_handle += 1
        handle = self.next_handle
        self.identities[handle] = (pid, 10 if pid == self.launch else 20)
        self.opens.append((pid, handle))
        return handle

    def identity(self, handle):
        if handle in self.dead:
            raise NB.BindingRefused('PROCESS_DEAD', 'planted dead process')
        return self.identities[handle]

    def parent_pid(self, handle):
        return self.parent

    def job_pids(self):
        return list(self.members)

    def module(self, handle, path):
        self.module_calls += 1
        return dict(self.module_info)

    def close(self, handle):
        self.closed.append(handle)
        if handle in self.fail_close:
            raise NB.BindingRefused('HANDLE_CLOSE', 'planted close failure')


class NativeBindingControls(unittest.TestCase):
    def setUp(self):
        # The component's only OS identity helper is also mocked. Native API
        # operations below are exclusively FakeAPI, never _WindowsAPI.
        patcher = mock.patch.object(NB.os, 'getpid', return_value=300)
        patcher.start()
        self.addCleanup(patcher.stop)

    def assert_refuses(self, code, function, *args):
        with self.assertRaises(NB.BindingRefused) as caught:
            function(*args)
        self.assertEqual(caught.exception.code, code)
        self.assertLessEqual(len(caught.exception.message), 320)
        return caught.exception

    def test_import_has_no_native_query_or_library_activation(self):
        with mock.patch.object(ctypes, 'WinDLL', side_effect=AssertionError('native activation')):
            spec = importlib.util.spec_from_file_location('plan15_binding_passive_import', SOURCE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.assertEqual(module._EXPECTED_CACHE, {})

    def test_pinned_read_and_defensive_cache_preserve_exact_named_rvas(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'libmpfr-6.dll'
            data = pe_fixture()
            path.write_bytes(data)
            sha = hashlib.sha256(data).hexdigest()
            with mock.patch.object(NB, '_PINNED_PATH', str(path)), \
                    mock.patch.object(NB, '_PINNED_SHA256', sha), \
                    mock.patch.object(NB, '_EXPECTED_CACHE', {}):
                parsed = NB.read_expected_exports(path, sha)
                self.assertEqual(parsed['size'], 0x4000)
                self.assertEqual(parsed['exports'], expected_fixture()['exports'])
                parsed['exports']['mpfr_mul'] = 1
                with mock.patch('builtins.open', side_effect=AssertionError('second file scan')):
                    again = NB.read_expected_exports(path, sha)
                self.assertEqual(again['exports']['mpfr_mul'], 0x1100)
                self.assert_refuses('SOURCE_SHA', NB.read_expected_exports, path, '0' * 64)
                self.assert_refuses('SOURCE_PATH', NB.read_expected_exports, path.with_name('other.dll'), sha)

    def test_pe_bounds_counts_and_architecture_fail_closed(self):
        cases = []
        for offset, fmt, value, code in (
                (0x3c, '<I', 0xfffffffc, 'PE_BOUNDS'),
                (0x84, '<H', 0x14c, 'PE_MACHINE'),
                (0x98, '<H', 0x10b, 'PE_OPTIONAL'),
                (0xa00 + 20, '<I', 65537, 'PE_EXPORT_COUNT'),
                (0xa00 + 28, '<I', 0x3fff, 'PE_RVA'),
                (0xac0, '<H', 14, 'PE_ORDINAL')):
            data = bytearray(pe_fixture())
            struct.pack_into(fmt, data, offset, value)
            cases.append((bytes(data), code))
        for data, code in cases:
            with self.subTest(code=code):
                self.assert_refuses(code, NB._parse_pe, data, str(Path(NB._PINNED_PATH)), NB._PINNED_SHA256)

    def test_pe_forwarded_noncode_alias_and_duplicate_exports_refuse(self):
        for kind in ('forwarded', 'noncode', 'alias', 'duplicate'):
            data = bytearray(pe_fixture())
            if kind == 'forwarded':
                struct.pack_into('<I', data, 0xa40, 0x2100)
                code = 'PE_FORWARDED'
            elif kind == 'noncode':
                struct.pack_into('<I', data, 0xa40, 0x2801)
                code = 'PE_NON_CODE'
            elif kind == 'alias':
                struct.pack_into('<I', data, 0xa44, 0x1100)
                code = 'EXPORT_ALIAS'
            else:
                struct.pack_into('<I', data, 0xa84, struct.unpack_from('<I', data, 0xa80)[0])
                code = 'PE_DUPLICATE_NAME'
            with self.subTest(kind=kind):
                self.assert_refuses(code, NB._parse_pe, bytes(data), str(Path(NB._PINNED_PATH)), NB._PINNED_SHA256)

    def test_receipt_closed_schemas_exact_integers_and_named_rvas(self):
        expected = expected_fixture()
        self.assertIsNone(NB.validate_receipt(receipt_fixture(), expected))
        mutations = (
            (lambda r: r.update(extra=True), 'RECEIPT_SCHEMA'),
            (lambda r: r.update(pid=True), 'PROCESS_IDENTITY'),
            (lambda r: r.update(creation_filetime=0), 'PROCESS_IDENTITY'),
            (lambda r: r['module'].update(base=True), 'MODULE_BASE'),
            (lambda r: r['module'].update(size=0x4001), 'MODULE_SOURCE'),
            (lambda r: r['module'].update(path='other.dll'), 'MODULE_SOURCE'),
            (lambda r: r['module'].update(sha256='0' * 64), 'MODULE_SOURCE'),
            (lambda r: r['exports'].pop('mpfr_mul'), 'RECEIPT_EXPORTS'),
            (lambda r: r['exports']['mpfr_mul'].update(rva=0x1101), 'EXPORT_BINDING'),
            (lambda r: r['exports']['mpfr_mul'].update(address=0x10001101), 'EXPORT_BINDING'))
        for mutate, code in mutations:
            receipt = receipt_fixture()
            mutate(receipt)
            with self.subTest(code=code):
                self.assert_refuses(code, NB.validate_receipt, receipt, expected)

    def test_live_child_and_same_process_admission_retain_actual_not_launcher(self):
        for actual in (100, 200):
            api = FakeAPI(actual=actual)
            with self.subTest(actual=actual), mock.patch.object(NB, '_api_factory', return_value=api):
                bound = NB.open_admitted(actual, 100, 900)
                self.assertEqual(bound.pid, actual)
                self.assertEqual(bound.creation_filetime, 10 if actual == 100 else 20)
                self.assertEqual(bound.owner_record['relationship'],
                                 'same-process' if actual == 100 else 'live-immediate-child')
                self.assertTrue(bound.owner_record['job_proof']['complete'])
                self.assertNotIn('handle', bound.owner_record)
                self.assertNotIn(900, api.closed)
                actual_handle = api.opens[-1][1]
                self.assertNotIn(actual_handle, api.closed)
                bound.close()
                bound.close()
                self.assertEqual(api.closed.count(actual_handle), 1)
                self.assertTrue(bound.owner_record['closed'])

    def test_relationship_job_handle_and_open_faults_close_partial_handles(self):
        for fault, code in (('ancestry', 'PROCESS_ANCESTRY'), ('membership', 'JOB_MEMBERSHIP'),
                            ('duplicate-job', 'JOB_MEMBERSHIP'), ('borrowed', 'LAUNCH_IDENTITY'),
                            ('open', 'PROCESS_OPEN')):
            api = FakeAPI()
            if fault == 'ancestry': api.parent = 999
            if fault == 'membership': api.members.remove(200)
            if fault == 'duplicate-job': api.members.append(api.members[0])
            if fault == 'borrowed': api.identities[900] = (999, 10)
            if fault == 'open': api.fail_open = 200
            with self.subTest(fault=fault), mock.patch.object(NB, '_api_factory', return_value=api):
                self.assert_refuses(code, NB.open_admitted, 200, 100, 900)
            self.assertCountEqual(api.closed, [h for p, h in api.opens])
            self.assertNotIn(900, api.closed)

    def test_creation_mismatch_and_cleanup_failure_preserve_refusal(self):
        api = FakeAPI()
        original = api.open
        def wrong_creation(pid):
            handle = original(pid)
            api.identities[handle] = (pid, 11)
            return handle
        api.open = wrong_creation
        with mock.patch.object(NB, '_api_factory', return_value=api):
            self.assert_refuses('LAUNCH_IDENTITY', NB.open_admitted, 200, 100, 900)
        self.assertCountEqual(api.closed, [h for p, h in api.opens])
        api = FakeAPI()
        api.parent = 999
        api.fail_close = {1001}
        with mock.patch.object(NB, '_api_factory', return_value=api):
            self.assert_refuses('ADMISSION_CLEANUP', NB.open_admitted, 200, 100, 900)
        self.assertCountEqual(api.closed, [1001, 1002])

    def test_query_uses_independent_pinned_metadata_and_live_module_then_refuses_change(self):
        api, expected = FakeAPI(), expected_fixture()
        with mock.patch.object(NB, '_api_factory', return_value=api), \
                mock.patch.object(NB, 'read_expected_exports', return_value=copy.deepcopy(expected)):
            bound = NB.open_admitted(200, 100, 900)
            receipt = bound.query(expected)
            self.assertEqual(receipt['pid'], 200)
            self.assertEqual(receipt['exports']['mpfr_mul']['address'], 0x10001100)
            receipt['module']['base'] = 1
            again = bound.query(expected)
            self.assertEqual(again['module']['base'], 0x10000000)
            self.assertEqual(api.module_calls, 2)
            self.assertEqual(bound.owner_record['costs']['cached_receipt_reuses'], 1)
            api.module_info['base'] += 0x10000
            self.assert_refuses('MODULE_LIFETIME_CHANGED', bound.query, expected)
            self.assert_refuses('BINDING_FAILED', bound.query, expected)
            self.assertEqual(bound.owner_record['query_failure']['code'], 'MODULE_LIFETIME_CHANGED')
            self.assertEqual(api.module_calls, 3)
            bound.close()
            self.assert_refuses('PROCESS_CLOSED', bound.query, expected)

    def test_query_refuses_forged_expected_dead_process_and_unknown_module(self):
        for fault, code in (('expected', 'EXPECTED_TAMPER'), ('dead', 'PROCESS_DEAD'),
                            ('size', 'MODULE_SOURCE'), ('path', 'MODULE_SOURCE')):
            api, expected = FakeAPI(), expected_fixture()
            trusted = copy.deepcopy(expected)
            with mock.patch.object(NB, '_api_factory', return_value=api), \
                    mock.patch.object(NB, 'read_expected_exports', return_value=trusted):
                bound = NB.open_admitted(200, 100, 900)
                if fault == 'expected': expected['exports']['mpfr_mul'] += 1
                if fault == 'dead': api.dead.add(api.opens[-1][1])
                if fault == 'size': api.module_info['size'] += 1
                if fault == 'path': api.module_info['path'] = 'other.dll'
                with self.subTest(fault=fault):
                    self.assert_refuses(code, bound.query, expected)
                self.assertEqual(bound.owner_record['query_failure']['code'], code)
                bound.close()
                self.assertTrue(bound.owner_record['closed'])

    def test_close_failure_is_reported_without_claiming_closed(self):
        api = FakeAPI()
        with mock.patch.object(NB, '_api_factory', return_value=api):
            bound = NB.open_admitted(200, 100, 900)
        api.fail_close.add(api.opens[-1][1])
        self.assert_refuses('HANDLE_CLOSE', bound.close)
        self.assertFalse(bound.owner_record['closed'])
        self.assertEqual(bound.owner_record['close_failure']['code'], 'HANDLE_CLOSE')

    def test_self_capture_checks_actual_ctypes_pointers_and_always_closes(self):
        expected = expected_fixture()
        function_type = ctypes.CFUNCTYPE(ctypes.c_int)
        pointers = {n: function_type(0x10000000 + rva) for n, rva in expected['exports'].items()}
        for fault in (None, 'pointer', 'integer', 'missing', 'module'):
            api = FakeAPI(actual=os.getpid())
            supplied = dict(pointers)
            if fault == 'pointer': supplied['mpfr_mul'] = function_type(0x10001101)
            if fault == 'integer': supplied['mpfr_mul'] = 0x10001100
            if fault == 'missing': supplied.pop('mpfr_mul')
            if fault == 'module': api.module_info['size'] += 1
            with self.subTest(fault=fault), mock.patch.object(NB, '_api_factory', return_value=api), \
                    mock.patch.object(NB, 'read_expected_exports', return_value=expected):
                if fault:
                    self.assert_refuses('BOUND_EXPORTS' if fault == 'missing' else
                                        'MODULE_SOURCE' if fault == 'module' else 'BOUND_POINTER',
                                        NB.capture_self, expected, supplied)
                else:
                    receipt = NB.capture_self(expected, supplied)
                    self.assertEqual(receipt['pid'], os.getpid())
                    self.assertEqual(receipt['creation_filetime'], 20)
            self.assertCountEqual(api.closed, [h for p, h in api.opens])


def known_fault_cli():
    """Consequential future CLI control: explicit refusal is non-zero, never PASS."""
    receipt = receipt_fixture()
    receipt['pid'] = True
    try:
        NB.validate_receipt(receipt, expected_fixture())
    except NB.BindingRefused as exc:
        result = dict(schema='plan15.native-binding-known-fault.r1', status='REFUSED',
                      expected_refusal_code='PROCESS_IDENTITY',
                      error=dict(code=exc.code, message=exc.message),
                      native_queries=0, scientific_eligibility=False,
                      source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest())
        print(json.dumps(result, sort_keys=True))
        return 2 if exc.code == 'PROCESS_IDENTITY' else 1
    print(json.dumps(dict(schema='plan15.native-binding-known-fault.r1',
                          status='UNEXPECTED_ACCEPT', scientific_eligibility=False)))
    return 1


if __name__ == '__main__':
    if sys.argv[1:] == ['--known-fault']:
        raise SystemExit(known_fault_cli())
    unittest.main(verbosity=2)
