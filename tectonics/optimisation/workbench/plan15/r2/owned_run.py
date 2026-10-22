"""Plan15's supervised route, reusing the reviewed non-breakaway Windows job backend.

No dispatch on import. Queue tracking alone is a measurement, not an RSS/free-floor
guard. This supervisor samples itself plus every job member and stops only its retained
job handle. A shell exit does not complete a job while descendants remain active.
"""
import ctypes
from ctypes import wintypes
from hashlib import sha256
import importlib.util
from pathlib import Path
import time

import psutil

BACKEND = Path(__file__).resolve().parents[2]/'plan05/r9-launch-prep/owned_windows_job.py'
BACKEND_SHA256 = '132d53b54729c13193293ffa9b3eddd6c248f2c00e8f76aaa553f39a5f8146aa'
RSS_BYTES, FREE_BYTES = 12 << 30, 1 << 30


class JobPids(ctypes.Structure):
    _fields_ = [('assigned', wintypes.DWORD), ('listed', wintypes.DWORD),
                ('ids', ctypes.c_size_t * 256)]


def backend():
    if sha256(BACKEND.read_bytes()).hexdigest() != BACKEND_SHA256:
        raise ValueError('ownership backend source changed')
    spec = importlib.util.spec_from_file_location('plan15_owned_windows_job', BACKEND)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WindowsJob


def sample_job(job):
    buf = JobPids()
    if not job.k.QueryInformationJobObject(job.job, 3, ctypes.byref(buf), ctypes.sizeof(buf), None):
        raise OSError(ctypes.get_last_error(), 'owned job membership unavailable')
    if buf.assigned != buf.listed or buf.listed > 256:
        raise ValueError('incomplete job membership sample')
    rss = psutil.Process().memory_info().rss
    for index in range(buf.listed):
        try:
            rss += psutil.Process(int(buf.ids[index])).memory_info().rss
        except psutil.NoSuchProcess:
            continue
    return rss, psutil.virtual_memory().available


def supervise(job, *, sample=sample_job, clock=time.monotonic, sleep=time.sleep):
    """No arbitrary timing kill: the coordinator's 1.5x booking rule remains separate.

    Guard frequency is 250ms. The number is a sampled simultaneous RSS peak, not a
    continuous maximum or logical ledger reading. The exact runtime ledgers stay active.
    """
    began = clock()
    record = dict(errors=[], finality='UNRESOLVED', exit_code=None,
                  peak_tree_rss_bytes=0, available_low_bytes=None)
    try:
        while True:
            observation = job.snapshot()
            record['last_observation'] = observation
            record['exit_code'] = observation['exit_code']
            rss, free = sample(job)
            record['peak_tree_rss_bytes'] = max(record['peak_tree_rss_bytes'], rss)
            record['available_low_bytes'] = (free if record['available_low_bytes'] is None
                                             else min(record['available_low_bytes'], free))
            if rss > RSS_BYTES or free < FREE_BYTES:
                raise ValueError('runtime guard: tree RSS=%d available=%d' % (rss, free))
            if observation['job']['active'] == 0 and observation['exit_code'] is not None:
                record['finality'] = 'COMPLETE'
                break
            sleep(.25)
    except BaseException as failure:
        record['errors'].append(type(failure).__name__+': '+str(failure))
        try:
            record['termination'] = job.terminate_owned()
            end = clock()+10
            while True:
                observation = job.snapshot()
                record['last_observation'] = observation
                record['exit_code'] = observation['exit_code']
                if observation['job']['active'] == 0:
                    record['finality'] = 'COMPLETE'
                    break
                if clock() >= end:
                    raise ValueError('owned cleanup still has active descendants')
                sleep(.25)
        except BaseException as cleanup:
            record['errors'].append('cleanup: '+type(cleanup).__name__+': '+str(cleanup))
    record['wall_seconds'] = clock()-began
    return record


def execute(argv, cwd, env, stdout, stderr):
    job = backend()()
    try:
        try:
            job.start([str(value) for value in argv], cwd, env, stdout, stderr)
        except BaseException:
            job.terminate_owned()
            raise
        record = supervise(job)
        record['ownership'] = dict(job.identity)
        return record
    finally:
        job.close()
