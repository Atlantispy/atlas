"""Passive resource supplement for a NEW successor of the existing job guard.

No launch, cancellation, hooks, writes or cleanup authority lives here. Replace
the successor guard's job.sample(...) with sample_job(job, parent_pid, cohort),
then feed that sample to ResourceSummary.observe at its existing 0.25 s tick.
Keep its RSS/free-RAM decisions, handle ownership and stop/finally paths intact.

Memory and CPU are read from the SAME exact job-member handle. The memory/time
calls replace the existing RSS/identity calls; no second process-tree census is
needed. Parent OS peaks are lifetime values, not phase-local peaks. Summed
process peaks are deliberately absent: they need not be simultaneous. Sampling
cannot measure processes that start and exit wholly between guardian ticks.
"""
import ctypes
import math

import windows_workload_job as WJ


def _ticks(value):
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


def _key(row):
    return row['pid'], row['created_ticks']


def _process_resources(process):
    counters = WJ.MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    WJ.checked(process.api.K32GetProcessMemoryInfo(
        process.handle, ctypes.byref(counters), counters.cb))
    times = [WJ.W.FILETIME() for _ in range(4)]
    WJ.checked(process.api.GetProcessTimes(
        process.handle, *(ctypes.byref(value) for value in times)))
    return dict(pid=process.pid, created_ticks=_ticks(times[0]),
        rss_bytes=int(counters.WorkingSetSize),
        private_bytes=int(counters.PrivateUsage),
        os_peak_working_set_bytes=int(counters.PeakWorkingSetSize),
        os_peak_pagefile_bytes=int(counters.PeakPagefileUsage),
        cpu_kernel_seconds=_ticks(times[2])/10_000_000,
        cpu_user_seconds=_ticks(times[3])/10_000_000)


def sample_job(job, parent_pid, launch_cohort=None):
    """Preserve the existing guardian's three sample keys and ownership rule.

    ``job.member`` opens one exact handle and verifies its membership BEFORE
    this function reads anything. All handles close, including error/exit races.
    ``launch_cohort`` is the existing guard's retained startup handle identities;
    without it the worker count is unknown, never guessed from policy settings.
    """
    live = []
    for pid in job.pids():
        process = job.member(pid)
        if process is None:
            continue
        try:
            try:
                row = _process_resources(process)
            except OSError:
                if process.poll() is not None:
                    continue
                raise
            live.append(row)
        finally:
            process.close()
    parents = [row for row in live if row['pid'] == parent_pid]
    cohort = None if launch_cohort is None else {_key(row) for row in launch_cohort}
    return dict(
        parent_rss_bytes=sum(row['rss_bytes'] for row in parents),
        process_tree_rss_bytes=sum(row['rss_bytes'] for row in live),
        live_processes=live,
        process_tree_private_bytes=sum(row['private_bytes'] for row in live),
        process_count=len(live),
        nonparent_process_count=len(live)-len(parents),
        worker_process_count=None if cohort is None else
            sum(_key(row) not in cohort for row in live),
        largest_observed_process_os_peak_working_set_bytes=max(
            (row['os_peak_working_set_bytes'] for row in live), default=None),
        largest_observed_process_os_peak_pagefile_bytes=max(
            (row['os_peak_pagefile_bytes'] for row in live), default=None),
        parent_os_peak_working_set_bytes=max(
            (row['os_peak_working_set_bytes'] for row in parents), default=None),
        parent_os_peak_pagefile_bytes=max(
            (row['os_peak_pagefile_bytes'] for row in parents), default=None))


class ResourceSummary:
    """Bounded, constant-history aggregates; no per-cell or per-tick history.

    CPU deltas cover identities observed on two consecutive samples only, so
    new/exited process tails are not silently invented. Percent uses one CPU
    core as 100% and can exceed 100 with parallel work. Phase durations are
    sampled transition estimates; use the driver's exact phase markers for
    outer stage durations. The output explains these limits explicitly.
    """
    def __init__(self, max_phases=128):
        if type(max_phases) is not int or not 1 <= max_phases <= 1024:
            raise ValueError('Bounded positive max_phases required')
        self.max_phases = max_phases
        self.phases = {}
        self.previous = {}
        self.previous_elapsed = self.previous_phase = None
        self.samples = self.phase_overflow_samples = 0
        self.cpu_seconds = 0.0
        self.latest = None
        self.peaks = {}

    def observe(self, sample, phase, elapsed):
        if not isinstance(phase, str) or not phase or len(phase) > 256:
            raise ValueError('Short, nonempty phase name required')
        if not math.isfinite(elapsed) or elapsed < 0 or (
                self.previous_elapsed is not None and elapsed <= self.previous_elapsed):
            raise ValueError('Strictly increasing nonnegative elapsed time required')
        if phase not in self.phases and len(self.phases) >= self.max_phases:
            phase = None
            self.phase_overflow_samples += 1
        entry = None
        if phase is not None:
            entry = self.phases.setdefault(phase, dict(samples=0,
                first_observed_seconds=elapsed, last_observed_seconds=elapsed,
                observed_duration_seconds=0.0, overlapping_identity_cpu_seconds=0.0,
                peaks={}, least_available_ram_bytes=None))
            entry['samples'] += 1
            entry['last_observed_seconds'] = elapsed
        current = {_key(row): row['cpu_kernel_seconds']+row['cpu_user_seconds']
                   for row in sample['live_processes']}
        if len(current) != len(sample['live_processes']):
            raise ValueError('Duplicate process identity in guardian sample')
        if any(not math.isfinite(cpu) or cpu < 0 for cpu in current.values()):
            raise ValueError('Finite nonnegative process CPU counters required')
        delta = 0.0
        for key in current.keys() & self.previous.keys():
            if current[key] < self.previous[key]:
                raise ValueError('CPU counters regressed for the same process identity')
            delta += current[key]-self.previous[key]
        interval = None if self.previous_elapsed is None else elapsed-self.previous_elapsed
        if interval is not None and self.previous_phase is not None:
            previous_entry = self.phases[self.previous_phase]
            previous_entry['observed_duration_seconds'] += interval
            previous_entry['overlapping_identity_cpu_seconds'] += delta
        self.cpu_seconds += delta
        fields = ('parent_rss_bytes', 'process_tree_rss_bytes', 'process_tree_private_bytes',
                  'process_count', 'nonparent_process_count', 'worker_process_count',
                  'parent_os_peak_working_set_bytes', 'parent_os_peak_pagefile_bytes',
                  'largest_observed_process_os_peak_working_set_bytes',
                  'largest_observed_process_os_peak_pagefile_bytes')
        for field in fields:
            value = sample[field]
            if value is not None:
                self.peaks[field] = max(self.peaks.get(field, 0), value)
                if entry is not None:
                    entry['peaks'][field] = max(entry['peaks'].get(field, 0), value)
        available = sample.get('available_ram_bytes')
        if entry is not None and available is not None:
            previous_available = entry['least_available_ram_bytes']
            entry['least_available_ram_bytes'] = available if previous_available is None else min(available, previous_available)
        self.latest = dict(phase=phase, elapsed_seconds=elapsed,
            overlapping_identity_cpu_delta_seconds=delta,
            overlapping_identity_cpu_percent=None if interval is None else 100*delta/interval,
            interval_seconds=interval)
        self.samples += 1
        self.previous, self.previous_elapsed, self.previous_phase = current, elapsed, phase

    def snapshot(self):
        # Return plain data independent of future samples, bounded by max_phases
        # and the current job census; no process history or scientific arrays.
        return dict(schema='atlas.private.resource-summary.r1', samples=self.samples,
            peak_scope='sampled except per-process OS lifetime peaks; no simultaneous tree OS peak claimed',
            cpu_scope='consecutive-sample identity overlap only; excludes first observations and exited-process tails',
            child_scope='worker count excludes exact launch cohort; includes every other live job member',
            phase_scope='sampled transitions; exact outer stage markers remain in workload receipt',
            overlapping_identity_cpu_seconds=self.cpu_seconds,
            latest=None if self.latest is None else dict(self.latest), peaks=dict(self.peaks),
            phase_limit=self.max_phases, phase_overflow_samples=self.phase_overflow_samples,
            phases={name: {**row, 'peaks': dict(row['peaks'])} for name, row in self.phases.items()})
