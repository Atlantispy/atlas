"""Launch-bound Windows ownership; no ancestry or wall-clock ordering decisions.

The supervisor alone holds the job handle. Workloads cannot break away. A PID
returned by the job is opened and its membership checked on that SAME handle
before reading RSS. Termination addresses the job, never a discovered PID.
Only ordinary CreateProcess descendants are supported (Python/subprocess workers).
Out-of-process brokers such as WMI/services are outside this execution contract.
"""
import ctypes
from ctypes import wintypes as W
import os
import subprocess
import time
import uuid


JOB_QUERY = 4
KILL_ON_CLOSE = 0x2000
BREAKAWAY = 0x800 | 0x1000
QUERY_PROCESS = 0x1000 | 0x100000  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class BASIC_LIMITS(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', W.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', W.DWORD),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', W.DWORD), ('SchedulingClass', W.DWORD)]


class EXTENDED_LIMITS(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', BASIC_LIMITS), ('IoInfo', IO_COUNTERS),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


class MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [('cb', W.DWORD), ('PageFaultCount', W.DWORD)] + [
        (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
        'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
        'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]


def kernel():
    if os.name != 'nt':
        raise OSError('Windows job ownership is required; no ancestry fallback')
    dll = ctypes.WinDLL('kernel32', use_last_error=True)
    definitions = {
        'CreateJobObjectW': ([ctypes.c_void_p, W.LPCWSTR], W.HANDLE),
        'OpenJobObjectW': ([W.DWORD, W.BOOL, W.LPCWSTR], W.HANDLE),
        'SetInformationJobObject': ([W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD], W.BOOL),
        'QueryInformationJobObject': ([W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.c_void_p], W.BOOL),
        'AssignProcessToJobObject': ([W.HANDLE, W.HANDLE], W.BOOL),
        'IsProcessInJob': ([W.HANDLE, W.HANDLE, ctypes.POINTER(W.BOOL)], W.BOOL),
        'TerminateJobObject': ([W.HANDLE, W.UINT], W.BOOL),
        'OpenProcess': ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        'CloseHandle': ([W.HANDLE], W.BOOL),
        'ResumeThread': ([W.HANDLE], W.DWORD),
        'WaitForSingleObject': ([W.HANDLE, W.DWORD], W.DWORD),
        'GetExitCodeProcess': ([W.HANDLE, ctypes.POINTER(W.DWORD)], W.BOOL),
        'GetProcessTimes': ([W.HANDLE, ctypes.POINTER(W.FILETIME), ctypes.POINTER(W.FILETIME),
                             ctypes.POINTER(W.FILETIME), ctypes.POINTER(W.FILETIME)], W.BOOL),
        'K32GetProcessMemoryInfo': ([W.HANDLE, ctypes.c_void_p, W.DWORD], W.BOOL),
        'TerminateProcess': ([W.HANDLE, W.UINT], W.BOOL),
    }
    for name, (args, result) in definitions.items():
        function = getattr(dll, name)
        function.argtypes, function.restype = args, result
    return dll


def checked(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def belongs(api, handle, job):
    result = W.BOOL()
    checked(api.IsProcessInJob(handle, job, ctypes.byref(result)))
    return bool(result.value)


class ProcessHandle:
    def __init__(self, api, handle, pid):
        self.api, self.handle, self.pid = api, handle, pid

    def poll(self):
        wait = self.api.WaitForSingleObject(self.handle, 0)
        if wait == 258:
            return None
        if wait != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = W.DWORD()
        checked(self.api.GetExitCodeProcess(self.handle, ctypes.byref(code)))
        return code.value

    def identity(self):
        values = [W.FILETIME() for _ in range(4)]
        checked(self.api.GetProcessTimes(self.handle, *(ctypes.byref(value) for value in values)))
        stamp = (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
        # Display/binding only: no comparison of different processes' birth order.
        return dict(pid=self.pid, created_ticks=stamp)

    def wait(self, seconds):
        result = self.api.WaitForSingleObject(self.handle, max(0, int(seconds*1000)))
        if result not in (0, 258):
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0

    def rss(self):
        counters = MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        checked(self.api.K32GetProcessMemoryInfo(self.handle, ctypes.byref(counters), counters.cb))
        return counters.WorkingSetSize

    def close(self):
        if self.handle:
            checked(self.api.CloseHandle(self.handle))
            self.handle = None


class WindowsJob:
    def __init__(self):
        self.api = kernel()
        self.name = 'Local\\AtlasContinuation-' + uuid.uuid4().hex
        ctypes.set_last_error(0)
        self.handle = checked(self.api.CreateJobObjectW(None, self.name))
        if ctypes.get_last_error() == 183:
            self.close()
            raise RuntimeError('Exclusive fresh workload job required')
        try:
            limits = EXTENDED_LIMITS()
            limits.BasicLimitInformation.LimitFlags = KILL_ON_CLOSE
            checked(self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            self.verify_limits()
        except BaseException:
            self.close()
            raise

    def verify_limits(self):
        limits = EXTENDED_LIMITS()
        checked(self.api.QueryInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits), None))
        flags = limits.BasicLimitInformation.LimitFlags
        if not flags & KILL_ON_CLOSE or flags & BREAKAWAY:
            raise RuntimeError('Workload job must kill on close and forbid breakaway')

    def launch(self, command, env, cwd):
        import _winapi
        # No inherited handles: in particular the workload must never keep the
        # supervisor's kill-on-close job handle alive after supervisor death.
        flags = 0x4 | 0x8000000 | 0x400  # SUSPENDED | NO_WINDOW | UNICODE_ENVIRONMENT
        hp, ht, pid, _ = _winapi.CreateProcess(str(command[0]), subprocess.list2cmdline(command),
            None, None, False, flags, env, str(cwd), subprocess.STARTUPINFO())
        process = ProcessHandle(self.api, hp, pid)
        try:
            checked(self.api.AssignProcessToJobObject(self.handle, hp))
            if not belongs(self.api, hp, self.handle):
                raise RuntimeError('Suspended workload assignment could not be verified')
            if self.api.ResumeThread(ht) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            return process
        except BaseException:
            # This exact handle was returned by OUR CreateProcess while suspended.
            self.api.TerminateProcess(hp, 2)
            self.api.WaitForSingleObject(hp, 2000)
            process.close()
            raise
        finally:
            checked(self.api.CloseHandle(ht))

    def pids(self):
        capacity = 32
        for _ in range(16):
            class PID_LIST(ctypes.Structure):
                _fields_ = [('assigned', W.DWORD), ('listed', W.DWORD),
                            ('pids', ctypes.c_size_t * capacity)]
            data = PID_LIST()
            ok = self.api.QueryInformationJobObject(self.handle, 3, ctypes.byref(data), ctypes.sizeof(data), None)
            if ok and data.assigned <= data.listed:
                return list(data.pids[:data.listed])
            if not ok and ctypes.get_last_error() != 234:
                raise ctypes.WinError(ctypes.get_last_error())
            capacity = max(capacity * 2, data.assigned + 8)
        raise RuntimeError('Cannot obtain a complete bounded workload job census')

    def member(self, pid):
        handle = self.api.OpenProcess(QUERY_PROCESS, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # Process vanished before opening it.
                return None
            raise ctypes.WinError(error)
        process = ProcessHandle(self.api, handle, pid)
        try:
            # The PID may now name another process. Read nothing until the exact
            # opened handle proves membership in OUR job.
            if not belongs(self.api, handle, self.handle) or process.poll() is not None:
                process.close()
                return None
            return process
        except BaseException:
            process.close()
            raise

    def sample(self, parent_pid):
        total, parent, live = 0, 0, []
        for pid in self.pids():
            process = self.member(pid)
            if process is None:
                continue
            try:
                try:
                    memory = process.rss()
                    identity = process.identity()
                except OSError:
                    if process.poll() is not None:
                        continue
                    raise
                total += memory
                parent += memory if pid == parent_pid else 0
                live.append(dict(identity, rss_bytes=memory))
            finally:
                process.close()
        return dict(parent_rss_bytes=parent, process_tree_rss_bytes=total, live_processes=live)

    def stop(self):
        checked(self.api.TerminateJobObject(self.handle, 2))
        deadline = time.monotonic() + 2.0
        remaining = self.pids()
        while remaining and time.monotonic() < deadline:
            time.sleep(.02)
            remaining = self.pids()
        return dict(remaining=[dict(pid=pid) for pid in remaining], action_errors=[])

    def close(self):
        if self.handle:
            checked(self.api.CloseHandle(self.handle))
            self.handle = None


def verify_current_membership(job_name):
    """A short-lived QUERY-only handle; never retained in a workload process."""
    api = kernel()
    job = checked(api.OpenJobObjectW(JOB_QUERY, False, job_name))
    process = None
    try:
        process = checked(api.OpenProcess(QUERY_PROCESS, False, os.getpid()))
        if not belongs(api, process, job):
            raise RuntimeError('This process was not launched inside the continuation job')
        limits = EXTENDED_LIMITS()
        checked(api.QueryInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits), None))
        flags = limits.BasicLimitInformation.LimitFlags
        if not flags & KILL_ON_CLOSE or flags & BREAKAWAY:
            raise RuntimeError('Continuation job ownership policy differs')
        return ProcessHandle(api, process, os.getpid()).identity()
    finally:
        if process:
            api.CloseHandle(process)
        api.CloseHandle(job)
