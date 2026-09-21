#!/usr/bin/env python3
"""Run one finite, fixed-schedule R4.4 case segment; never infer full acceptance.
SPDX-License-Identifier: AGPL-3.0-only

Use -I -B and the declared installed environment. New run directories are
exclusive. Resume verifies the immutable receipt chain and exact code, case
specification, solver policy and future schedule. SIGTERM/SIGINT request
cooperative cancellation; an accepted state is saved before returning. A
hard-kill lock is not removed automatically. Existing ArrayStore transactions,
identity checking and WorkBudget admission are reused rather than replaced.
"""
from __future__ import annotations

import argparse
from concurrent.futures import CancelledError
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT/'src'))
import numpy as np
import atlas_tectonics as atlas
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreLimits
from atlas_tectonics.reuse import ExecutionContext

SCHEMA = 'atlas.convection-run-r4-4.v1'
STEP_SOURCE = 'Tosi R4.4: fixed published inputs and explicit unchanged timestep schedule'


def encode(obj):
    return (json.dumps(obj, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_new(path, obj):
    """Publish flushed complete JSON by an exclusive same-filesystem hard link."""
    temporary = path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(encode(obj)); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, path)
        if hasattr(os, 'O_DIRECTORY'):
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(fd)
            finally: os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def safe_path(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symbolic-link run/source paths are refused')


def source_record():
    safe_path(ROOT)
    inventory = {}
    for p in sorted((ROOT/'src').rglob('*')):
        safe_path(p)
        if p.suffix in ('.pyc', '.pyo'):
            raise ValueError('pre-existing bytecode is refused')
        if p.is_file(): inventory[p.relative_to(ROOT).as_posix()] = digest(p.read_bytes())
    return dict(source=inventory, runner=digest(Path(__file__).read_bytes()),
                case_specification=digest((ROOT/'cases/convection_r4_4.json').read_bytes()))


class Cancellation:
    def __init__(self, seconds):
        self.requested = False
        self.deadline = None if seconds is None else time.monotonic()+seconds
    def is_set(self):
        return self.requested or (self.deadline is not None and time.monotonic() >= self.deadline)
    def signal(self, *_): self.requested = True


def read_receipts(out, config_id):
    """Read the immutable chain, folding diagnostic-only repairs into their state.

    A repair is a new linked receipt, never an overwrite or an extra physical
    step. The returned head commits to it as well as the accepted-state ledger.
    """
    records = []
    previous = None
    for path in sorted(out.glob('receipt_*.json')):
        safe_path(path)
        raw = path.read_bytes()
        record = json.loads(raw)
        if record['config_id'] != config_id or record['parent_receipt'] != previous:
            raise ValueError('receipt/configuration chain changed')
        repair = record.get('kind') == 'endpoint-diagnostic'
        if record.get('kind') not in (None, 'endpoint-diagnostic'):
            raise ValueError('unknown receipt kind')
        suffix = '_diagnostic' if repair else ''
        if path.name != f"receipt_{record['step']:09d}{suffix}.json":
            raise ValueError('receipt filename/step mismatch')
        if repair:
            if (not records or any(record[k] != records[-1][k] for k in ('step', 'time', 'state_id'))
                    or record['stage_iteration_counts'] or len(record['samples']) != 1):
                raise ValueError('diagnostic repair must attach to the same accepted endpoint')
            sample = record['samples'][0]
            if (any(sample[k] != record[k] for k in ('step', 'time', 'state_id'))
                    or any(s['step'] >= record['step'] for s in records[-1]['samples'])):
                raise ValueError('diagnostic repair has a duplicate or mismatched endpoint sample')
            records[-1]['samples'].append(sample)
            previous = digest(raw)
            continue
        if records and (record['step'] <= records[-1]['step'] or record['time'] <= records[-1]['time']):
            raise ValueError('non-monotone accepted receipt chain')
        previous = digest(raw)
        records.append(record)
    if not records: raise ValueError('no committed receipt; orphan states cannot be resumed')
    return records, previous


def schedule_feasibility(config, specification):
    """Cheap necessary maturity conditions, not sufficient convergence evidence.

    Short explicit smoke/diagnostic runs remain allowed. In particular, ten
    observed periods are only a lower duration bound: spin-up and peak alignment
    require additional time. No schedule or acceptance tolerance is changed.
    """
    dt = config['dt']
    if type(dt) not in (int,float) or not math.isfinite(dt) or dt <= 0:
        raise ValueError('schedule dt must be finite and positive')
    for key in ('maximum_steps','sample_every','save_every'):
        if type(config[key]) is not int or config[key] <= 0:
            raise ValueError('schedule counts must be positive integers')
    if config['sample_every'] > config['save_every'] or config['save_every'] % config['sample_every']:
        raise ValueError('save cadence must be a positive multiple of sample cadence')
    duration = dt*config['maximum_steps']
    sample_gap = dt*config['sample_every']
    field_gap = dt*config['save_every']
    policy = specification['predeclared_acceptance']
    case = config['case']['name']
    if case not in ('tosi-1','tosi-2','tosi-3','tosi-4','tosi-5a','tosi-5b'):
        raise ValueError('unrecognised benchmark case')
    blockers = []
    unknowns = ['A feasible schedule does not establish maturity or reference agreement.']
    if config['maximum_steps'] % config['sample_every']:
        blockers.append('Final scheduled state has no uniformly spaced diagnostic sample.')
    if case in ('tosi-1','tosi-2','tosi-3','tosi-4'):
        steady = policy['steady']
        if duration < steady['minimum_time']:
            blockers.append('Maximum duration is shorter than the registered steady-state minimum time.')
        if sample_gap*(steady['minimum_samples']-1) > steady['window']*(1+1e-12):
            blockers.append('Diagnostic cadence cannot fit the required sample count in the steady window.')
    elif case == 'tosi-5a':
        periods = specification['reported_values'][case]['period'].values()
        low, high = min(periods), max(periods)
        periodic = policy['periodic']
        if duration < periodic['cycles']*high:
            blockers.append('Duration cannot cover the required cycles across the published period range, even before spin-up.')
        if sample_gap*periodic['samples_per_period'] > low*(1+1e-12):
            blockers.append('Diagnostic cadence underresolves the shortest published period.')
        if field_gap*periodic['samples_per_period'] > low*(1+1e-12):
            blockers.append('Saved-field cadence underresolves the shortest published period.')
    else:
        unknowns.append('Case 5b regime and period must be established for this yield; no universal duration is inferred.')
    return dict(status='INSUFFICIENT_FOR_MATURITY' if blockers else 'NO_KNOWN_SCHEDULE_BLOCKER',
                known_blockers=blockers, unknowns=unknowns, benchmark_accepted=False)


def main(args):
    output = args.output.absolute()
    safe_path(output)
    if type(args.segment_steps) is not int or not 1 <= args.segment_steps <= 1000000:
        raise ValueError('one invocation requires 1..1000000 finite segment steps')
    if args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds <= 0):
        raise ValueError('positive finite cooperative time allowance required')
    supplied = ('case', 'yield_stress', 'cells', 'dt', 'max_steps', 'save_every',
                'sample_every', 'max_picard', 'linear_rtol', 'momentum_tolerance',
                'viscosity_rtol', 'ilu_fill_factor', 'nonlinear_start', 'nonlinear_solver', 'preconditioner_max_uses', 'adaptive_inner', 'velocity_preconditioner')
    identities = source_record()
    if args.resume:
        if any(getattr(args, k) is not None for k in supplied):
            raise ValueError('resume uses frozen inputs/policies; do not resupply them')
        config = json.loads((output/'run.json').read_bytes())
        if config['schema'] != SCHEMA or config['identities'] != identities:
            raise ValueError('changed source/runner/specification; continuation refused')
    else:
        case = atlas.TosiCase(args.case or 'tosi-1', args.yield_stress)
        n = 16 if args.cells is None else args.cells
        case.problem(n)  # typed physical validation before making an output directory
        dt = 1e-5 if args.dt is None else args.dt
        steps = 30000 if args.max_steps is None else args.max_steps
        save = 500 if args.save_every is None else args.save_every
        sample = 25 if args.sample_every is None else args.sample_every
        if not math.isfinite(dt) or dt <= 0 or dt > .01:
            raise ValueError('positive finite explicit timestep <=0.01 required')
        if type(steps) is not int or not 1 <= steps <= 10000000:
            raise ValueError('finite overall step envelope required')
        if (type(save) is not int or type(sample) is not int or
                not 1 <= sample <= save <= 100000 or save % sample):
            raise ValueError('save cadence must be a positive multiple of sample cadence')
        if steps % sample:
            raise ValueError('maximum steps must be a multiple of sample cadence so the final state can be assessed')
        # A larger *iteration count*, not weaker convergence, is explicitly selected.
        pol = atlas.NonlinearStokesPolicy(
            max_picard_iterations=400 if args.max_picard is None else args.max_picard,
            linear_rtol=1e-12 if args.linear_rtol is None else args.linear_rtol,
            momentum_tolerance=1e-9 if args.momentum_tolerance is None else args.momentum_tolerance,
            viscosity_rtol=1e-8 if args.viscosity_rtol is None else args.viscosity_rtol,
            ilu_fill_factor=17.0 if args.ilu_fill_factor is None else args.ilu_fill_factor,
            velocity_preconditioner=args.velocity_preconditioner or 'auto')
        if pol.linear_rtol > 1e-12 or pol.momentum_tolerance > 1e-9 or pol.viscosity_rtol > 1e-8:
            raise ValueError('benchmark runner refuses weaker-than-R4.3 convergence gates')
        nonlinear_start = 'zero-rate' if args.nonlinear_start is None else args.nonlinear_start
        if nonlinear_start not in ('zero-rate','rk-stage0','previous-stage1'):
            raise ValueError('unsupported nonlinear starting policy')
        config = dict(schema=SCHEMA, identities=identities, case=asdict(case), cells=n,
            dt=dt, maximum_steps=steps, save_every=save, sample_every=sample,
            nonlinear_start=nonlinear_start, nonlinear_policy=asdict(pol), thermal_policy=asdict(atlas.ThermochemicalPolicy(max_steps=steps)),
            forcing='two-current-stage-mechanics; zero composition; zero extra heating',
            field_source=STEP_SOURCE, benchmark_accepted=False)
        if args.adaptive_inner:config['adaptive_inner_policy']=asdict(atlas.AdaptiveInnerPolicy())
        if args.nonlinear_solver=='anderson':config['anderson_policy']=asdict(atlas.AndersonPolicy())
        if args.preconditioner_max_uses is not None:config['preconditioner_reuse_policy']=asdict(atlas.PreconditionerReusePolicy(max_uses=args.preconditioner_max_uses))
        output.mkdir(parents=False, exist_ok=False)
        atomic_new(output/'run.json', config)
        specification = json.loads((ROOT/'cases/convection_r4_4.json').read_bytes())
        print(json.dumps({'schedule_feasibility': schedule_feasibility(config, specification)}), flush=True)
    config_id = digest(encode(config))
    # The lock remains after a hard kill; never remove another process's claim.
    lock = output/'RUNNING.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'pid': os.getpid(), 'config_id': config_id}, stream)
        stream.flush(); os.fsync(stream.fileno())
    budget = WorkBudget(args.budget_mib << 20)
    cancel = Cancellation(args.seconds)
    old_handlers = {sig: signal.signal(sig, cancel.signal) for sig in (signal.SIGINT, signal.SIGTERM)}
    start = time.perf_counter()
    state = None; parent = None; pending = []; last_saved = -1; stage_iterations = []
    outcome = dict(status='STARTED', config_id=config_id, benchmark_accepted=False)
    invocation = uuid.uuid4().hex
    try:
        case = atlas.TosiCase(**config['case'])
        problem = case.problem(config['cells'])
        pol = atlas.NonlinearStokesPolicy(**config['nonlinear_policy'])
        thermal = atlas.ThermochemicalPolicy(**config['thermal_policy'])
        ip=None if 'adaptive_inner_policy' not in config else atlas.AdaptiveInnerPolicy(**config['adaptive_inner_policy'])
        if ip is not None:
            from atlas_tectonics.adaptive_inner import check_policy
            check_policy(ip,pol)
            if encode(asdict(ip))!=encode(config['adaptive_inner_policy']):raise ValueError('noncanonical adaptive policy')
        ap=None if 'anderson_policy' not in config else atlas.AndersonPolicy(**config['anderson_policy'])
        if ap is not None and encode(asdict(ap))!=encode(config['anderson_policy']):raise ValueError('noncanonical Anderson policy')
        with ExecutionContext('numba') as context:
            # Runtime identity is checked independently of source file identity.
            runtime_path = output/'runtime.json'
            if args.resume:
                if json.loads(runtime_path.read_bytes())['identity'] != context.identity:
                    raise ValueError('changed loaded runtime/source context; continuation refused')
            else: atomic_new(runtime_path, {'identity': context.identity})
        with ArrayStore(output/'states.sqlite', StoreLimits(chunk_bytes=65536,
                max_store_bytes=2<<30, max_array_bytes=32<<20), budget=budget) as store:
            if args.resume:
                records, parent = read_receipts(output, config_id)
                last = records[-1]
                state = atlas.load_thermochemical_state(store, last['state_id'], budget=budget)
                if (state.problem.problem_id != problem.problem_id or state.step_index != last['step'] or
                        state.time_s != last['time']):
                    raise ValueError('stored state differs from frozen case/receipt')
                last_saved = state.step_index
            else:
                state = atlas.ThermochemicalState(problem, atlas.tosi_initial_temperature(config['cells'], budget=budget),
                    np.zeros((config['cells'], config['cells'])), time_s=0.,
                    source='Tosi equation 11 exact cell-average initial state', budget=budget)

            def save():
                nonlocal parent, pending, last_saved, stage_iterations
                repair = state.step_index == last_saved
                if repair and not pending: return
                if repair and (stage_iterations or len(pending) != 1 or
                        any(pending[0][k] != value for k, value in
                            (('step', state.step_index), ('time', state.time_s), ('state_id', state.state_id)))):
                    raise ValueError('only a missing endpoint diagnostic may amend a saved state')
                if source_record() != identities:
                    raise ValueError('source/runner/specification changed before publication')
                if not repair: atlas.save_thermochemical_state(state, store, budget=budget)
                rec = dict(config_id=config_id, parent_receipt=parent, state_id=state.state_id,
                    step=state.step_index, time=state.time_s, samples=pending,
                    stage_iteration_counts=stage_iterations)
                if repair: rec['kind'] = 'endpoint-diagnostic'
                suffix = '_diagnostic' if repair else ''
                path = output/f'receipt_{state.step_index:09d}{suffix}.json'
                atomic_new(path, rec)
                parent = digest(path.read_bytes()); last_saved = state.step_index
                pending = []; stage_iterations = []

            with atlas.PreparedThermochemical2D(problem, policy=thermal, nonlinear_policy=pol,
                    nonlinear_start=config.get('nonlinear_start','zero-rate'),adaptive_inner_policy=ip,anderson_policy=ap,preconditioner_reuse_policy=None if 'preconditioner_reuse_policy' not in config else atlas.PreconditionerReusePolicy(**config['preconditioner_reuse_policy']),budget=budget) as solver:
                try:
                    needs_sample = (state.step_index % config['sample_every'] == 0 and
                        (not args.resume or not any(s['step'] == state.step_index for s in last['samples'])))
                    if needs_sample:
                        flow = solver.mechanical_snapshot(state, source='R4.4 accepted endpoint '+state.state_id, cancel=cancel)
                        pending.append(atlas.tosi_state_diagnostics(state, flow, budget=budget)); save()
                    target = min(config['maximum_steps'], state.step_index+args.segment_steps)
                    while state.step_index < target:
                        if cancel.is_set(): raise CancelledError('cooperative run bound reached')
                        step = solver.advance(state, config['dt'], source=STEP_SOURCE, cancel=cancel)
                        state = step.state
                        record = state.descriptor()['step_record']
                        stage_iterations.append(dict(step=state.step_index,
                            state_id=state.state_id, input_time=record['input_time_s'],
                            dt=record['dt_s'], balances=record['balances'],
                            mechanics=record['nonlinear_mechanics']['stages']))
                        if config.get('nonlinear_start')=='previous-stage1':
                            stage_iterations[-1]['cross_step_start']=record['nonlinear_mechanics']['cross_step_start']
                        # Every accepted step retains its two-stage convergence/heat ledger.
                        if state.step_index % config['sample_every'] == 0:
                            flow = solver.mechanical_snapshot(state, source='R4.4 accepted endpoint '+state.state_id, cancel=cancel)
                            rec = atlas.tosi_state_diagnostics(state, flow, budget=budget)
                            pending.append(rec)
                            print(json.dumps(dict(time=state.time_s, step=state.step_index,
                                  elapsed_s=time.perf_counter()-start, **rec['diagnostics'])), flush=True)
                        if state.step_index % config['save_every'] == 0: save()
                    save()
                    outcome.update(status=('FINITE_SCHEDULE_COMPLETE' if state.step_index == config['maximum_steps']
                                           else 'SEGMENT_COMPLETE'))
                except CancelledError:
                    save(); outcome.update(status='CANCELLED_ACCEPTED_STATE_SAVED')
                except Exception as exc:
                    save(); outcome.update(status='FAILED_ACCEPTED_STATE_SAVED', error=str(exc),
                                            traceback=traceback.format_exc())
    except Exception as exc:
        outcome.update(status='FAILED_BEFORE_ACCEPTED_SAVE', error=str(exc), traceback=traceback.format_exc())
    finally:
        outcome.update(elapsed_s=time.perf_counter()-start,
            last_step=None if state is None else state.step_index,
            last_time=None if state is None else state.time_s,
            last_state_id=None if state is None else state.state_id,
            last_saved_step=last_saved, budget_after_close=budget.statistics())
        try:
            atomic_new(output/('invocation_'+invocation+'.json'), outcome)
        finally:
            lock.unlink(missing_ok=True)
            for sig, handler in old_handlers.items(): signal.signal(sig, handler)
    print(json.dumps(outcome), flush=True)
    return 1 if outcome['status'].startswith('FAILED') else 0


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--case', choices=('tosi-1','tosi-2','tosi-3','tosi-4','tosi-5a','tosi-5b'))
    p.add_argument('--yield-stress', type=float)
    p.add_argument('--cells', type=int)
    p.add_argument('--dt', type=float)
    p.add_argument('--max-steps', type=int)
    p.add_argument('--save-every', type=int)
    p.add_argument('--sample-every', type=int)
    p.add_argument('--max-picard', type=int)
    p.add_argument('--linear-rtol', type=float)
    p.add_argument('--momentum-tolerance', type=float)
    p.add_argument('--viscosity-rtol', type=float)
    p.add_argument('--ilu-fill-factor', type=float)
    p.add_argument('--velocity-preconditioner', choices=('auto','ilu','gmg'),
                   help='default auto: measured size/workload rule; explicit ilu/gmg for comparison')
    p.add_argument('--adaptive-inner', action='store_true', default=None,
                   help='opt-in bounded provisional linear accuracy; strict final certification')
    p.add_argument('--preconditioner-max-uses', type=int, choices=range(1,9),
                   help='Opt-in guarded request-local velocity ILU reuse; assessed value 4')
    p.add_argument('--nonlinear-solver', choices=('picard','anderson'),
                   help='Explicit safeguarded Anderson option; default remains Picard')
    p.add_argument('--nonlinear-start', choices=('zero-rate','rk-stage0','previous-stage1'),
                   help='Explicit intra-step or persisted previous-stage1 guess; default remains zero-rate')
    p.add_argument('--segment-steps', type=int, default=1000)
    p.add_argument('--seconds', type=float)
    p.add_argument('--budget-mib', type=int, default=1024)
    return p


if __name__ == '__main__':
    try:
        args = parser().parse_args()
        if not 32 <= args.budget_mib <= 4096: raise ValueError('budget admission must be 32..4096 MiB')
        raise SystemExit(main(args))
    except (ValueError, OSError, atlas.TectonicsError) as exc:
        print(json.dumps({'status':'REFUSED', 'error':str(exc), 'benchmark_accepted':False}), file=sys.stderr)
        raise SystemExit(2)
