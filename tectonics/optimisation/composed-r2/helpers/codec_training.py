"""Offline, hash-bound Zstandard training under an owned Windows Job.

No live store is opened. Input, temporary output, child-process commit and
returned dictionary ownership all retain explicit bounds and budget charges.
"""
from concurrent.futures import CancelledError
from contextlib import contextmanager
import ctypes
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import time


NATIVE_LIMIT = 128 << 20
PYTHON_ALLOWANCE = 16 << 20
MAX_CORPUS = 1 << 20
MAX_SAMPLE = 64 << 10
MAX_SAMPLES = 256
MAX_DICTIONARY = 64 << 10
MAX_EXECUTABLE = 64 << 20
JOB_HELPER_SHA256 = '56f66b8826b148a31b85d490c75766422eb210fdfb35c665c449d2e73788f0b4'
JOB_HELPER = Path(__file__).parent.parent / 'probes/structure-census-r3/guard/windows_workload_job.py'
SCHEMA = 'atlas.trained-dictionary.v1'
_SHA = re.compile(r'[0-9a-f]{64}\Z')


class TrainingRefused(RuntimeError):
    def __init__(self, message, *, metrics=None):
        super().__init__(message)
        self.metrics = metrics


class _TrainingMemory:
    """A failed traceback keeps its temporary Python workspace funded."""
    def __init__(self, budget):
        self.reservation = budget.reserve(NATIVE_LIMIT + PYTHON_ALLOWANCE,
                                          category='codec-dictionary-training')
        self.reservation.__enter__()

    def __enter__(self):
        return self

    def close(self):
        reservation, self.reservation = self.reservation, None
        if reservation is not None:
            reservation.__exit__(None, None, None)

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.close()
        # On failure the caller frame/exception retains this owner until the
        # traceback (and its buffers) is discarded, including separately held
        # tracebacks. Releasing merely because stack unwinding began is unsafe.
        else:
            value._wp10_training_memory_owner = self

    def __del__(self):
        self.close()


def _require(condition, message):
    if not condition:
        raise TrainingRefused(message)


def _cancel(token):
    if token is not None and token.is_set():
        raise CancelledError('dictionary training cancelled')


def _job_module():
    raw = JOB_HELPER.read_bytes()
    _require(sha256(raw).hexdigest() == JOB_HELPER_SHA256, 'Windows ownership helper identity changed')
    name = '_wp10_bound_windows_job'
    spec = importlib.util.spec_from_loader(name, loader=None, origin=str(JOB_HELPER))
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(JOB_HELPER), 'exec'), module.__dict__)
    return module


class TrainingJob:
    """The established suspended-launch owner with stricter instance limits."""
    def __init__(self):
        self.module = _job_module()
        self.job = self.module.WindowsJob()
        try:
            limits = self.module.EXTENDED_LIMITS()
            limits.BasicLimitInformation.LimitFlags = self.module.KILL_ON_CLOSE | 0x100 | 0x200
            limits.ProcessMemoryLimit = limits.JobMemoryLimit = NATIVE_LIMIT
            self.module.checked(self.job.api.SetInformationJobObject(self.job.handle, 9,
                ctypes.byref(limits), ctypes.sizeof(limits)))
            self.verify_limits()
        except BaseException:
            self.job.close()
            raise

    def _query(self):
        limits = self.module.EXTENDED_LIMITS()
        self.module.checked(self.job.api.QueryInformationJobObject(self.job.handle, 9,
            ctypes.byref(limits), ctypes.sizeof(limits), None))
        return limits

    def verify_limits(self):
        value = self._query()
        flags = value.BasicLimitInformation.LimitFlags
        _require(flags & (self.module.KILL_ON_CLOSE | 0x100 | 0x200) ==
                 (self.module.KILL_ON_CLOSE | 0x100 | 0x200) and not flags & self.module.BREAKAWAY
                 and value.ProcessMemoryLimit == value.JobMemoryLimit == NATIVE_LIMIT,
                 'hard training process/job limits could not be verified')
        return dict(process_memory_limit_bytes=int(value.ProcessMemoryLimit),
                    job_memory_limit_bytes=int(value.JobMemoryLimit), kill_on_close=True,
                    breakaway=False, suspended_launch_owned=True)

    def launch(self, command, env, cwd):
        self.verify_limits()
        return self.job.launch(command, env, cwd)

    def metrics(self):
        value = self._query()
        return dict(peak_job_memory_used_bytes=int(value.PeakJobMemoryUsed),
                    peak_process_memory_used_bytes=int(value.PeakProcessMemoryUsed))

    def stop(self):
        return self.job.stop()

    def close(self):
        self.job.close()


@contextmanager
def _executable_lock(path, expected):
    """Deny replacement/writes while the authenticated executable is launched."""
    _require(os.name == 'nt', 'Windows owned-job training is required')
    import msvcrt
    from ctypes import wintypes
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    function = api.CreateFileW
    function.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    function.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    # GENERIC_READ; FILE_SHARE_READ only; OPEN_EXISTING. Loader reads remain possible.
    handle = function(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        api.CloseHandle(handle)
        raise
    with os.fdopen(descriptor, 'rb') as stream:
        _require(0 < os.fstat(stream.fileno()).st_size <= MAX_EXECUTABLE, 'trainer executable size is unbounded')
        digest = sha256()
        while block := stream.read(65536):
            digest.update(block)
        _require(digest.hexdigest() == expected, 'trainer executable identity differs')
        yield


class TrainedDictionary:
    """Retains its shared-budget reservation until the dictionary owner closes."""
    def __init__(self, data, metadata, reservation):
        self._data, self._metadata, self._reservation = data, metadata, reservation

    @property
    def data(self):
        _require(self._reservation is not None, 'dictionary owner is closed')
        return self._data

    @property
    def metadata(self):
        _require(self._reservation is not None, 'dictionary owner is closed')
        return self._metadata

    def close(self):
        reservation, self._reservation = self._reservation, None
        self._data = self._metadata = None
        if reservation is not None:
            reservation.__exit__(None, None, None)

    def __enter__(self):
        _require(self._reservation is not None, 'dictionary owner is closed')
        return self

    def __exit__(self, *_args):
        self.close()

    def __del__(self):
        self.close()


def train_dictionary(executable, *, expected_executable_sha256, samples,
                     array_class, dtype, shuffle, source_identity, budget, work_root,
                     capacity=16384, timeout_seconds=30, cancel=None,
                     transform_for_training=None, _job_factory=None, _lock_factory=None):
    """Train once; return an owned artifact only after exit/output verification.

    `samples` must already be a bounded sequence of immutable raw chunks. The
    optional transform receives (raw, dtype, shuffle) under the reservation.
    `source_identity` is the caller's authenticated corpus/source SHA-256.
    Test-only factories permit deterministic job failure fixtures, never a
    platform fallback. Production always uses the existing Windows Job owner.
    """
    _require(type(samples) in (tuple, list) and 0 < len(samples) <= MAX_SAMPLES,
             'bounded explicit training sample sequence required')
    _require(all(type(raw) is bytes and 0 < len(raw) <= MAX_SAMPLE for raw in samples)
             and sum(map(len, samples)) <= MAX_CORPUS, 'training corpus exceeds fixed bounds')
    _require(type(expected_executable_sha256) is str and _SHA.fullmatch(expected_executable_sha256),
             'expected trainer executable SHA-256 required')
    _require(type(source_identity) is str and _SHA.fullmatch(source_identity), 'authenticated source SHA-256 required')
    _require(type(array_class) is str and 0 < len(array_class) <= 128
             and type(dtype) is str and 0 < len(dtype) <= 32 and shuffle in ('none', 'byte', 'bit'),
             'explicit class/dtype/shuffle binding required')
    _require(type(capacity) is int and 256 <= capacity <= MAX_DICTIONARY, 'dictionary capacity exceeds fixed bounds')
    _require(type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 30,
             'training timeout must be positive and at most 30 seconds')
    _cancel(cancel)
    executable, work_root = Path(executable).resolve(), Path(work_root).resolve()
    _require(executable.is_file() and work_root.is_dir(), 'existing executable and private work root required')
    owner = None
    with _TrainingMemory(budget) as training_memory:
        # Keep the owner in this frame for separately retained failed tracebacks.
        _require(training_memory.reservation is not None, 'training reservation is unavailable')
        transformed = []
        for raw in samples:
            _cancel(cancel)
            value = raw if transform_for_training is None else transform_for_training(raw, dtype, shuffle)
            _require(type(value) is bytes and 0 < len(value) <= MAX_SAMPLE,
                     'training transform exceeds one bounded immutable chunk')
            transformed.append(value)
        total = sum(map(len, transformed))
        _require(total <= MAX_CORPUS, 'transformed training corpus exceeds fixed bound')
        source_hashes = [sha256(raw).hexdigest() for raw in samples]
        transformed_hashes = [sha256(raw).hexdigest() for raw in transformed]
        lock = _executable_lock if _lock_factory is None else _lock_factory
        job_factory = TrainingJob if _job_factory is None else _job_factory
        with lock(executable, expected_executable_sha256), tempfile.TemporaryDirectory(
                prefix='wp10-training-', dir=work_root) as private:
            private = Path(private).resolve()
            _require(private.parent == work_root and not private.is_symlink(), 'private scratch escaped work root')
            input_path, output_path = private / 'samples.bin', private / 'dictionary.bin'
            with input_path.open('xb') as stream:
                stream.write(struct.pack('<4sIII', b'WPT1', len(transformed), capacity, total))
                stream.write(struct.pack('<' + 'I'*len(transformed), *map(len, transformed)))
                for raw in transformed:
                    stream.write(raw)
            job, process, metrics = None, None, {}
            started = time.monotonic()
            try:
                _cancel(cancel)
                job = job_factory()
                limits = job.verify_limits()
                _require(limits == dict(process_memory_limit_bytes=NATIVE_LIMIT,
                    job_memory_limit_bytes=NATIVE_LIMIT, kill_on_close=True,
                    breakaway=False, suspended_launch_owned=True), 'hard training limits differ')
                _cancel(cancel)
                process = job.launch([str(executable), str(input_path), str(output_path)],
                                     dict(os.environ), private)
                deadline = started + timeout_seconds
                while process.poll() is None:
                    _cancel(cancel)
                    remaining = deadline - time.monotonic()
                    _require(remaining > 0, 'dictionary trainer exceeded timeout')
                    process.wait(min(.25, remaining))
                code = process.poll()
                metrics = dict(job.metrics(), elapsed_seconds=time.monotonic()-started, exit_code=code)
                _require(code == 0, f'dictionary trainer failed with exit code {code}')
                _cancel(cancel)
                _require(output_path.is_file() and not output_path.is_symlink(), 'trainer produced no dictionary')
                with output_path.open('rb') as stream:
                    data = stream.read(capacity+1)
                _require(8 <= len(data) <= capacity and data[:4] == b'\x37\xa4\x30\xec'
                         and int.from_bytes(data[4:8], 'little') != 0,
                         'trainer output is oversized or lacks a trained dictionary identity')
                metadata = dict(schema=SCHEMA, sha256=sha256(data).hexdigest(), array_class=array_class,
                    dtype=dtype, shuffle=shuffle, source_identity=source_identity,
                    training_sample_sha256=source_hashes, transformed_sample_sha256=transformed_hashes,
                    trainer_executable_sha256=expected_executable_sha256,
                    job_helper_sha256=JOB_HELPER_SHA256, training_sample_count=len(samples),
                    training_raw_bytes=sum(map(len, samples)), training_transformed_bytes=total,
                    capacity_bytes=capacity, dictionary_bytes=len(data), limits=limits,
                    metrics=dict(metrics, dictionary_physical_bytes=output_path.stat().st_size),
                    status='TRAINED_NOT_ADOPTED', production_enabled=False)
                encoded_metadata = json.dumps(metadata, sort_keys=True, allow_nan=False).encode()
                reservation = budget.reserve(65536 + 2*len(data) + 4*len(encoded_metadata),
                                             category='codec-trained-dictionary-owner')
                reservation.__enter__()
                owner = TrainedDictionary(data, metadata, reservation)
            except BaseException as error:
                if owner is not None:
                    owner.close()
                if job is not None:
                    stopped = job.stop()
                    if process is not None:
                        _require(process.wait(2.) and process.poll() is not None,
                                 'trainer termination did not join owned process')
                    _require(not stopped.get('remaining') and not stopped.get('action_errors'),
                             'trainer job termination is incomplete')
                    metrics = dict(job.metrics(), elapsed_seconds=time.monotonic()-started)
                if isinstance(error, TrainingRefused):
                    error.metrics = metrics
                raise
            finally:
                if process is not None:
                    process.close()
                if job is not None:
                    job.close()
        return owner
