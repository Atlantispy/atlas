"""Opt-in WP19 timing at existing stage/sub-stage checkpoints only.

The measured scope is run_prepared_restart, excluding guardian startup and the
outer finalisation. Wall/process-CPU clocks describe this workload process;
worker CPU and whole-tree memory remain the guardian's sampled evidence.
Events stream to a bounded exclusive file. Diagnostic errors disable recording
without replacing a scientific result, cancellation or exception. No polling
thread, query hook, guard.check wrapper or workload payload capture is used.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
import os
from pathlib import Path
import time


SCHEMA = 'atlas.dev-stage-timing.events.v1'
ENV = 'ATLAS_DEV_STAGE_TIMING'
FILENAME = 'dev-stage-timing.jsonl'
MAX_LINE_BYTES = 16 << 10
MAX_FILE_BYTES = 256 << 20
MAX_NAMES = 256
WORKSPACE_BYTES = 256 << 10
_CURRENT = ContextVar('atlas_dev_stage_timing', default=None)


def enabled(flag=False, environ=None):
    """Explicit flag or exact 1; reject ambiguous environment values early."""
    if type(flag) is not bool:
        raise ValueError('dev timing flag must be boolean')
    value = (os.environ if environ is None else environ).get(ENV, '')
    if value not in ('', '0', '1'):
        raise ValueError(ENV+' must be unset, 0 or 1')
    return flag or value == '1'


class Recorder:
    def __init__(self, directory, record, *, metadata=None, budget=lambda: None,
                 clock=time.perf_counter_ns, cpu=time.process_time_ns,
                 memory=None, max_bytes=MAX_FILE_BYTES):
        if type(max_bytes) is not int or not MAX_LINE_BYTES <= max_bytes <= MAX_FILE_BYTES:
            raise ValueError('bounded diagnostic file size required')
        self.record, self.budget = record, budget
        self.clock, self.cpu = clock, cpu
        self.memory = memory
        self.process = None
        self.start_wall, self.start_cpu = clock(), cpu()
        self.previous_wall = self.previous_cpu = 0
        self.seq = self.bytes = 0
        self.names = set()
        self.reservation = None
        self.active, self.max_bytes = True, max_bytes
        self.path = Path(directory)/FILENAME
        self.stream = self.path.open('xb', buffering=0)
        self.record['dev_stage_timing'] = dict(enabled=True, status='RECORDING',
            path=str(self.path), schema=SCHEMA, measured_scope='run_prepared_restart',
            mode='completed_subsection_checkpoints_only', cpu_scope='parent_process', file_cap_bytes=max_bytes,
            memory_scope='checkpoint observations; guardian owns sampled whole-tree evidence')
        try:
            metadata = {} if metadata is None else metadata
            if (type(metadata) is not dict or len(metadata) > 16 or
                    any(type(k) is not str or len(k) > 64 or
                        type(v) not in (str, int, bool, type(None)) or
                        (isinstance(v, str) and len(v) > 256) for k, v in metadata.items())):
                raise ValueError('bounded scalar timing metadata required')
            self._emit('session_start', stamp=(0, 0), schema=SCHEMA, pid=os.getpid(),
                       phase='startup', metadata=metadata)
        except Exception:
            self.stream.close()
            raise

    def _disable(self, error):
        self.active = False
        self.record['dev_stage_timing'].update(status='INCOMPLETE',
            error=type(error).__name__+': '+str(error)[:256], events=self.seq, bytes=self.bytes)
        try:
            self.stream.close()
        except Exception:
            pass
        self._release()

    def _release(self):
        reservation, self.reservation = self.reservation, None
        if reservation is not None:
            try:
                reservation.__exit__(None, None, None)
            except Exception as error:
                self.record['dev_stage_timing'].update(status='INCOMPLETE',
                    release_error=type(error).__name__+': '+str(error)[:256])

    def _charge(self):
        if self.reservation is not None:
            return
        budget = self.budget()
        if budget is None:
            return  # Before the shared budget is created: bounded startup only.
        lease = budget.try_reserve(WORKSPACE_BYTES, category='dev-stage-timing')
        if not lease.__enter__():
            lease.__exit__(None, None, None)
            raise MemoryError('optional timing workspace does not fit the shared budget')
        self.reservation = lease

    def _stamp(self):
        wall, cpu = self.clock()-self.start_wall, self.cpu()-self.start_cpu
        if wall < self.previous_wall or cpu < self.previous_cpu:
            raise ValueError('timing clocks moved backwards')
        return wall, cpu

    def _memory(self):
        if self.memory is not None:
            return self.memory()
        if self.process is None:
            import psutil
            self.process = psutil.Process()
        info = self.process.memory_info()
        budget = self.budget()
        return dict(parent_rss_bytes=info.rss,
            parent_private_bytes=getattr(info, 'private', None),
            parent_os_peak_working_set_bytes=getattr(info, 'peak_wset', None),
            parent_os_peak_pagefile_bytes=getattr(info, 'peak_pagefile', None),
            logical_reserved_bytes=None if budget is None else budget.reserved_bytes)

    def _emit(self, event, *, stamp=None, **fields):
        if not self.active:
            return None
        try:
            self._charge()
            wall, cpu = self._stamp() if stamp is None else stamp
            row = dict(event=event, seq=self.seq, wall_ns=wall, cpu_ns=cpu, **fields)
            try:
                memory = self._memory()
                if memory is not None:
                    if (type(memory) is not dict or len(memory) > 5 or
                            any(v is not None and (type(v) is not int or v < 0) for v in memory.values())):
                        raise ValueError('invalid memory observation')
                    row['memory'] = memory
            except Exception as error:
                self.record['dev_stage_timing']['memory_error'] = type(error).__name__+': '+str(error)[:256]
            raw = (json.dumps(row, ensure_ascii=True, allow_nan=False, separators=(',', ':'))+'\n').encode()
            if len(raw) > MAX_LINE_BYTES or self.bytes+len(raw) > self.max_bytes:
                raise ValueError('bounded timing event/file limit reached')
            if self.stream.write(raw) != len(raw):
                raise OSError('partial timing event write')
            self.bytes += len(raw)
            self.seq += 1
            self.previous_wall, self.previous_cpu = wall, cpu
            return wall, cpu
        except Exception as error:
            self._disable(error)
            return None

    def _name(self, name):
        if (type(name) is not str or not name or len(name) > 128 or
                name in ('timing-finalisation', 'incomplete-subsection')):
            raise ValueError('bounded nonempty diagnostic name required')
        if name not in self.names:
            if len(self.names) >= MAX_NAMES-1:  # Reserve one aggregate for session_end.
                raise ValueError('diagnostic stage limit reached')
            self.names.add(name)
        return name

    def checkpoint(self, name):
        if not self.active:
            return
        try:
            name = self._name(name)
            self._emit('checkpoint', name=name)
        except Exception as error:
            self._disable(error)

    def close(self, workload_status):
        if self.active:
            self._emit('session_end', phase='timing-finalisation' if workload_status == 'ok' else 'incomplete-subsection',
                       workload_status=workload_status, closed=True)
            if self.active:
                self.record['dev_stage_timing'].update(status='CLOSED',
                    events=self.seq, bytes=self.bytes, workload_status=workload_status)
        self.active = False
        try:
            self.stream.close()
        except Exception as error:
            self.record['dev_stage_timing'].update(status='INCOMPLETE', error=str(error)[:256])
        self._release()


def checkpoint(name):
    """Record one completed subsection; never called inside a calculation loop."""
    recorder = _CURRENT.get()
    if recorder is not None:
        recorder.checkpoint(name)


@contextmanager
def collect(guard, directory, *, enabled, record, metadata=None):
    """Establish optional timing without changing any guard or scientific call.

    The selected runner and driver emit explicit completion checkpoints.
    Recording failures remain diagnostic. Release the optional budget on exit.
    """
    if not enabled:
        yield None
        return
    try:
        metadata = dict(metadata or {}, measured_scope='run_prepared_restart',
                        mode='completed_subsection_checkpoints_only',
                        source_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
        recorder = Recorder(directory, record, metadata=metadata, budget=lambda: guard.budget)
    except Exception as error:
        record['dev_stage_timing'] = dict(enabled=True, status='INCOMPLETE',
            error=type(error).__name__+': '+str(error)[:256])
        yield None
        return
    token = _CURRENT.set(recorder)
    status = 'ok'
    try:
        yield recorder
    except BaseException:
        status = 'error'
        raise
    finally:
        _CURRENT.reset(token)
        recorder.close(status)
