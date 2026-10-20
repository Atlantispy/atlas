"""Passive bounded cohort/disk observations, recorded in the existing stage record.

No global tracing, profiler hooks or background service. A caller samples at its
normal process wait boundary. Results are sampled peaks, not exact allocation
maxima or numerical validation. Both comparable arms use the same observer.
"""
import math
import os
from pathlib import Path
import time


class MeasurementRefused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise MeasurementRefused(message)


def ordinary_output_path(root):
    """Check original existing ancestry before resolving; junctions must not escape."""
    path = Path(root).absolute()
    for item in (*reversed(path.parents), path):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        require(not item.is_symlink() and not (getattr(info, 'st_file_attributes', 0) & 0x400),
                'reparse point in measured output ancestry')
    return path


def output_bytes(root):
    """Only this arm's declared output; refuse reparse points and links."""
    root = ordinary_output_path(root)
    if not root.exists():
        return 0
    require(root.is_dir() and not root.is_symlink(), 'ordinary arm output directory required')
    total = 0
    def scan_error(error):
        raise MeasurementRefused('output disk scan incomplete: '+str(error)) from error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=scan_error):
        for name in (*dirs, *files):
            path = Path(directory)/name
            try:
                st = path.lstat()
            except FileNotFoundError:
                continue  # A transient staging file ended between bounded observations.
            require(not path.is_symlink() and not (getattr(st, 'st_file_attributes', 0) & 0x400),
                    'reparse point in measured output')
            if name in files:
                total += st.st_size
    return total


class CohortObserver:
    def __init__(self, launcher_pid, *, output_roots, clock=time.monotonic, process_factory=None,
                 memory_sample_seconds=0.5, disk_sample_seconds=2):
        if process_factory is None:
            import psutil
            process_factory = psutil.Process
        require(type(launcher_pid) is int and launcher_pid > 0, 'explicit launcher PID required')
        roots = tuple(ordinary_output_path(root).resolve() for root in output_roots)
        require(roots and len(set(roots)) == len(roots) and
                not any(a != b and a.is_relative_to(b) for a in roots for b in roots),
                'disjoint output roots required to avoid double-counting')
        require(type(memory_sample_seconds) in (int, float) and type(disk_sample_seconds) in (int, float) and
                math.isfinite(memory_sample_seconds) and math.isfinite(disk_sample_seconds) and
                0 < memory_sample_seconds <= disk_sample_seconds,
                'positive bounded observer cadence required')
        self.root = process_factory(launcher_pid)
        self.identity = (launcher_pid, self.root.create_time())
        self.outputs, self.clock = roots, clock
        self.started, self.next_ram, self.next_disk = clock(), 0., 0.
        self.ram_cadence, self.disk_cadence = memory_sample_seconds, disk_sample_seconds
        self.ram_peak = self.disk_peak = self.process_peak = self.samples = 0
        self.observer_seconds = 0.
        self.per_process_peaks = {}

    def sample(self, *, force=False):
        began = self.clock()
        require(self.root.create_time() == self.identity[1], 'launcher PID was reused')
        if force or began >= self.next_ram:
            self.next_ram = began+self.ram_cadence
            processes = {self.root.pid: self.root}
            processes.update((p.pid, p) for p in self.root.children(recursive=True))
            total = count = 0
            import psutil
            for process in processes.values():
                try:
                    identity = (process.pid, process.create_time())
                    rss = process.memory_info().rss
                except psutil.NoSuchProcess:
                    continue
                # Access failures remain failures; they do not turn missing RSS into zero.
                total += rss
                count += 1
                key = f'{identity[0]}@{identity[1]:.9f}'
                self.per_process_peaks[key] = max(self.per_process_peaks.get(key, 0), rss)
            self.ram_peak, self.process_peak = max(self.ram_peak, total), max(self.process_peak, count)
            self.samples += 1
        if force or began >= self.next_disk:
            self.next_disk = began+self.disk_cadence
            self.disk_peak = max(self.disk_peak, sum(output_bytes(root) for root in self.outputs))
        self.observer_seconds += self.clock()-began

    def record(self):
        return {'schema': 'atlas.reader-overlap-observation.v1',
                'wall_seconds': self.clock()-self.started, 'sampled_tree_peak_bytes': self.ram_peak,
                'sampled_output_peak_bytes': self.disk_peak, 'sampled_process_peak': self.process_peak,
                'per_process_sampled_peaks': dict(self.per_process_peaks), 'samples': self.samples,
                'ram_sample_seconds': self.ram_cadence, 'disk_sample_seconds': self.disk_cadence,
                'observer_seconds': self.observer_seconds,
                'output_roots': [str(root) for root in self.outputs],
                'coverage': 'launcher descendants, including both guarded trees; sampled output sizes'}


def compare(baseline, candidate):
    """Summarise complete comparable observations; never manufacture missing values."""
    identity = ('input_identity', 'source_identity', 'ale_policy', 'reader_initial_workers', 'cache_state')
    for arm in (baseline, candidate):
        require(type(arm) is dict and arm.get('completed_chain') is True and arm.get('exact_checks_passed') is True,
                'completed reader/finalise/adoption and exact-check evidence required for both arms')
        require(all(name in arm for name in identity) and
                all(type(arm[name]) is str and arm[name].strip() for name in
                    ('input_identity', 'source_identity', 'cache_state')) and
                arm.get('ale_policy') == {'mode': 'serial'} and
                type(arm.get('reader_initial_workers')) is int and arm['reader_initial_workers'] == 0,
                'explicit matching input/source/cache/serial policies required')
        require(arm.get('exclusive') is True and arm.get('small_jobs_max') == 0 and
                type(arm.get('small_jobs_max')) is int and
                type(arm.get('free_cores_at_start')) in (int, float) and
                math.isfinite(arm['free_cores_at_start']) and arm['free_cores_at_start'] >= 0,
                'clean exclusive queue conditions must be recorded')
    require(all(baseline[name] == candidate[name] for name in identity), 'comparison inputs/sources/policies differ')
    result = {'scope': 'MEASURED selected serial-ALE route only', 'metrics': {}}
    fields = ('wall_seconds', 'sampled_tree_peak_bytes', 'sampled_output_peak_bytes')
    for name in fields:
        before, after = baseline.get(name), candidate.get(name)
        require(type(before) in (int, float) and type(after) in (int, float) and
                math.isfinite(before) and math.isfinite(after) and before > 0 and after >= 0,
                'missing, nonfinite or invalid comparable metric: '+name)
        result['metrics'][name] = {'baseline': before, 'candidate': after, 'reduction': before-after,
                                   'reduction_percent': (before-after)/before*100}
    return result
