"""Step 8 checkpoint-only memory probe for guarded representative runs.

Records, at named checkpoints only (never inside scientific loops):
- the complete run-budget ledger (reserved, peak, categories, category peaks);
- the retained scope's purposes and totals;
- process memory: rss, private, peak working set, pagefile and peak pagefile;
- system available memory;
- the Windows job's exact whole-tree peak commit (PeakJobMemoryUsed) and the
  largest single process peak (PeakProcessMemoryUsed), read through a short
  query-only handle exactly as the guardian's membership check does.
It takes no budget reservation of its own: one more ledger category would only
fall into the 63-category 'other' bucket and perturb what it measures.
"""
import ctypes
import gc
import importlib.util
import json
import os
import time
from pathlib import Path

import psutil


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class JobPeak:
    """Query-only reader of the launching continuation job's peak counters."""

    def __init__(self, guard_dir, env_name):
        self.job_name = None
        raw = os.environ.get(env_name)
        if raw is not None:
            self.job_name = json.loads(raw)['job_name']
        self.jobs = _load(Path(guard_dir)/'windows_workload_job.py', '_step8_probe_windows_job')

    def read(self):
        if self.job_name is None:
            return None
        api = self.jobs.kernel()
        job = self.jobs.checked(api.OpenJobObjectW(self.jobs.JOB_QUERY, False, self.job_name))
        try:
            limits = self.jobs.EXTENDED_LIMITS()
            self.jobs.checked(api.QueryInformationJobObject(job, 9, ctypes.byref(limits),
                                                            ctypes.sizeof(limits), None))
            return {'peak_job_commit_bytes': int(limits.PeakJobMemoryUsed),
                    'peak_process_commit_bytes': int(limits.PeakProcessMemoryUsed)}
        finally:
            api.CloseHandle(job)


class Probe:
    def __init__(self, *, budget, scope, guard=None, job=None, started=None):
        self.budget, self.scope, self.guard, self.job = budget, scope, guard, job
        self.process = psutil.Process()
        self.started = time.perf_counter() if started is None else started
        self.rows = []

    def stage(self, name, **sizes):
        info = self.process.memory_info()
        ledger = self.budget.statistics()
        stats = None if self.scope is None else self.scope.stats()
        row = {'stage': name, 'elapsed_seconds': time.perf_counter()-self.started,
               'process': {'rss_bytes': info.rss, 'private_bytes': getattr(info, 'private', None),
                           'peak_wset_bytes': getattr(info, 'peak_wset', None),
                           'pagefile_bytes': getattr(info, 'pagefile', None),
                           'peak_pagefile_bytes': getattr(info, 'peak_pagefile', None)},
               'available_bytes': psutil.virtual_memory().available,
               'ledger': {'reserved_bytes': ledger['reserved_bytes'], 'peak_reserved_bytes': ledger['peak_reserved_bytes'],
                          'categories': ledger['categories'], 'category_peaks': ledger['category_peaks'],
                          'category_count': len(ledger['categories'])},
               'gc_counts': gc.get_count(), 'sizes': sizes}
        if stats is not None:
            row['retained'] = {'retained_bytes': stats.retained_bytes, 'peak_retained_bytes': stats.peak_retained_bytes,
                               'pinned_bytes': stats.pinned_bytes, 'evictable_bytes': stats.evictable_bytes,
                               'non_cache_owned_bytes': stats.non_cache_owned_bytes,
                               'purpose_bytes': dict(stats.purpose_bytes), 'purpose_peak_bytes': dict(stats.purpose_peak_bytes)}
        if self.job is not None:
            row['job'] = self.job.read()
        previous = self.rows[-1] if self.rows else None
        if previous is not None:
            row['delta'] = {'seconds': row['elapsed_seconds']-previous['elapsed_seconds'],
                'ledger_peak_rose': row['ledger']['peak_reserved_bytes'] > previous['ledger']['peak_reserved_bytes'],
                'reserved_change_bytes': row['ledger']['reserved_bytes']-previous['ledger']['reserved_bytes'],
                'retained_change_bytes': (None if stats is None else
                                          row['retained']['retained_bytes']-previous['retained']['retained_bytes']),
                'private_change_bytes': ((row['process']['private_bytes'] or 0)-(previous['process']['private_bytes'] or 0))}
        self.rows.append(row)
        if self.guard is not None:
            self.guard.phase(name)
        print(json.dumps({'stage': name, 'seconds': round(row['elapsed_seconds'], 3),
                          'rss': info.rss, 'reserved': ledger['reserved_bytes'],
                          'retained': None if stats is None else stats.retained_bytes,
                          'job_peak': None if row.get('job') is None else row['job']['peak_job_commit_bytes']}),
              flush=True)
        return row
