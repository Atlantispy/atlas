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
import sys
import time


SCHEMA = 'atlas.dev-stage-timing.events.v1'
FILENAME = 'dev-stage-timing.jsonl'
MAX_LINE_BYTES = 16 << 10
MAX_FILE_BYTES = 256 << 20
MAX_NAMES = 256
WORKSPACE_BYTES = 256 << 10
_CURRENT = ContextVar('atlas_dev_stage_timing', default=None)


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
def collect(guard, directory, *, enabled, record, metadata=None, source_sha256=None):
    """Establish optional timing without changing any guard or scientific call.

    The selected runner and driver emit explicit completion checkpoints.
    Recording failures remain diagnostic. Release the optional budget on exit.
    """
    if not enabled:
        yield None
        return
    try:
        if source_sha256 is None:
            source_sha256 = sha256(Path(__file__).read_bytes()).hexdigest()
        metadata = dict(metadata or {}, measured_scope='run_prepared_restart',
                        mode='completed_subsection_checkpoints_only', source_sha256=source_sha256)
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


def start_stacks(folder, mode):
    """Start the workload's optional sampling thread."""
    import collections, threading

    def top(pair):
        return {'samples': sum(pair[0].values()), 'stacks': pair[0].most_common(50), 'top3': pair[1].most_common(50)}

    def run():
        try:
            folder.mkdir(exist_ok=True)
            out = str(folder/('stacks-%s-%d.json' % (mode, os.getpid())))
            me, t0 = threading.get_ident(), time.monotonic()
            done, minute, pair, last = {}, 0, (collections.Counter(), collections.Counter()), t0
            while True:
                time.sleep(0.2)
                now = time.monotonic()
                if int((now-t0)//60) != minute:
                    done[str(minute*60)] = top(pair)
                    minute, pair = int((now-t0)//60), (collections.Counter(), collections.Counter())
                for ident, frame in sys._current_frames().items():
                    stack = []
                    while frame is not None and ident != me and len(stack) < 40:
                        code = frame.f_code
                        stack.append('%s:%s:%d' % (os.path.basename(code.co_filename), code.co_name, frame.f_lineno))
                        frame = frame.f_back
                    if stack:
                        pair[0][' < '.join(stack)] += 1
                        pair[1][' < '.join(s.rsplit(':', 1)[0] for s in stack[:3])] += 1
                frame = None
                if now-last >= 30:
                    last = now
                    try:
                        with open(out+'.tmp', 'w') as stream:
                            json.dump({**done, str(minute*60): top(pair)}, stream)
                        os.replace(out+'.tmp', out)
                    except OSError:  # an open handle on the file makes the replace fail on Windows; next try in 30 s
                        pass
        except Exception:  # a profiler failure never stops the step (rule 18)
            pass

    try:
        threading.Thread(target=run, name='profile-stack-sampler', daemon=True).start()
    except Exception:  # G-3: a thread that cannot start never stops the step either
        pass


def profile_selection(value):
    """Parse a launcher selection; carry only its requested instruments."""
    if value == 'off':
        return frozenset()
    instruments = value.split(',')
    if not all(name in ('stages', 'stacks', 'tree') for name in instruments):
        raise ValueError('run profile must be off or a list of stages, stacks, tree')
    return frozenset(instruments)


def profile_words(selection):
    child = sorted(selection)
    return ['--run-profile', ','.join(child)] if child else []


def profile_tool(selection, path):
    """Linked settings: 'tree' needs the sampling profiler executable, and the executable needs 'tree'."""
    if ('tree' in selection) != (path is not None):
        raise ValueError('--run-profile tree and --profile-tool are given together or not at all')
    if path is not None and not Path(path).is_file():
        raise ValueError(f'--profile-tool is not a file: {path}')
    return path


def profile_command(selection, guarded_argv, *, raw_path, executable):
    if 'tree' not in selection:
        return guarded_argv
    return [str(executable), 'record', '--subprocesses', '--rate', '100', '--format', 'raw',
            '--output', str(raw_path), '--', *guarded_argv]


def report(kind, path, *args, reader=None, **options):
    """Read a named offline input using the selected existing report contract."""
    if kind in ('stages', 'journal'):
        return reader(path, *args, **options)
    from atlas_shared.execution import profile_reports

    view = {
        'active': profile_reports.active,
        'check-share': profile_reports.check_share,
        'callers': profile_reports.callers,
        'rows': profile_reports.rows,
    }[kind]
    return view(path, *args, **options)


def stacks_enabled(selection):
    return 'stacks' in selection
