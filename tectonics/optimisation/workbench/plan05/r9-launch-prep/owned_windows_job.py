"""Small Windows-only ownership boundary. Importing this file starts nothing.

Create suspended -> assign to retained, non-breakaway job -> verify -> resume.
No OpenProcess/PID-based termination. See LAUNCHER-NOTE.md for API sources.
"""
import ctypes as c
from ctypes import wintypes as w
import os
import subprocess


class BasicLimits(c.Structure):
    _fields_ = [('process_time', c.c_longlong), ('job_time', c.c_longlong),
                ('flags', w.DWORD), ('min_ws', c.c_size_t), ('max_ws', c.c_size_t),
                ('active_limit', w.DWORD), ('affinity', c.c_size_t),
                ('priority', w.DWORD), ('scheduling', w.DWORD)]


class IOCounters(c.Structure):
    _fields_ = [(name, c.c_ulonglong) for name in
                ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]


class ExtendedLimits(c.Structure):
    _fields_ = [('basic', BasicLimits), ('io', IOCounters),
                ('process_memory', c.c_size_t), ('job_memory', c.c_size_t),
                ('peak_process_memory', c.c_size_t), ('peak_job_memory', c.c_size_t)]


class Accounting(c.Structure):
    _fields_ = [('user', c.c_longlong), ('kernel', c.c_longlong),
                ('period_user', c.c_longlong), ('period_kernel', c.c_longlong),
                ('faults', w.DWORD), ('total', w.DWORD), ('active', w.DWORD),
                ('terminated', w.DWORD)]


class StartupInfo(c.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR),
                ('title', w.LPWSTR), ('x', w.DWORD), ('y', w.DWORD),
                ('xsize', w.DWORD), ('ysize', w.DWORD), ('xchars', w.DWORD),
                ('ychars', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
                ('show', w.WORD), ('reserved_size', w.WORD), ('reserved_bytes', c.c_void_p),
                ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]


class StartupInfoEx(c.Structure):
    _fields_ = [('startup', StartupInfo), ('attributes', c.c_void_p)]


class ProcessInfo(c.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE),
                ('pid', w.DWORD), ('tid', w.DWORD)]


def error(api):
    return OSError(c.get_last_error(), api + ' failed')


class WindowsJob:
    def __init__(self):
        if os.name != 'nt' or c.sizeof(c.c_void_p) != 8:
            raise RuntimeError('Requires 64-bit Windows; no containment fallback')
        self.k = c.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateJobObjectW': (w.HANDLE, [c.c_void_p, w.LPCWSTR]),
            'SetInformationJobObject': (w.BOOL, [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]),
            'QueryInformationJobObject': (w.BOOL, [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]),
            'AssignProcessToJobObject': (w.BOOL, [w.HANDLE, w.HANDLE]),
            'IsProcessInJob': (w.BOOL, [w.HANDLE, w.HANDLE, c.POINTER(w.BOOL)]),
            'TerminateJobObject': (w.BOOL, [w.HANDLE, w.UINT]),
            'TerminateProcess': (w.BOOL, [w.HANDLE, w.UINT]),
            'GetCurrentProcess': (w.HANDLE, []),
            'DuplicateHandle': (w.BOOL, [w.HANDLE, w.HANDLE, w.HANDLE, c.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD]),
            'CloseHandle': (w.BOOL, [w.HANDLE]),
            'InitializeProcThreadAttributeList': (w.BOOL, [c.c_void_p, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)]),
            'UpdateProcThreadAttribute': (w.BOOL, [c.c_void_p, w.DWORD, c.c_size_t, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p]),
            'DeleteProcThreadAttributeList': (None, [c.c_void_p]),
            'CreateProcessW': (w.BOOL, [w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL,
                                      w.DWORD, c.c_void_p, w.LPCWSTR, c.c_void_p, c.POINTER(ProcessInfo)]),
            'ResumeThread': (w.DWORD, [w.HANDLE]),
            'WaitForSingleObject': (w.DWORD, [w.HANDLE, w.DWORD]),
            'GetExitCodeProcess': (w.BOOL, [w.HANDLE, c.POINTER(w.DWORD)]),
            'GetProcessTimes': (w.BOOL, [w.HANDLE, c.POINTER(w.FILETIME), c.POINTER(w.FILETIME),
                                       c.POINTER(w.FILETIME), c.POINTER(w.FILETIME)]),
        }
        for name, (restype, argtypes) in signatures.items():
            function = getattr(self.k, name)
            function.restype, function.argtypes = restype, argtypes
        self.job = self.k.CreateJobObjectW(None, None)  # Unnamed, non-inheritable.
        self.pi = ProcessInfo()
        self.assigned = self.resumed = False
        self.identity = {'ownership': 'retained-unnamed-job', 'assigned_before_resume': False}
        if not self.job:
            raise error('CreateJobObjectW')
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway flags.
        if not self.k.SetInformationJobObject(self.job, 9, c.byref(limits), c.sizeof(limits)):
            failure = error('SetInformationJobObject')
            self.k.CloseHandle(self.job)
            self.job = None
            raise failure

    def accounting(self):
        info, returned = Accounting(), w.DWORD()
        if not self.k.QueryInformationJobObject(self.job, 1, c.byref(info), c.sizeof(info), c.byref(returned)):
            raise error('QueryInformationJobObject')
        if returned.value != c.sizeof(info):
            raise RuntimeError('Incomplete job accounting response')
        return {'active': int(info.active), 'total': int(info.total), 'terminated': int(info.terminated)}

    def start(self, argv, cwd, env, stdout, stderr):
        """Any failure leaves handles on this object for terminate_owned()/close()."""
        import msvcrt
        if self.pi.process or self.assigned or self.resumed:
            raise RuntimeError('Single-dispatch ownership object already used')
        if not argv or not os.path.isabs(argv[0]) or any('\0' in arg for arg in argv):
            raise ValueError('Absolute executable and NUL-free argv required')
        if any('\0' in key + value or '=' in key for key, value in env.items()):
            raise ValueError('Invalid environment entry')
        inherited, attributes, initialised = [], None, False
        try:
            with open(os.devnull, 'rb') as stdin:
                current = self.k.GetCurrentProcess()
                for stream in (stdin, stdout, stderr):
                    duplicate = w.HANDLE()
                    source = w.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
                    if not self.k.DuplicateHandle(current, source, current, c.byref(duplicate), 0, True, 2):
                        raise error('DuplicateHandle')
                    inherited.append(duplicate.value)
                size = c.c_size_t()
                self.k.InitializeProcThreadAttributeList(None, 1, 0, c.byref(size))
                if c.get_last_error() != 122 or not size.value:  # Expected sizing refusal.
                    raise error('InitializeProcThreadAttributeList sizing')
                attributes = c.create_string_buffer(size.value)
                if not self.k.InitializeProcThreadAttributeList(attributes, 1, 0, c.byref(size)):
                    raise error('InitializeProcThreadAttributeList')
                initialised = True
                handle_list = (w.HANDLE * len(inherited))(*inherited)
                if not self.k.UpdateProcThreadAttribute(attributes, 0, 0x00020002,
                                                       handle_list, c.sizeof(handle_list), None, None):
                    raise error('UpdateProcThreadAttribute HANDLE_LIST')
                startup = StartupInfoEx()
                startup.startup.cb = c.sizeof(startup)
                startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
                startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = inherited
                startup.attributes = c.cast(attributes, c.c_void_p)
                command = c.create_unicode_buffer(subprocess.list2cmdline(argv))
                environment = c.create_unicode_buffer('\0'.join(
                    key + '=' + value for key, value in sorted(env.items(), key=lambda pair: pair[0].upper())) + '\0\0')
                flags = 0x00000004 | 0x08000000 | 0x00080000 | 0x00000400
                # CREATE_SUSPENDED | CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT
                if not self.k.CreateProcessW(argv[0], command, None, None, True, flags,
                                            environment, str(cwd), c.byref(startup), c.byref(self.pi)):
                    raise error('CreateProcessW')
                self.identity.update(pid=int(self.pi.pid), thread_id=int(self.pi.tid), suspended=True)
                times = [w.FILETIME() for _ in range(4)]
                if not self.k.GetProcessTimes(self.pi.process, *(c.byref(value) for value in times)):
                    raise error('GetProcessTimes')
                self.identity['creation_filetime'] = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
                if not self.k.AssignProcessToJobObject(self.job, self.pi.process):
                    raise error('AssignProcessToJobObject')
                self.assigned = True
                inside = w.BOOL()
                if not self.k.IsProcessInJob(self.pi.process, self.job, c.byref(inside)) or not inside.value:
                    raise error('IsProcessInJob')
                initial = self.accounting()
                if initial['active'] != 1 or initial['total'] != 1:
                    raise RuntimeError('Unexpected membership before resume: ' + repr(initial))
                self.identity.update(assigned_before_resume=True, initial_accounting=initial)
                previous = self.k.ResumeThread(self.pi.thread)
                if previous != 1:
                    raise RuntimeError('ResumeThread expected suspended count 1; received ' + str(previous))
                self.resumed = True
                self.identity['suspended'] = False
        finally:
            if initialised:
                self.k.DeleteProcThreadAttributeList(attributes)
            close_errors = []
            for handle in inherited:
                if not self.k.CloseHandle(handle):
                    close_errors.append(str(error('CloseHandle inherited stream')))
            if close_errors:
                raise RuntimeError('; '.join(close_errors))

    def exit_code(self):
        if not self.pi.process:
            return None
        state = self.k.WaitForSingleObject(self.pi.process, 0)
        if state == 258:
            return None
        if state != 0:
            raise error('WaitForSingleObject')
        code = w.DWORD()
        if not self.k.GetExitCodeProcess(self.pi.process, c.byref(code)):
            raise error('GetExitCodeProcess')
        return int(code.value)

    def snapshot(self):
        return {'exit_code': self.exit_code(), 'job': self.accounting()}

    def terminate_owned(self):
        if self.assigned:
            if not self.k.TerminateJobObject(self.job, 0xE0000001):
                raise error('TerminateJobObject')
            return 'retained-job-handle'
        if self.pi.process:
            # This handle came directly from our still-suspended CreateProcessW.
            if self.exit_code() is None and not self.k.TerminateProcess(self.pi.process, 0xE0000002):
                raise error('TerminateProcess own suspended child')
            return 'retained-suspended-process-handle'
        return 'no-process-created'

    def close(self):
        failures = []
        for name, handle in (('thread', self.pi.thread), ('process', self.pi.process), ('job', self.job)):
            if handle and not self.k.CloseHandle(handle):
                failures.append(str(error('CloseHandle ' + name)))
        self.pi = ProcessInfo()
        self.job = None
        if failures:
            raise RuntimeError('; '.join(failures))
