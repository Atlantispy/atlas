"""Read-only, source-pinned MPFR bindings. Importing this source queries nothing.

This component supplies evidence, not scientific acceptance. Windows system API
libraries are resolved lazily; MPFR/H3 is never loaded or initialised here.
"""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path
import struct
import time


EXPORT_NAMES = (
    'mpfr_mul', 'mpfr_add', 'mpfr_set', 'mpfr_less_p', 'mpfr_greater_p',
    'mpfr_lessequal_p', 'mpfr_regular_p', 'mpfr_sgn', 'mpfr_get_exp',
    'mpfr_flags_save', 'mpfr_flags_clear', 'mpfr_flags_restore',
    'mpfr_get_emin', 'mpfr_get_emax',
)
_PINNED_PATH = (r'C:\Users\LOCAL_USER\Documents\Codex\2026-09-02\the-diadem-local-tasks-10'
                r'\.r44-env\Lib\site-packages\gmpy2.libs\libmpfr-6.dll')
_PINNED_SHA256 = 'b81a548eb7a23d4e3acbe296f1eff077a0b284617a2c1cc53a1ccdb0637b52b8'
_MAX_FILE = 64 << 20
_MAX_EXPORTS = 65536
_MAX_JOB_PIDS = 65536
_MAX_MODULES = 4096
_READ_RIGHTS = 0x00100000 | 0x0400 | 0x0010  # SYNCHRONIZE, QUERY_INFORMATION, VM_READ.
_EXPECTED_CACHE = {}


class BindingRefused(ValueError):
    """Bounded error identity; callers retain their own operation/finality record."""
    def __init__(self, code, message):
        self.code = str(code)[:64]
        self.message = str(message)[:320]
        super().__init__(self.code + ': ' + self.message)


def _require(condition, code, message):
    if not condition:
        raise BindingRefused(code, message)


def _positive(value):
    return type(value) is int and 0 < value < (1 << 64)


def _keys(value, names, code):
    _require(type(value) is dict and set(value) == set(names), code, 'Closed object keys required')


def _path(value):
    _require(isinstance(value, (str, Path)), 'SOURCE_PATH', 'Path must name the pinned MPFR DLL')
    text = str(Path(value))
    _require(os.path.isabs(text) and text == str(Path(_PINNED_PATH)),
             'SOURCE_PATH', 'Exact pinned absolute MPFR path required')
    return text


def _copy_expected(value):
    return dict(schema=value['schema'], path=value['path'], sha256=value['sha256'],
                size=value['size'], exports=dict(value['exports']))


def _validate_expected(expected):
    _keys(expected, ('schema', 'path', 'sha256', 'size', 'exports'), 'EXPECTED_SCHEMA')
    _require(expected['schema'] == 'plan15.mpfr-exports.r1', 'EXPECTED_SCHEMA', 'Wrong metadata schema')
    _require(type(expected['path']) is str, 'SOURCE_PATH', 'Expected path must be a string')
    _path(expected['path'])
    _require(expected['sha256'] == _PINNED_SHA256, 'SOURCE_SHA', 'Wrong pinned MPFR hash')
    _require(_positive(expected['size']) and expected['size'] <= 0xffffffff,
             'EXPECTED_SIZE', 'Invalid PE SizeOfImage')
    _keys(expected['exports'], EXPORT_NAMES, 'EXPECTED_EXPORTS')
    rvas = list(expected['exports'].values())
    _require(all(_positive(v) and v < expected['size'] for v in rvas),
             'EXPECTED_RVA', 'Export RVA must lie inside the image')
    _require(len(set(rvas)) == len(EXPORT_NAMES), 'EXPORT_ALIAS', 'Export aliases are forbidden')


def _parse_pe(data, path, sha256):
    """Private bounded byte parser; only read_expected_exports establishes its pin."""
    _require(type(data) is bytes and 512 <= len(data) <= _MAX_FILE, 'PE_SIZE', 'PE file bounds')

    def span(offset, count):
        _require(type(offset) is int and type(count) is int and offset >= 0 and count >= 0
                 and offset + count <= len(data), 'PE_BOUNDS', 'Out-of-file PE span')
        return offset

    def number(fmt, offset):
        span(offset, struct.calcsize(fmt))
        return struct.unpack_from(fmt, data, offset)[0]

    _require(data[:2] == b'MZ', 'PE_DOS', 'DOS signature required')
    pe = number('<I', 0x3c)
    span(pe, 24)
    _require(data[pe:pe + 4] == b'PE\0\0', 'PE_SIGNATURE', 'PE signature required')
    _require(number('<H', pe + 4) == 0x8664, 'PE_MACHINE', 'AMD64 required')
    count, optional_size = number('<H', pe + 6), number('<H', pe + 20)
    _require(1 <= count <= 96 and 120 <= optional_size <= 4096,
             'PE_HEADERS', 'Bounded section/optional headers required')
    optional = pe + 24
    span(optional, optional_size)
    _require(number('<H', optional) == 0x20b, 'PE_OPTIONAL', 'PE32+ required')
    image_size, header_size = number('<I', optional + 56), number('<I', optional + 60)
    _require(0 < header_size <= len(data) and header_size < image_size <= 0xffffffff,
             'PE_IMAGE', 'Invalid image/header size')
    _require(number('<I', optional + 108) >= 1, 'PE_EXPORT_DIRECTORY', 'Export directory missing')
    export_rva, export_size = number('<I', optional + 112), number('<I', optional + 116)
    _require(export_rva > 0 and 40 <= export_size and export_rva + export_size <= image_size,
             'PE_EXPORT_DIRECTORY', 'Invalid export directory bounds')
    sections = []
    table = optional + optional_size
    span(table, count * 40)
    _require(table + count * 40 <= header_size, 'PE_HEADERS', 'Section headers exceed SizeOfHeaders')
    for index in range(count):
        base = table + index * 40
        virtual_size, va, raw_size, raw = struct.unpack_from('<IIII', data, base + 8)
        flags = number('<I', base + 36)
        mapped = max(virtual_size, raw_size)
        _require(mapped > 0 and va >= header_size and va + mapped <= image_size,
                 'PE_SECTION', 'Section image bounds')
        if raw_size:
            span(raw, raw_size)
            _require(raw >= header_size, 'PE_SECTION', 'Section overlaps headers')
        for old in sections:
            _require(va + mapped <= old[0] or old[0] + old[1] <= va,
                     'PE_SECTION_OVERLAP', 'Overlapping virtual sections')
            if raw_size and old[3]:
                _require(raw + raw_size <= old[2] or old[2] + old[3] <= raw,
                         'PE_SECTION_OVERLAP', 'Overlapping raw sections')
        sections.append((va, mapped, raw, raw_size, flags))

    def offset(rva, size):
        _require(_positive(rva) and type(size) is int and size >= 0 and rva + size <= image_size,
                 'PE_RVA', 'Invalid RVA span')
        matches = [(a, raw, rs) for a, mapped, raw, rs, flags in sections
                   if a <= rva and rva + size <= a + mapped]
        _require(len(matches) == 1, 'PE_RVA', 'RVA must belong to exactly one section')
        va, raw, raw_size = matches[0]
        _require(rva - va + size <= raw_size, 'PE_RVA', 'RVA has no complete backing bytes')
        return span(raw + rva - va, size)

    def string(rva):
        start = offset(rva, 1)
        end = start
        while end - start <= 512:
            offset(rva + end - start, 1)
            if data[end] == 0:
                try:
                    text = data[start:end].decode('ascii')
                except UnicodeDecodeError:
                    raise BindingRefused('PE_STRING', 'Non-ASCII export name') from None
                _require(bool(text), 'PE_STRING', 'Empty export name')
                return text
            end += 1
        raise BindingRefused('PE_STRING', 'Unterminated or oversized export name')

    directory = offset(export_rva, 40)
    string(number('<I', directory + 12))
    functions, names = number('<I', directory + 20), number('<I', directory + 24)
    _require(1 <= functions <= _MAX_EXPORTS and 1 <= names <= _MAX_EXPORTS,
             'PE_EXPORT_COUNT', 'Export count outside bound')
    function_table = offset(number('<I', directory + 28), functions * 4)
    name_table = offset(number('<I', directory + 32), names * 4)
    ordinal_table = offset(number('<I', directory + 36), names * 2)
    all_rvas = [number('<I', function_table + 4 * i) for i in range(functions)]
    found, seen_names, named_rvas = {}, set(), []
    for index in range(names):
        name = string(number('<I', name_table + 4 * index))
        _require(name not in seen_names, 'PE_DUPLICATE_NAME', 'Duplicate export name')
        seen_names.add(name)
        ordinal = number('<H', ordinal_table + 2 * index)
        _require(ordinal < functions, 'PE_ORDINAL', 'Export ordinal out of range')
        rva = all_rvas[ordinal]
        named_rvas.append(rva)
        if name in EXPORT_NAMES:
            _require(rva > 0 and not export_rva <= rva < export_rva + export_size,
                     'PE_FORWARDED', 'Null/forwarded export forbidden')
            code = [s for s in sections if s[0] <= rva < s[0] + s[1]]
            _require(len(code) == 1 and code[0][4] & 0x20000000 and code[0][4] & 0x20,
                     'PE_NON_CODE', 'Export must target an executable code section')
            offset(rva, 1)
            found[name] = rva
    _require(set(found) == set(EXPORT_NAMES), 'PE_EXPORT_MISSING', 'Required named export missing')
    for rva in found.values():
        _require(all_rvas.count(rva) == 1 and named_rvas.count(rva) == 1,
                 'EXPORT_ALIAS', 'Aliased function RVA forbidden')
    expected = dict(schema='plan15.mpfr-exports.r1', path=path, sha256=sha256,
                    size=image_size, exports={name: found[name] for name in EXPORT_NAMES})
    _validate_expected(expected)
    return expected


def read_expected_exports(path, expected_sha256):
    """Read pinned metadata once per configured source; return a defensive copy."""
    path = _path(path)
    _require(expected_sha256 == _PINNED_SHA256, 'SOURCE_SHA', 'Exact MPFR pin required')
    key = (path, expected_sha256)
    if key not in _EXPECTED_CACHE:
        try:
            with open(path, 'rb') as stream:
                before = os.fstat(stream.fileno())
                _require(512 <= before.st_size <= _MAX_FILE, 'PE_SIZE', 'Pinned file size outside bound')
                data = stream.read(_MAX_FILE + 1)
                after = os.fstat(stream.fileno())
            _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                     == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                     and len(data) == before.st_size, 'SOURCE_CHANGED', 'Pinned file changed during read')
        except OSError as exc:
            raise BindingRefused('SOURCE_READ', 'Pinned file read failed: ' + str(exc.winerror if hasattr(exc, 'winerror') else exc.errno)) from exc
        _require(hashlib.sha256(data).hexdigest() == expected_sha256, 'SOURCE_SHA', 'Pinned file bytes differ')
        parsed = _parse_pe(data, path, expected_sha256)
        _EXPECTED_CACHE[key] = (parsed['size'], tuple(parsed['exports'].items()))
    size, exports = _EXPECTED_CACHE[key]
    return dict(schema='plan15.mpfr-exports.r1', path=path, sha256=expected_sha256,
                size=size, exports=dict(exports))


def validate_receipt(receipt, expected):
    """Pure closed-schema validation; expected must come from the pinned parser."""
    _validate_expected(expected)
    _keys(receipt, ('schema', 'pid', 'creation_filetime', 'module', 'exports'), 'RECEIPT_SCHEMA')
    _require(receipt['schema'] == 'plan15.native-binding.r1', 'RECEIPT_SCHEMA', 'Wrong binding schema')
    _require(_positive(receipt['pid']) and receipt['pid'] <= 0xffffffff
             and _positive(receipt['creation_filetime']), 'PROCESS_IDENTITY', 'Exact process identity required')
    module = receipt['module']
    _keys(module, ('path', 'sha256', 'base', 'size'), 'MODULE_SCHEMA')
    _require(module['path'] == expected['path'] and module['sha256'] == expected['sha256']
             and type(module['size']) is int and module['size'] == expected['size'],
             'MODULE_SOURCE', 'Module path/hash/image size mismatch')
    _require(_positive(module['base']) and module['base'] + module['size'] <= (1 << 64),
             'MODULE_BASE', 'Invalid module address interval')
    _keys(receipt['exports'], EXPORT_NAMES, 'RECEIPT_EXPORTS')
    for name in EXPORT_NAMES:
        value = receipt['exports'][name]
        _keys(value, ('address', 'rva'), 'RECEIPT_EXPORT')
        _require(_positive(value['rva']) and value['rva'] == expected['exports'][name]
                 and _positive(value['address']) and value['address'] == module['base'] + value['rva'],
                 'EXPORT_BINDING', 'Export address/RVA mismatch: ' + name)


class _WindowsAPI:
    """Lazy query-only Win32 adapter. Handles never include mutation rights."""
    def __init__(self):
        _require(os.name == 'nt' and c.sizeof(c.c_void_p) == 8,
                 'PLATFORM', '64-bit Windows required; no fallback')
        self.k = c.WinDLL('kernel32', use_last_error=True)
        self.n = c.WinDLL('ntdll', use_last_error=True)
        specs = {
            'OpenProcess': (w.HANDLE, [w.DWORD, w.BOOL, w.DWORD]),
            'GetProcessId': (w.DWORD, [w.HANDLE]),
            'GetProcessTimes': (w.BOOL, [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4),
            'WaitForSingleObject': (w.DWORD, [w.HANDLE, w.DWORD]),
            'QueryInformationJobObject': (w.BOOL, [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]),
            'K32EnumProcessModulesEx': (w.BOOL, [w.HANDLE, c.POINTER(w.HMODULE), w.DWORD, c.POINTER(w.DWORD), w.DWORD]),
            'K32GetModuleFileNameExW': (w.DWORD, [w.HANDLE, w.HMODULE, w.LPWSTR, w.DWORD]),
            'K32GetModuleInformation': (w.BOOL, [w.HANDLE, w.HMODULE, c.c_void_p, w.DWORD]),
            'CloseHandle': (w.BOOL, [w.HANDLE]),
        }
        for name, (restype, argtypes) in specs.items():
            function = getattr(self.k, name)
            function.restype, function.argtypes = restype, argtypes
        self.n.NtQueryInformationProcess.restype = c.c_long
        self.n.NtQueryInformationProcess.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.ULONG, c.POINTER(w.ULONG)]

    def _ok(self, result, code):
        _require(bool(result), code, 'Windows query failed: ' + str(c.get_last_error()))

    def open(self, pid):
        handle = self.k.OpenProcess(_READ_RIGHTS, False, pid)
        self._ok(handle, 'PROCESS_OPEN')
        return handle

    def identity(self, handle):
        pid = int(self.k.GetProcessId(handle))
        self._ok(pid, 'HANDLE_PID')
        times = [w.FILETIME() for _ in range(4)]
        self._ok(self.k.GetProcessTimes(handle, *(c.byref(v) for v in times)), 'PROCESS_TIMES')
        creation = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        _require(_positive(creation), 'PROCESS_TIMES', 'Missing process creation time')
        # Zero-time state query only: never wait or poll.
        _require(self.k.WaitForSingleObject(handle, 0) == 258, 'PROCESS_DEAD', 'Process must still be alive')
        return pid, creation

    def parent_pid(self, handle):
        class Basic(c.Structure):
            _fields_ = [('exit_status', c.c_long), ('peb', c.c_void_p),
                        ('affinity', c.c_size_t), ('priority', c.c_long),
                        ('pid', c.c_size_t), ('parent', c.c_size_t)]
        info, returned = Basic(), w.ULONG()
        status = self.n.NtQueryInformationProcess(handle, 0, c.byref(info), c.sizeof(info), c.byref(returned))
        _require(status == 0 and returned.value == c.sizeof(info),
                 'PROCESS_ANCESTRY', 'Incomplete/failed live process ancestry query')
        return int(info.parent)

    def job_pids(self):
        # NULL queries the calling controller's current retained job. A fixed
        # bounded buffer refuses truncation rather than resizing/polling.
        size = 8 + _MAX_JOB_PIDS * c.sizeof(c.c_size_t)
        buffer, returned = c.create_string_buffer(size), w.DWORD()
        self._ok(self.k.QueryInformationJobObject(None, 3, buffer, size, c.byref(returned)), 'JOB_QUERY')
        assigned, listed = struct.unpack_from('<II', buffer.raw)
        _require(0 < assigned == listed <= _MAX_JOB_PIDS
                 and 8 + listed * c.sizeof(c.c_size_t) <= returned.value <= size,
                 'JOB_INCOMPLETE', 'Current-job PID snapshot is incomplete/unknown')
        pids = [int(c.c_size_t.from_buffer(buffer, 8 + i * c.sizeof(c.c_size_t)).value)
                for i in range(listed)]
        _require(len(set(pids)) == listed and all(_positive(p) and p <= 0xffffffff for p in pids),
                 'JOB_INCOMPLETE', 'Invalid/duplicate current-job PID snapshot')
        return sorted(pids)

    def module(self, handle, path):
        modules, needed = (w.HMODULE * _MAX_MODULES)(), w.DWORD()
        self._ok(self.k.K32EnumProcessModulesEx(handle, modules, c.sizeof(modules), c.byref(needed), 3),
                 'MODULE_ENUM')
        _require(0 < needed.value <= c.sizeof(modules) and needed.value % c.sizeof(w.HMODULE) == 0,
                 'MODULE_INCOMPLETE', 'Module enumeration incomplete/unknown')
        class Info(c.Structure):
            _fields_ = [('base', c.c_void_p), ('size', w.DWORD), ('entry', c.c_void_p)]
        found = []
        for index in range(needed.value // c.sizeof(w.HMODULE)):
            text = c.create_unicode_buffer(32768)
            length = self.k.K32GetModuleFileNameExW(handle, modules[index], text, len(text))
            _require(0 < length < len(text) - 1, 'MODULE_PATH', 'Unknown/truncated live module path')
            if text.value == path:
                info = Info()
                self._ok(self.k.K32GetModuleInformation(handle, modules[index], c.byref(info), c.sizeof(info)),
                         'MODULE_INFO')
                found.append(dict(path=text.value, base=int(info.base or 0), size=int(info.size)))
        _require(len(found) == 1, 'MODULE_NOT_UNIQUE', 'Exactly one pinned live module required')
        return found[0]

    def close(self, handle):
        self._ok(self.k.CloseHandle(handle), 'HANDLE_CLOSE')


def _api_factory():
    try:
        return _WindowsAPI()
    except (OSError, AttributeError) as exc:
        raise BindingRefused('WINDOWS_API', 'Required read-only Windows API unavailable') from exc


def _job_proof(api, required):
    pids = api.job_pids()
    _require(type(pids) is list and pids and len(pids) <= _MAX_JOB_PIDS
             and len(set(pids)) == len(pids) and all(_positive(p) for p in pids)
             and set(required).issubset(pids), 'JOB_MEMBERSHIP', 'Actual/launch/controller current-job membership unproved')
    return dict(schema='plan15.current-job-proof.r1', complete=True,
                caller_pid=os.getpid(), required_pids=sorted(set(required)),
                member_count=len(pids), member_pids=sorted(pids),
                authority='QueryInformationJobObject(NULL), calling controller current retained job')


def _checked_expected(expected):
    _validate_expected(expected)
    trusted = read_expected_exports(expected['path'], expected['sha256'])
    _require(expected == trusted, 'EXPECTED_TAMPER', 'Supplied metadata differs from pinned parsed bytes')
    return trusted


def _receipt(api, handle, pid, creation, expected, costs=None):
    _require(api.identity(handle) == (pid, creation), 'PROCESS_CHANGED', 'Retained process identity changed')
    if costs is not None:
        costs['module_query_calls'] += 1
    module = api.module(handle, expected['path'])
    _keys(module, ('path', 'base', 'size'), 'LIVE_MODULE_SCHEMA')
    _require(type(module['path']) is str and _positive(module['base'])
             and _positive(module['size']), 'LIVE_MODULE_VALUE', 'Invalid live module metadata')
    receipt = dict(schema='plan15.native-binding.r1', pid=pid, creation_filetime=creation,
                   module=dict(module, sha256=expected['sha256']),
                   exports={name: dict(address=module['base'] + rva, rva=rva)
                            for name, rva in expected['exports'].items()})
    validate_receipt(receipt, expected)
    _require(api.identity(handle) == (pid, creation), 'PROCESS_CHANGED', 'Process exited/changed during module query')
    return receipt


class BoundProcess:
    """Authenticated actual interpreter, holding only a read-only process handle."""
    def __init__(self, api, handle, pid, creation, owner_record):
        self.pid, self.creation_filetime = pid, creation
        self.owner_record = owner_record
        self._api, self._handle = api, handle
        self._cached = None

    def query(self, expected):
        started = time.perf_counter()
        costs = self.owner_record['costs']
        costs['query_calls'] += 1
        try:
            _require(self._handle is not None, 'PROCESS_CLOSED', 'Bound process is closed')
            _require(self.owner_record['query_failure'] is None,
                     'BINDING_FAILED', 'Earlier binding query failed; no retry/recapture')
            expected = _checked_expected(expected)
            proof = _job_proof(self._api, (os.getpid(), self.pid))
            receipt = _receipt(self._api, self._handle, self.pid, self.creation_filetime, expected, costs)
            if self._cached is not None:
                _require(receipt == self._cached, 'MODULE_LIFETIME_CHANGED', 'Previously bound source/module changed; no recapture')
                costs['cached_receipt_reuses'] += 1
            self._cached = receipt
            self.owner_record['last_query_job_proof'] = proof
            self.owner_record['query_failure'] = None
            return dict(receipt, module=dict(receipt['module']),
                        exports={n: dict(v) for n, v in receipt['exports'].items()})
        except BindingRefused as exc:
            if self.owner_record['query_failure'] is None:
                self.owner_record['query_failure'] = dict(code=exc.code, message=exc.message)
            raise
        finally:
            costs['query_seconds'] += time.perf_counter() - started

    def close(self):
        if self._handle is None:
            return
        started = time.perf_counter()
        try:
            self._api.close(self._handle)
            self._handle = None
            self.owner_record['closed'] = True
            self.owner_record['close_failure'] = None
        except BindingRefused as exc:
            self.owner_record['close_failure'] = dict(code=exc.code, message=exc.message)
            raise
        finally:
            self.owner_record['costs']['close_seconds'] += time.perf_counter() - started


def open_admitted(pid, launch_pid, launch_handle):
    """Authenticate at existing ready admission; close every partial own handle."""
    started = time.perf_counter()
    _require(_positive(pid) and pid <= 0xffffffff and _positive(launch_pid) and launch_pid <= 0xffffffff,
             'PROCESS_PID', 'Exact positive DWORD PIDs required')
    _require(isinstance(launch_handle, int) and type(launch_handle) is not bool
             and 0 < launch_handle < (1 << 64),
             'LAUNCH_HANDLE', 'Retained launch handle required')
    api, actual, launch = _api_factory(), None, None
    try:
        borrowed_identity = api.identity(launch_handle)
        _require(borrowed_identity[0] == launch_pid, 'LAUNCH_IDENTITY', 'Launch handle PID mismatch')
        launch = api.open(launch_pid)
        launch_identity = api.identity(launch)
        _require(launch_identity == borrowed_identity, 'LAUNCH_IDENTITY', 'Launch handle creation mismatch')
        actual = api.open(pid)
        actual_identity = api.identity(actual)
        _require(actual_identity[0] == pid, 'PROCESS_IDENTITY', 'Actual interpreter handle PID mismatch')
        parent = api.parent_pid(actual)
        relationship = 'same-process' if pid == launch_pid else 'live-immediate-child'
        _require((pid == launch_pid and actual_identity == launch_identity)
                 or (pid != launch_pid and parent == launch_pid and actual_identity[1] > launch_identity[1]),
                 'PROCESS_ANCESTRY', 'Actual interpreter is not the live launcher/immediate child')
        proof = _job_proof(api, (os.getpid(), launch_pid, pid))
        _require(api.identity(launch_handle) == launch_identity and api.identity(actual) == actual_identity,
                 'PROCESS_CHANGED', 'Process changed during admission')
        api.close(launch)
        launch = None
        record = dict(schema='plan15.native-admission.r1', pid=pid,
                      creation_filetime=actual_identity[1], launch_pid=launch_pid,
                      launch_creation_filetime=launch_identity[1], actual_parent_pid=parent,
                      relationship=relationship, read_only_actual_handle=True,
                      job_proof=proof, closed=False, close_failure=None, query_failure=None,
                      costs=dict(open_seconds=time.perf_counter() - started, query_seconds=0.0,
                                 query_calls=0, module_query_calls=0, cached_receipt_reuses=0,
                                 close_seconds=0.0))
        result = BoundProcess(api, actual, pid, actual_identity[1], record)
        actual = None
        return result
    finally:
        errors = []
        for handle in (launch, actual):
            if handle is not None:
                try:
                    api.close(handle)
                except BindingRefused as exc:
                    errors.append(exc.code)
        if errors:
            raise BindingRefused('ADMISSION_CLEANUP', ','.join(errors))


def capture_self(expected, bound_exports):
    """Observe already-loaded ctypes pointers; never resolve/load MPFR or H3."""
    expected = _checked_expected(expected)
    _keys(bound_exports, EXPORT_NAMES, 'BOUND_EXPORTS')
    api, handle = _api_factory(), None
    try:
        pid = os.getpid()
        handle = api.open(pid)
        actual_pid, creation = api.identity(handle)
        _require(actual_pid == pid, 'PROCESS_IDENTITY', 'Self handle does not name current process')
        receipt = _receipt(api, handle, pid, creation, expected)
        for name in EXPORT_NAMES:
            function = bound_exports[name]
            _require(isinstance(function, c._CFuncPtr), 'BOUND_POINTER', 'Actual ctypes function required: ' + name)
            address = c.cast(function, c.c_void_p).value
            _require(type(address) is int and address == receipt['exports'][name]['address'],
                     'BOUND_POINTER', 'Loaded function differs from pinned export: ' + name)
        return receipt
    finally:
        if handle is not None:
            api.close(handle)
