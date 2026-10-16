"""Launch-bound continuation guard, successor of the preserved guard r2.

Same 12 GiB sampled RSS ceiling, 1 GiB free floor, .25 s nominal sample period,
five-second cooperative grace, cancel filename and receipt ownership. Windows
job membership replaces every PID/creation-time ancestry decision. The external
supervisor owns the job through driver exit, including final receipt writes.

Run: python -B this_file --launch --output ABS.json -- PYTHON -B DRIVER ARGS...
The driver must instantiate ContinuationGuard with the SAME absolute output.
Direct invocation, failed job assignment, and foreign membership fail closed.
The workload and its workers must use ordinary CreateProcess/subprocess launch;
broker-launched services/WMI are not an admitted execution mechanism.
"""
import argparse
from concurrent.futures import CancelledError
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid

import psutil
import private_heat_resource_diagnostics_r1 as RESOURCE_DIAGNOSTICS

from windows_workload_job import WindowsJob, verify_current_membership

RSS_LIMIT = 12 << 30
FREE_FLOOR = 1 << 30
RETRIES, RETRY_SECONDS = 50, .02
PATIENT_TRIES = 500
ENV = 'ATLAS_CONTINUATION_JOB_CONTEXT'


class GuardAborted(CancelledError):
    """A cancelled or unowned workload can never become a successful interval."""


def _limits(rss_bytes, free_floor_bytes, sample_interval, grace_seconds):
    if type(rss_bytes) is not int or not 0 < rss_bytes <= RSS_LIMIT:
        raise ValueError('RSS guard must be positive and at most the authorised 12 GiB')
    if type(free_floor_bytes) is not int or free_floor_bytes < FREE_FLOOR:
        raise ValueError('Free-memory floor cannot fall below the authorised 1 GiB')
    if not math.isfinite(sample_interval) or not .01 <= sample_interval <= 1:
        raise ValueError('Guard sampling interval must be between .01 and 1 second')
    if not math.isfinite(grace_seconds) or not 0 < grace_seconds <= 5:
        raise ValueError('Cooperative grace must be positive and at most 5 seconds')


def _write(path, value, tries=RETRIES):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    for attempt in range(tries):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == tries-1:
                raise
            time.sleep(RETRY_SECONDS)


def _read(path, tries=RETRIES):
    for attempt in range(tries):
        try:
            with Path(path).open(encoding='utf-8') as stream:
                return json.load(stream)
        except (PermissionError, FileNotFoundError):
            if attempt == tries-1:
                raise
            time.sleep(RETRY_SECONDS)


def _terminal_main(output, receipt):
    # Supervisor calls this only after its retained exact process handle signals.
    try:
        main = _read(output)
        main['status'] = 'INTERRUPTED' if receipt.get('reason') == 'user_cancel' else 'FAILED'
        failure = 'Independent continuation guard: ' + str(receipt.get('reason'))
        main.setdefault('failure', failure)
        main.setdefault('errors', []).append(dict(source='continuation_guard', failure=failure))
        main['supervisor'] = {key: receipt.get(key) for key in
                              ('status', 'reason', 'phase', 'cleanup', 'parent', 'guardian')}
        _write(output, main)
        return dict(updated=True)
    except Exception as error:
        return dict(updated=False, error=repr(error))


class ContinuationGuard:
    def __init__(self, output, record, save, *, rss_bytes=RSS_LIMIT,
                 free_floor_bytes=FREE_FLOOR, sample_interval=.25, grace_seconds=5.):
        _limits(rss_bytes, free_floor_bytes, sample_interval, grace_seconds)
        self.output = Path(output).resolve()
        self.record, self.save = record, save
        self.path = self.output.with_suffix('.cancel')
        self.receipt_path = self.output.with_suffix('.guard.json')
        self.abort_path = self.output.with_suffix('.guard-abort.json')
        self.control_path = self.output.with_suffix('.guard-control.json')
        self.started = time.monotonic()
        self.budget, self.counts, self.closed = None, {}, False
        self._check_interval, self._next_check = sample_interval, 0.
        raw = os.environ.get(ENV)
        if raw is None:
            raise GuardAborted('External Windows-job launch required; workload not admitted')
        context = json.loads(raw)
        if context['output'] != str(self.output):
            raise GuardAborted('Launch output differs; workload not admitted')
        self.nonce = context['nonce']
        self.identity = verify_current_membership(context['job_name'])
        self._control = dict(nonce=self.nonce, parent=self.identity, phase='guard-startup',
            close_requested=False, limits=dict(rss_bytes=rss_bytes, free_floor_bytes=free_floor_bytes),
            sample_interval=sample_interval, grace_seconds=grace_seconds)
        if self.control_path.exists():
            raise FileExistsError('Fresh driver control required: ' + str(self.control_path))
        _write(self.control_path, self._control, PATIENT_TRIES)
        deadline = time.monotonic() + 10
        while True:
            receipt = _read(self.receipt_path)
            if receipt.get('nonce') != self.nonce:
                raise GuardAborted('Guardian startup identity mismatch')
            if receipt.get('status') == 'RUNNING':
                if receipt.get('parent') != self.identity:
                    raise GuardAborted('Guardian workload binding differs')
                self.check(force=True)
                self._sync()
                break
            if receipt.get('status') not in ('STARTING',):
                raise GuardAborted('Guardian refused startup: ' + receipt.get('status', 'UNKNOWN'))
            if time.monotonic() >= deadline:
                raise GuardAborted('Guardian startup handshake timed out')
            time.sleep(.025)

    def _sync(self):
        receipt = _read(self.receipt_path)
        if receipt.get('nonce') != self.nonce or receipt.get('parent') != self.identity:
            raise GuardAborted('Guardian receipt identity changed')
        self.record['supervisor'] = dict(receipt=str(self.receipt_path), status=receipt['status'],
            reason=receipt.get('reason'), pid=receipt['guardian']['pid'], limits=receipt['limits'],
            ownership=receipt['ownership'], workload_exit_confirmed=receipt.get('workload_exit_confirmed', False))
        if 'latest_sample' in receipt:
            self.record['resources'] = dict(receipt['latest_sample'],
                sampled_peak_bytes=receipt['sampled_peak_bytes'],
                sampled_peak_by_phase=receipt.get('sampled_peak_by_phase'),
                logical_budget=None if self.budget is None else self.budget.statistics())
        if 'resource_summary' in receipt:
            self.record['resource_summary'] = receipt['resource_summary']
        if 'resource_summary_error' in receipt:
            self.record['resource_summary_error'] = receipt['resource_summary_error']
        return receipt

    def check(self, force=False):
        if self.closed:
            raise GuardAborted('Attempted work after the guardian was closed')
        now = time.monotonic()
        if not force and now < self._next_check:
            return False
        self._next_check = now + self._check_interval
        if self.abort_path.exists():
            abort = _read(self.abort_path)
            if abort.get('nonce') != self.nonce:
                raise GuardAborted('Guardian abort identity changed')
            raise GuardAborted('Independent guard: ' + abort['reason'])
        if self.path.exists():
            raise GuardAborted('Independent guard: user_cancel')
        # A dead supervisor closes the only persistent job handle, terminating
        # every owned process. No PID poll is needed for that fail-closed rule.
        return False

    def phase(self, name):
        self.check(force=True)
        self._control['phase'] = name
        _write(self.control_path, self._control, PATIENT_TRIES)
        self.record.setdefault('phases', []).append(dict(name=name, seconds=time.monotonic()-self.started))
        self.record['stage'] = name
        self._sync()
        self.save()

    def _await_close(self):
        deadline = time.monotonic() + 10
        while True:
            receipt = self._sync()
            if receipt['status'] not in ('RUNNING', 'STARTING', 'ABORT_REQUESTED'):
                return receipt
            if time.monotonic() >= deadline:
                raise GuardAborted('Guardian close acknowledgement unconfirmed')
            time.sleep(.025)

    def close(self):
        if not self.closed:
            self._control['close_requested'] = True
            _write(self.control_path, self._control, PATIENT_TRIES)
            receipt = self._await_close()
            self.closed = True
        else:
            receipt = self._sync()
        if receipt['status'] != 'STOPPED':
            raise GuardAborted('Independent guard closed with ' + receipt['status'] + ': ' + str(receipt.get('reason')))
        return receipt

    def __enter__(self):
        return self

    def __exit__(self, kind, value, trace):
        try:
            self.close()
        except BaseException as error:
            if value is None:
                raise
            value.add_note('Guardian close also failed: ' + repr(error))
        return False


Guard = ContinuationGuard


def supervise(output, command, *, rss_bytes=RSS_LIMIT, free_floor_bytes=FREE_FLOOR,
              sample_interval=.25, grace_seconds=5., cwd=None):
    """Own and observe a workload until exit; return nonzero on any guard failure."""
    _limits(rss_bytes, free_floor_bytes, sample_interval, grace_seconds)
    output = Path(output).resolve()
    paths = {name: output.with_suffix(suffix) for name, suffix in
             (('receipt', '.guard.json'), ('abort', '.guard-abort.json'),
              ('control', '.guard-control.json'), ('cancel', '.cancel'))}
    for path in (output, paths['receipt'], paths['abort'], paths['control']):
        if path.exists():
            raise FileExistsError('Fresh run output required: ' + str(path))
    if not command or not Path(command[0]).is_absolute():
        raise ValueError('An explicit absolute workload executable is required')
    nonce = uuid.uuid4().hex
    started, trigger_time, control_seen, close_ack = time.monotonic(), None, None, False
    job = root = parent = None
    startup_handles = []
    resource_summary = RESOURCE_DIAGNOSTICS.ResourceSummary()
    receipt = dict(schema='atlas.private.continuation-guard.r3', nonce=nonce, status='STARTING',
        parent=None, guardian=dict(pid=os.getpid()), phase='guard-startup', samples=0,
        ownership='Windows job assigned before first instruction; no breakaway; exact-handle membership',
        limits=dict(rss_bytes=rss_bytes, free_floor_bytes=free_floor_bytes),
        sample_interval=sample_interval, grace_seconds=grace_seconds, time_limit_seconds=None,
        sampled_peak_bytes=dict(parent_rss=0, process_tree_rss=0), sampled_peak_by_phase={})

    def save(tries=1):
        receipt['elapsed_seconds'] = time.monotonic()-started
        receipt['updated_utc'] = datetime.now(timezone.utc).isoformat()
        try:
            _write(paths['receipt'], receipt, tries)
        except PermissionError as error:
            receipt['deferred_saves'] = receipt.get('deferred_saves', 0)+1
            receipt['last_deferred_save'] = repr(error)
            if tries != 1:
                raise

    def trigger(reason, detail=None):
        nonlocal trigger_time
        if trigger_time is None:
            trigger_time = time.monotonic()
            receipt.update(status='ABORT_REQUESTED', reason=reason, detail=detail)

    def abort_notice():
        try:
            _write(paths['abort'], dict(nonce=nonce, reason=receipt['reason'],
                                      phase=receipt['phase']), tries=1)
        except PermissionError as error:
            receipt['deferred_abort_notice'] = repr(error)

    try:
        job = WindowsJob()
        receipt['job_name'] = job.name
        save(RETRIES)  # Before any workload exists.
        env = dict(os.environ, **{ENV: json.dumps(dict(output=str(output), nonce=nonce, job_name=job.name))})
        root = job.launch(command, env, cwd or output.parent)
        receipt['launcher'] = root.identity()
        next_save = started
        while True:
            tick = time.monotonic()
            # Never sleep inside shared-file retry loops while responsible for
            # memory enforcement. Retain the last valid control during sharing.
            try:
                control = _read(paths['control'], tries=1)
                if control.get('nonce') != nonce:
                    raise RuntimeError('Guard control nonce changed')
                requested = control['limits']
                _limits(requested['rss_bytes'], requested['free_floor_bytes'],
                        control['sample_interval'], control['grace_seconds'])
                if (requested['rss_bytes'] > rss_bytes or requested['free_floor_bytes'] < free_floor_bytes
                        or control['sample_interval'] != sample_interval or control['grace_seconds'] != grace_seconds):
                    raise RuntimeError('Driver requests a different supervisor policy')
                if parent is None:
                    parent = job.member(control['parent']['pid'])
                    if parent is None or parent.identity() != control['parent']:
                        raise RuntimeError('Registering driver is not the exact owned process')
                    receipt['parent'] = parent.identity()
                    # Windows virtualenv launch can use more than one wrapper.
                    # The driver registers before work/worker creation. Retain
                    # exact handles for this launch-only cohort, count its RSS,
                    # and require the entire job to empty after driver exit.
                    for pid in job.pids():
                        handle = job.member(pid)
                        if handle is not None:
                            startup_handles.append(handle)
                    receipt['launch_cohort'] = [handle.identity() for handle in startup_handles]
                elif control['parent'] != receipt['parent']:
                    raise RuntimeError('Registered workload identity changed')
                control_seen = tick
                receipt['phase'] = control['phase']
                rss_bytes, free_floor_bytes = requested['rss_bytes'], requested['free_floor_bytes']
                receipt['limits'] = requested
            except (FileNotFoundError, PermissionError) as error:
                receipt['deferred_control_reads'] = receipt.get('deferred_control_reads', 0)+1
                if tick-(control_seen if control_seen is not None else started) > 10:
                    raise RuntimeError('Driver control unavailable for ten seconds') from error
                control = None
            sample = RESOURCE_DIAGNOSTICS.sample_job(job,
                None if parent is None else parent.pid, receipt.get('launch_cohort'))
            sample.update(available_ram_bytes=psutil.virtual_memory().available,
                          guardian_rss_bytes=psutil.Process().memory_info().rss)
            if resource_summary is not None:
                # Passive: a diagnostic failure disables only this summary.
                try:
                    resource_summary.observe(sample, str(receipt['phase']), tick-started)
                    resource_snapshot = resource_summary.snapshot()
                    json.dumps(resource_snapshot, allow_nan=False)
                    receipt['resource_summary'] = resource_snapshot
                except Exception as diagnostic_error:
                    resource_summary = None
                    receipt['resource_summary_error'] = repr(diagnostic_error)[:1024]
            receipt['latest_sample'] = sample
            receipt['samples'] += 1
            for key, field in (('parent_rss', 'parent_rss_bytes'), ('process_tree_rss', 'process_tree_rss_bytes')):
                receipt['sampled_peak_bytes'][key] = max(receipt['sampled_peak_bytes'][key], sample[field])
            phase = receipt['sampled_peak_by_phase'].setdefault(str(receipt['phase']),
                dict(parent_rss=0, process_tree_rss=0, least_available_ram=sample['available_ram_bytes']))
            phase['parent_rss'] = max(phase['parent_rss'], sample['parent_rss_bytes'])
            phase['process_tree_rss'] = max(phase['process_tree_rss'], sample['process_tree_rss_bytes'])
            phase['least_available_ram'] = min(phase['least_available_ram'], sample['available_ram_bytes'])
            if paths['cancel'].exists():
                trigger('user_cancel')
            if sample['process_tree_rss_bytes'] > rss_bytes:
                trigger('rss_limit', sample)
            if sample['available_ram_bytes'] < free_floor_bytes:
                trigger('free_memory_floor', sample)
            if receipt['status'] == 'STARTING' and parent is not None:
                receipt['status'] = 'RUNNING'
                save()
            target = parent if parent is not None else root
            exit_code = target.poll()
            if exit_code is not None:
                if not close_ack:
                    trigger('parent_exited_without_guard_close')
                # Root can be a venv redirector, the registered parent its Python.
                # Give that exact wrapper a bounded opportunity to exit normally.
                deadline = time.monotonic()+2
                startup_pids = {handle.pid for handle in startup_handles}
                if not any(pid not in startup_pids for pid in job.pids()):
                    for handle in startup_handles:
                        handle.wait(max(0, deadline-time.monotonic()))
                remaining = job.pids()
                if remaining:
                    trigger('live_descendants_at_exit', remaining)
                    receipt['cleanup'] = job.stop()
                else:
                    receipt['cleanup'] = dict(remaining=[], action_errors=[])
                receipt.update(workload_exit_confirmed=True, workload_exit_code=exit_code)
                if trigger_time is not None:
                    receipt['status'] = 'PARENT_EXITED'
                    receipt['main_output_update'] = _terminal_main(output, receipt)
                else:
                    receipt['status'] = 'STOPPED'
                save(RETRIES)
                return 0 if trigger_time is None and exit_code == 0 else 2
            if control is not None and control.get('close_requested') and not close_ack:
                startup_pids = {handle.pid for handle in startup_handles}
                extra = [pid for pid in job.pids() if pid not in startup_pids]
                if extra:
                    trigger('live_descendants_at_close', extra)
                receipt['status'] = 'COOPERATIVE_ABORT' if trigger_time is not None else 'STOPPED'
                # A deferred receipt cannot acknowledge close; keep trying while
                # still sampling. There is no terminal save before termination.
                save()
                close_ack = True
            if trigger_time is not None:
                abort_notice()
                if time.monotonic()-trigger_time >= grace_seconds:
                    receipt['status'] = 'HARD_STOPPING'
                    save()
                    receipt['cleanup'] = job.stop()
                    # Windows can remove a process from the job census just
                    # before its retained handle becomes signalled.
                    receipt['workload_exit_confirmed'] = target.wait(2.)
                    receipt['status'] = 'HARD_STOPPED' if receipt['workload_exit_confirmed'] else 'HARD_STOP_FAILED'
                    if receipt['workload_exit_confirmed']:
                        receipt['main_output_update'] = _terminal_main(output, receipt)
                    save(RETRIES)
                    return 2
            if tick >= next_save or close_ack or trigger_time is not None:
                save()
                next_save = tick+5
            time.sleep(max(0., sample_interval-(time.monotonic()-tick)))
    except BaseException as error:
        receipt.update(status='GUARDIAN_FAILED', reason='guardian_failure', detail=repr(error))
        if job is not None:
            try:
                receipt['cleanup'] = job.stop()
            except BaseException as cleanup_error:
                receipt['cleanup_error'] = repr(cleanup_error)
        target = parent if parent is not None else root
        if target is not None and target.wait(2.):
            receipt['workload_exit_confirmed'] = True
            receipt['main_output_update'] = _terminal_main(output, receipt)
        try:
            save(RETRIES)
        except BaseException:
            pass
        raise
    finally:
        for handle in startup_handles:
            handle.close()
        if parent is not None:
            parent.close()
        if root is not None:
            root.close()
        if job is not None:
            job.close()  # Kernel kills every remaining member, even if never sampled.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    return supervise(args.output, command)


if __name__ == '__main__':
    raise SystemExit(main())
