"""Explicit opt-in Windows/Linux MAGEMin process connection; no installer.

SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import base64
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import tomllib

from i01_gibbs_provider import Point, PhasePoint, check, finite


class MAGEMinG25:
    component_ids = ('SiO2', 'Al2O3', 'CaO', 'MgO', 'FeO', 'K2O', 'Na2O',
                     'TiO2', 'O', 'Cr2O3', 'H2O')
    molar_mass_kg = tuple(v/1000 for v in
        (60.08, 101.96, 56.08, 40.30, 71.85, 94.2, 61.98, 79.88, 16., 151.99, 18.015))

    def __init__(self, julia, project, depot, *, temperature_bounds_k,
                 pressure_bounds_pa, startup_timeout_s=180., point_timeout_s=30.):
        """Bounds are caller-reviewed numerical domain, not G25 calibration.

        Environment must already contain the exact pinned package. Nothing is
        downloaded/installed. One native worker is owned until close/context exit.
        """
        self.bounds = tuple(tuple(finite(x, 'domain', positive=True) for x in b)
                            for b in (pressure_bounds_pa, temperature_bounds_k))
        if any(len(b) != 2 or b[0] >= b[1] for b in self.bounds):
            raise ValueError('ordered positive P/T support required')
        self.point_timeout = finite(point_timeout_s, 'point timeout', positive=True)
        self.messages, self.log = queue.Queue(), deque(maxlen=8)
        self._lock = threading.Lock()
        self.last_metadata = None
        project, depot = Path(project).resolve(), Path(depot).resolve()
        worker = Path(__file__).with_suffix('.jl')
        manifest = project/'Manifest.toml'
        worker_hash = hashlib.sha256(worker.read_bytes()).hexdigest()
        manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
        env = dict(os.environ, JULIA_DEPOT_PATH=str(depot), JULIA_NUM_THREADS='1',
                   OPENBLAS_NUM_THREADS='1', JULIA_PKG_OFFLINE='true')
        cmd = [str(Path(julia).resolve()), '--startup-file=no', '--history-file=no',
               '--threads=1', '--project='+str(project), str(worker)]
        self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
            env=env, cwd=project, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.reader = threading.Thread(target=self._read, name='atlas-g25-output', daemon=True)
        self.reader.start()
        try:
            meta = self._response(time.perf_counter()+finite(startup_timeout_s, 'startup timeout', positive=True))
            if (meta.get('ready') is not True or meta.get('wrapper_version') != '2.3.7'
                    or meta.get('worker_sha256') != worker_hash
                    or meta.get('manifest_sha256') != manifest_hash):
                raise ValueError('unmatched pinned worker/environment identity')
            # Exact transport, dependency lock, component basis and bounds, never
            # a user-provided display label. Cache is process-local only.
            self.identity = hashlib.sha256(json.dumps(
                (meta, self.bounds, self.component_ids, self.molar_mass_kg),
                sort_keys=True).encode()).hexdigest()
            self.metadata = meta
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                if len(line) > 2_000_000:
                    self.messages.put(ValueError('oversized native response'))
                    break
                if line.startswith('ATLAS_G25\t'):
                    self.messages.put(line.split('\t', 1)[1].strip())
                else:
                    self.log.append(line[-2000:].strip())
        finally:
            self.messages.put(EOFError('native worker stopped: '+' | '.join(self.log)))

    def _response(self, deadline, cancel=None):
        while True:
            check(cancel, deadline)
            try:
                value = self.messages.get(timeout=min(.1, max(.001, deadline-time.perf_counter())))
            except queue.Empty:
                continue
            if isinstance(value, Exception):
                raise value
            return tomllib.loads(base64.b64decode(value, validate=True).decode('utf-8'))

    def validate(self, p, t, bulk):
        if (self.process.poll() is not None or len(bulk) != 11
                or not self.bounds[0][0] <= p <= self.bounds[0][1]
                or not self.bounds[1][0] <= t <= self.bounds[1][1]):
            raise ValueError('G25 worker unavailable or request outside declared support')
        if any(bulk[i] < 1e-4 for i in (0, 1, 3, 4)):
            raise ValueError('G25 wrapper would raise a core component; refusing changed inventory')

    def solve(self, p, t, bulk, *, cancel=None, deadline=None):
        self.validate(p, t, bulk)
        check(cancel, deadline)
        until = time.perf_counter()+self.point_timeout
        if deadline is not None:
            until = min(until, deadline)
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('one request at a time per prepared G25 worker')
        try:
            payload = f'p = {p!r}\nt = {t!r}\nb = {list(bulk)!r}\n'.encode()
            self.process.stdin.write(base64.b64encode(payload).decode()+'\n')
            self.process.stdin.flush()
            r = self._response(until, cancel)
            if r.get('ok') is not True:
                raise ValueError('MAGEMin refused: '+str(r.get('error', 'unknown failure')))
            if (r.get('database') != 'ig' or r.get('dataset') != 'tc_ds636'
                    or not r.get('native_version', '').startswith('2.0.4 ')):
                raise ValueError('different native model/version returned')
            # Returning requested SI P/T after verifying the round-trip avoids
            # fabricating identity drift from Celsius/kbar floating roundoff.
            if abs(r['p']-p) > 4*max(math.ulp(p), 1e-12) or abs(r['t']-t) > 1e-10:
                raise ValueError('native P/T mismatch')
            self.last_metadata = {k: r[k] for k in
                ('database', 'dataset', 'native_version', 'bulk_residual', 'solve_ms')}
            return Point(self.identity, p, t, tuple(r['bulk']), tuple(r['mu']), r['g'],
                tuple(PhasePoint(v['key'], tuple(v['amounts']), tuple(v['coordinates']))
                      for v in r['phases']))
        except BaseException:
            # Never leave a timed-out calculation behind or consume its output
            # as the next request. Failed sessions are explicit, not restarted.
            self.close()
            raise
        finally:
            self._lock.release()

    def close(self):
        p = self.process
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)
        for stream in (p.stdin, p.stdout):
            if stream and not stream.closed:
                stream.close()
        if self.reader.is_alive():
            self.reader.join(timeout=2)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
