"""Two guarded workloads for Plan11 phase 2; never starts a future producer.

This module owns launcher-side lifetime and observations, not scientific checks.
The caller supplies its existing guard handshake/tracking and postchecks. A
launcher failure always requests cancellation and confirms exits; it never
equates launcher loss with a stopped guardian. No automatic fallback exists.
"""
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import subprocess
import time


class CohortRefused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise CohortRefused(message)


@dataclass
class GuardedTask:
    process: object
    paths: dict
    started: float
    tracking: dict
    confirm_exit: object = None


def start(argv, env, paths, *, await_running, track, confirm_exit, emit, clock=time.monotonic):
    """The existing Windows guarded launch, split before its blocking wait."""
    require(os.name == 'nt', 'Windows guarded process launch required')
    require(callable(confirm_exit), 'final guard/job cleanup confirmation callback required')
    paths['out'].mkdir(exist_ok=False)
    began = clock()
    with open(paths['log'], 'xb') as log:
        process = subprocess.Popen(argv, env=env, cwd=paths['out'], stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    task = GuardedTask(process, paths, began, {}, confirm_exit)
    try:
        receipt = await_running(process, paths)
        require(receipt is not None, 'guarded workload did not reach RUNNING')
        task.tracking = track(process, receipt, paths)
        require(type(task.tracking) is dict and type(task.tracking.get('parent')) is dict,
                'exact guarded waiter identity was not tracked')
        emit(json.dumps({'status': 'RUNNING', 'parent': task.tracking['parent'],
                         'output': str(paths['out'])}))
        return task
    except BaseException as error:
        # Sidecars can exist even if the handshake/track failed. Do not abandon it.
        try:
            cancel_and_confirm(task, timeout_seconds=30)
        except BaseException as failure:
            error.add_note('Plan11 startup cleanup unconfirmed: '+repr(failure))
        raise


def wait(task, *, check_sources, clock=time.monotonic):
    """Wait while checking pinned sources; a source failure cancels the cohort upstream."""
    while task.process.poll() is None:
        check_sources()
        try:
            task.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
    check_sources()
    return task.process.returncode, clock()-task.started


def cancel_and_confirm(task, *, timeout_seconds, alive=None, clock=time.monotonic):
    """Request this guard's cancellation and confirm wrapper AND tracked tree exit.

    Timeout is a visible failure, never permission to adopt or start another
    attempt. The guard owns its Windows job; this routine does not kill arbitrary
    PIDs or infer that wrapper exit implies guardian exit.
    """
    require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds) and timeout_seconds > 0,
            'positive finite cancellation bound required')
    if alive is None:
        def alive(identity):
            if 'created_ticks' in identity:
                from reader_overlap_gate import process_alive
                return process_alive(identity)
            import psutil
            try:
                return psutil.Process(identity['pid']).create_time() == identity['create_time']
            except psutil.NoSuchProcess:
                return False
    identities = [task.tracking[name] for name in ('parent', 'guardian') if name in task.tracking]
    complete = (type(task.tracking.get('parent')) is dict and type(task.tracking.get('guardian')) is dict and
                set(task.tracking['parent']) == {'pid', 'created_ticks'} and
                type(task.tracking['parent']['pid']) is int and task.tracking['parent']['pid'] > 0 and
                type(task.tracking['parent']['created_ticks']) is int and task.tracking['parent']['created_ticks'] > 0 and
                type(task.tracking['guardian'].get('pid')) is int and task.tracking['guardian']['pid'] > 0 and
                type(task.tracking['guardian'].get('create_time')) in (int, float) and
                math.isfinite(task.tracking['guardian']['create_time']) and
                task.tracking['guardian']['create_time'] > 0)
    if complete and task.process.poll() is not None and not any(alive(identity) for identity in identities):
        require(callable(task.confirm_exit) and task.confirm_exit(task.paths, task.tracking) is True,
                'cancellation unconfirmed: final guard/job cleanup proof is absent or failed')
        return {'cancel_requested': False, 'wrapper_exit': task.process.returncode,
                'tracked_processes_exited': True}
    cancel = Path(task.paths['cancel'])
    try:
        with cancel.open('xb') as stream:
            stream.write(b'Plan11 launcher cancellation\n')
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        pass
    deadline = clock()+timeout_seconds
    while task.process.poll() is None and clock() < deadline:
        try:
            task.process.wait(timeout=min(0.25, max(0.001, deadline-clock())))
        except subprocess.TimeoutExpired:
            pass
    require(task.process.poll() is not None, 'cancellation unconfirmed: guarded wrapper is still live')
    require(complete, 'cancellation unconfirmed: exact parent/guardian tracking is incomplete')
    while any(alive(identity) for identity in identities) and clock() < deadline:
        time.sleep(min(0.05, max(0.001, deadline-clock())))
    require(not any(alive(identity) for identity in identities),
            'cancellation unconfirmed: guarded process or guardian is still live')
    require(callable(task.confirm_exit) and task.confirm_exit(task.paths, task.tracking) is True,
            'cancellation unconfirmed: final guard/job cleanup proof is absent or failed')
    return {'cancel_requested': True, 'wrapper_exit': task.process.returncode,
            'tracked_processes_exited': True}


def run_pair(*, start_producer, start_reader, producer_passed, publish_gate,
             reader_passed, check_sources, cancel_timeout_seconds=30):
    """Run current producer and serial reader; publish only after all producer checks.

    producer_passed must execute the unchanged guard/process-tree/receipt checks
    AND store-free producer_inputs preflight. publish_gate receives those results
    and the exact tracked waiter. reader_passed retains the ordinary reader
    postcheck. Finalise/adopt remain with the existing caller, after this returns.
    """
    producer = reader = None
    try:
        check_sources()
        producer = start_producer()
        reader = start_reader()
        code, seconds = wait(producer, check_sources=check_sources)
        evidence = producer_passed(code, seconds)
        require(evidence is not None, 'producer publication preflight supplied no evidence')
        require(reader.process.poll() is None, 'overlap reader exited before gate publication')
        check_sources()
        gate = publish_gate(evidence, reader.tracking['parent'])
        code, seconds = wait(reader, check_sources=check_sources)
        result = reader_passed(code, seconds)
        check_sources()
        return {'producer': evidence, 'gate': gate, 'reader': result}
    except BaseException as error:
        cleanup = []
        for task in (reader, producer):
            if task is not None:
                try:
                    cleanup.append(cancel_and_confirm(task, timeout_seconds=cancel_timeout_seconds))
                except BaseException as failure:
                    error.add_note('Plan11 cancellation/exit confirmation failed: '+repr(failure))
        # The failed attempt and its cancellation evidence remain in the caller's record.
        if cleanup:
            error.add_note('Plan11 cancellation evidence: '+repr(cleanup))
        raise


ELIGIBLE_FALLBACK = frozenset(('launcher_lost', 'wait_expired', 'cancelled', 'free_floor'))


def fallback_decision(*, failed_attempt, failure_reason, producer_valid, approval, directory, claim_path):
    """Validate one explicit coordinator-authorised sequential fallback; never launch it.

    The caller writes this decision exclusively before launching and preserves
    failed_attempt. Data, identity, receipt and gate failures are ineligible.
    """
    require(type(failed_attempt) is str and failed_attempt, 'failed overlap attempt identity required')
    require(failure_reason in ELIGIBLE_FALLBACK and producer_valid is True,
            'fallback requires an eligible non-data failure and a fully valid sealed producer')
    fields = {'failed_attempt', 'reason', 'fresh_directory', 'coordinator_approval'}
    require(type(approval) is dict and set(approval) == fields and
            approval['failed_attempt'] == failed_attempt and approval['reason'] == failure_reason and
            approval['fresh_directory'] == str(directory) and
            type(approval['coordinator_approval']) is str and approval['coordinator_approval'].strip(),
            'specific coordinator approval for this failed attempt and fresh directory required')
    target = Path(directory)
    require(target.is_absolute() and not target.exists() and target.parent.is_dir(),
            'fallback requires an absent output in an existing parent directory')
    claim = Path(claim_path)
    require(Path(failed_attempt).is_absolute() and Path(failed_attempt).is_dir() and
            claim == Path(failed_attempt)/'sequential-fallback.claim.json' and
            target.parent == Path(failed_attempt).parent,
            'fallback requires the failed reader fixed claim and a fresh sibling output')
    require(claim.is_absolute() and claim.parent.is_dir() and not claim.exists(),
            'one exclusive fallback claim per failed overlap attempt required')
    # The integration derives this fixed filename from the failed attempt, never
    # from the chosen output directory. A new directory cannot reset the count.
    with claim.open('xb') as stream:
        stream.write((json.dumps(approval, sort_keys=True, allow_nan=False)+'\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    return dict(approval)
