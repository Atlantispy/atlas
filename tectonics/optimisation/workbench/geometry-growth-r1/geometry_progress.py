"""Bounded per-query geometry progress recorder (proposed runner option, OFF by default).

Install with `install(G, path)` where G is the composed integration_differential_geometry
module (it must carry the progress_hooks transform). Only SLOW queries are written:
  start      once a query has used `slow_seconds` of process CPU (default 30 s): kind,
             support id, logical cell, endpoint / wall axis-end / interface constraint,
             paired cell, literal count;
  heartbeat  every `heartbeat_seconds` (default 120 s) while it runs. Endpoint queries
             add the latest subdivision snapshot: leaves, queue length, lower/upper/
             witness (floats, display only) and the unmet stopping condition (width /
             no positive witness while upper > 0). Wall and interface queries give CPU
             only (their refinement lives in the moments module, which is not hooked);
  end        the issued record's leaves, met, work units and bounds (and, for an
             interface, the Taylor attempt's leaves and outcome).
Why a watchdog thread: the measured stall is in interface queries, which have no
step hook, so a timer is the only way to see one while it runs. The thread only reads
the current query's ids and the snapshot the geometry thread last stored (a tuple of
existing immutable values); it never calls into the geometry.
Bounds: one JSONL file, at most `max_bytes` (default 32 MiB); past that only the
final summary line is written. Each line <= 4 KiB. Timing is the process CPU clock.
It never raises into the geometry (a recording error disables it and is counted);
no reservation, work charge or result is touched. Not a WP19 checkpoint. A worker
process records only if the runner installs a recorder in that worker.
"""
import json
import os
import threading
import time


class _Query:
    __slots__ = ('id', 'kind', 'support', 'cell', 'where', 'other', 'literals', 't0', 'last', 'steps', 'snap',
                 'announced')

    def __init__(self, id, kind, support, cell, where, other, literals, t0):
        self.id, self.kind, self.support, self.cell = id, kind, support, cell
        self.where, self.other, self.literals = where, other, literals
        self.t0 = self.last = t0
        self.steps, self.snap, self.announced = 0, None, False


class GeometryProgress:
    def __init__(self, path, *, slow_seconds=30.0, heartbeat_seconds=120.0, max_bytes=32 << 20,
                 snapshot_stride=64, poll_seconds=None):
        self.path = path
        self.slow, self.heartbeat, self.max_bytes = float(slow_seconds), float(heartbeat_seconds), int(max_bytes)
        self.stride = int(snapshot_stride)
        self.poll = float(poll_seconds) if poll_seconds else max(0.5, min(self.slow, self.heartbeat) / 4)
        self.stream = open(path, 'x', encoding='utf8', newline='\n')
        self.bytes = 0
        self.current = None
        self.counts = dict(queries=0, slow=0, heartbeats=0, dropped_lines=0, errors=0)
        self.disabled = False
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._watch, name='geometry-progress', daemon=True)
        self.thread.start()

    # -- writing (always under self.lock) --
    def _write(self, row):
        if self.disabled:
            return
        try:
            line = json.dumps(row, separators=(',', ':'), default=str)[:4095] + '\n'
            if self.bytes + len(line) > self.max_bytes:
                self.counts['dropped_lines'] += 1
                return
            self.stream.write(line)
            self.stream.flush()
            self.bytes += len(line)
        except Exception:
            self.counts['errors'] += 1
            self.disabled = True

    def _announce(self, q, now):
        q.announced = True
        q.last = now
        self.counts['slow'] += 1
        self._write(dict(event='start', query=q.id, kind=q.kind, support=q.support, cell=q.cell,
                         where=q.where, other=q.other, literals=q.literals, cpu_s=round(now - q.t0, 3)))

    def _close_current(self, now):
        q = self.current
        if q is not None and q.announced:
            self._write(dict(event='end-unrecorded', query=q.id, cpu_s=round(now - q.t0, 3)))
        self.current = None

    # -- watchdog thread --
    def _watch(self):
        while not self.stopping.wait(self.poll):
            try:
                with self.lock:
                    q = self.current
                    if q is None:
                        continue
                    now = time.process_time()
                    if not q.announced:
                        if now - q.t0 >= self.slow:
                            self._announce(q, now)
                        continue
                    if now - q.last < self.heartbeat:
                        continue
                    q.last = now
                    self.counts['heartbeats'] += 1
                    row = dict(event='heartbeat', query=q.id, cpu_s=round(now - q.t0, 3))
                    snap = q.snap
                    if snap is not None:
                        leaves, queued, low, high, witness, width, positive_witness = snap
                        unmet = []
                        if high - low > width:
                            unmet.append('width')
                        if positive_witness and not witness and high > 0:
                            unmet.append('no positive witness while upper > 0')
                        row.update(leaves=leaves, queued=queued, lower=float(low), upper=float(high),
                                   witness=float(witness), unmet=unmet)
                    self._write(row)
            except Exception:
                self.counts['errors'] += 1

    # -- hooks called by the geometry (progress_hooks transform) --
    def start(self, kind, support_id, cell, where, *, other=None, literals=None):
        now = time.process_time()
        with self.lock:
            self._close_current(now)
            self.counts['queries'] += 1
            self.current = _Query(self.counts['queries'], kind, support_id[:16], cell[:16], where,
                                  other[:16] if other else None, literals, now)

    def step(self, leaves, queued, low, high, witness, width, positive_witness):
        q = self.current
        if q is None:
            return
        q.steps += 1
        if q.steps % self.stride == 0:
            q.snap = (leaves, queued, low, high, witness, width, positive_witness)   # one atomic store

    def end(self, record):
        now = time.process_time()
        with self.lock:
            q = self.current
            if q is None:
                return
            if not q.announced and now - q.t0 >= self.slow:
                self._announce(q, now)
            if q.announced:
                row = dict(event='end', query=q.id, cpu_s=round(now - q.t0, 3),
                           leaves=record.get('leaves'), met=record.get('met'), work_units=record.get('work_units'))
                for key in ('lower_m3', 'upper_m3', 'inward_volume_bounds_m3', 'outward_volume_bounds_m3'):
                    if key in record:
                        row[key] = record[key]
                moments = record.get('moving_interface_moments')
                if isinstance(moments, dict):
                    row.update(attempt_leaves=moments.get('attempt_leaves'), attempt_met=moments.get('attempt_met'))
                self._write(row)
            self.current = None

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=10)
        with self.lock:
            self._close_current(time.process_time())
            try:
                self.stream.write(json.dumps(dict(event='summary', **self.counts, bytes=self.bytes)) + '\n')
                self.stream.close()
            except Exception:
                pass


def install(geometry_module, path, **options):
    if not hasattr(geometry_module, '_GEOMETRY_PROGRESS'):
        raise RuntimeError('composed geometry lacks the progress_hooks transform')
    if geometry_module._GEOMETRY_PROGRESS is not None:
        raise RuntimeError('a progress recorder is already installed')
    if os.path.exists(path):
        raise FileExistsError(path)
    recorder = GeometryProgress(path, **options)
    geometry_module._GEOMETRY_PROGRESS = recorder
    return recorder


def uninstall(geometry_module):
    recorder = geometry_module._GEOMETRY_PROGRESS
    geometry_module._GEOMETRY_PROGRESS = None
    if recorder is not None:
        recorder.close()
    return recorder
