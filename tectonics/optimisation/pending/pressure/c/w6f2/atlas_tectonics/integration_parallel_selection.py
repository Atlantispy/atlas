"""Automatic selection of optional exact-interface and fixed-wall workers.

Scheduling only. The decision uses elapsed-time observations bound to the
current source, machine and numerical settings; a worker result still enters
only through the unchanged funded adoption after the serial prefix, so the
issued bytes are those of the serial path. Unknown, stale or cheap work stays
serial, and so does any plan whose predicted saving does not pay for the
worker start-up it costs.

The first decision is made from estimates and machine/ledger hints alone: no
lease, execution context, directory or support decode, so a serial answer
leaves the workflow ledger untouched. Only a plan that passes is funded, and
its candidates are then screened exactly before anything is launched. Nothing
here raises an Exception into the scientific path: every failure is a recorded
reason to stay serial. Policies, estimates, timings and decisions never enter
an issued record, a receipt row, a measure or any identity.

Both passes of the exterior router also carry a rolling batch schedule
(integration_parallel_rolling). Its threshold is applied to the eligible work
expected in the whole pass, not to one lookahead window: the schedule reads a
bounded distance ahead, groups upcoming requests into cost-targeted batches
and gives each batch to one one-shot worker. Classes here supply its
estimates, its gates, its session and its report; the single-contact planner
below is unchanged and keeps its own first lookahead.
SPDX-License-Identifier: AGPL-3.0-only
"""
from collections import deque
from dataclasses import dataclass, fields
from itertools import combinations, islice
import math
import os
import re
from time import perf_counter

from . import integration_differential_geometry as G
from . import integration_parallel_dispatch as D
from . import integration_parallel_profile as PF
from . import integration_parallel_rolling as RB
from . import resources as R
from .integration_parallel_binding import BATCH_LIMIT
from .integration_parallel_owner import nodes_for
from .integration_parallel_results import MOMENTS, raw_capacity

DECISION_SCHEMA = 'atlas.interface-parallel-decision.v1'
MODES = ('auto', 'serial', 'off')
MAX_TIMEOUT_SECONDS = 1800.0
MAX_HORIZON = 1 << 16
SLOWEST = 16    # longest fixed-wall measures named in one call's report
OWN_WORK = 0.001    # seconds of a schedule's own work inside a contact's timing that spoil it as an observation
_SCREENED = (('decided', 'an exact shortcut decides it'), ('refused', 'the exact screen was refused'),
             ('oversize', 'its support is too large for the worker transport'))
# Where something that reads like a file-system path starts: a drive, a word
# holding a backslash, a home-relative name or an absolute POSIX name. It is
# cut from there to the end of its line.
_PATHLIKE = r'(?:[A-Za-z]:[\\/]|\S*\\|~/|(?<![\w.<])/(?=[^\s/]+/)).*'


def _real(value, low, high=math.inf):
    # An integer beyond float range is refused here, not by an OverflowError from math.isfinite.
    if type(value) is int:
        return low <= value <= min(high, 1e300)
    return type(value) is float and math.isfinite(value) and low <= value <= high


def _whole(value, low, high=None):
    return type(value) is int and value >= low and (high is None or value <= high)


def _first(row):
    return row[0]


@dataclass(frozen=True, slots=True)
class InterfaceParallelPolicy:
    """Execution only: no field changes an equation, tolerance, record or result.

    mode 'auto' observes, estimates and dispatches when that is justified;
    'serial' observes and reports but never dispatches; 'off' is the previous
    code path with no selection machinery at all. minimum_seconds is the
    conservative serial seconds of eligible work the lookahead must hold;
    minimum_job_seconds an optional per-contact floor (120 restores the
    earlier rule). workers is 1 to 6 (rolling batches; the single-contact
    planner still dispatches at most 2). A class needs minimum_samples integrator
    observations before it yields an estimate. startup_seconds and
    transfer_seconds are the measured fixed costs of one worker and of its
    parent-side handling, contention the slow-down of a worker's body,
    parent_slowdown the measured slow-down of the parent's own contacts while
    a worker is alive, and a plan must save benefit_ratio times the overhead
    it pays. child_bytes and
    predicate_units are the worker envelope, screen_bytes and screen_units the
    scratch of one exact screen. timeout_seconds is the ceiling of a plan's
    worker timeout, 4 times the high estimate plus the start-up and at least
    120 s; a contact whose worker is itself modelled to need longer than that
    (start-up plus contention times its high estimate) is never dispatched.
    ram_reserve_bytes of physical memory must remain free, the parent keeps
    one free core beside its workers, and the optional envelope may use
    budget_fraction of what the budget has available. profile_path is an
    optional observation store outside the source tree; use_exact admits
    identical earlier requests.

    batch_seconds is the expected integrator seconds one worker batch of the
    rolling schedule is cut at; None leaves both passes to the single-contact
    rule alone. batch_jobs bounds the requests of one batch and horizon the
    requests a pass may read ahead of its parent. The rolling schedule applies
    minimum_seconds to the eligible work it expects in the whole pass, and
    rates the parent's own stretches beside its workers instead of using
    parent_slowdown.
    """
    mode: str = 'auto'
    minimum_seconds: float = 120.0
    minimum_job_seconds: object = None
    workers: int = 2
    lookahead: int = 64
    minimum_samples: int = 5
    startup_seconds: float = 3.0
    transfer_seconds: float = 0.4
    contention: float = 1.3
    parent_slowdown: float = 2.5
    benefit_ratio: float = 1.0
    child_bytes: int = 512 << 20
    predicate_units: int = 1 << 34
    timeout_seconds: float = 1800.0
    ram_reserve_bytes: int = 2 << 30
    budget_fraction: float = 0.5
    screen_bytes: int = 8 << 20
    screen_units: int = 65536
    profile_path: object = None
    use_exact: bool = True
    batch_seconds: object = 20.0
    batch_jobs: int = 512
    horizon: int = 4096

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError('interface parallel mode must be auto, serial or off')
        if (not _real(self.minimum_seconds, 0) or not _real(self.startup_seconds, 0)
                or not _real(self.transfer_seconds, 0) or not _real(self.benefit_ratio, 0)
                or not _real(self.contention, 1) or not _real(self.parent_slowdown, 1)
                or self.minimum_job_seconds is not None and not _real(self.minimum_job_seconds, 0)):
            raise ValueError('finite nonnegative timing policy and slow-downs of at least one required')
        if not _real(self.timeout_seconds, 0, MAX_TIMEOUT_SECONDS) or not self.timeout_seconds:
            raise ValueError('worker timeout must be positive and at most 1800 seconds')
        if not _real(self.budget_fraction, 0, 1) or not self.budget_fraction:
            raise ValueError('budget fraction must lie in (0, 1]')
        if (not _whole(self.workers, 1, 6) or not _whole(self.lookahead, 1, D.SCAN_LIMIT)
                or not _whole(self.minimum_samples, 1)):
            raise ValueError('one to six workers, a lookahead within the scan limit and a positive sample count required')
        if (not _whole(self.child_bytes, 1) or not _whole(self.predicate_units, 1)
                or not _whole(self.ram_reserve_bytes, 0) or not _whole(self.screen_units, 1)
                or not _whole(self.screen_bytes, 1, D.PARENT_STORAGE//4)):
            raise ValueError('positive integer envelopes required; the screen scratch lies inside parent storage')
        if self.profile_path is not None and (not isinstance(self.profile_path, (str, os.PathLike))
                                              or not os.fspath(self.profile_path)):
            raise ValueError('profile path must be a file name or None')
        if type(self.use_exact) is not bool:
            raise ValueError('use_exact must be a boolean')
        if (self.batch_seconds is not None and (not _real(self.batch_seconds, 0) or not self.batch_seconds)
                or not _whole(self.batch_jobs, 1, BATCH_LIMIT)
                or not _whole(self.horizon, self.batch_jobs, MAX_HORIZON)):
            raise ValueError('a positive batch target or None, a batch within the binding limit and a '
                             'horizon of at least one batch required')


DEFAULT_POLICY = InterfaceParallelPolicy()


def _median(values):
    ordered = sorted(values)
    return (ordered[(len(ordered)-1)//2]+ordered[len(ordered)//2])/2


def class_estimate(row, minimum_samples):
    """Conservative seconds of one class row, or None while it is unknown.

    low is the lower quartile (an order statistic, never interpolated above a
    sample), mid the median and high 1.25 times the maximum of the kept
    integrator seconds; share is the observed fraction of contacts that
    reached the integrator. A class seen at least minimum_samples times and
    only ever as an exact shortcut is known and costs nothing.
    """
    integrator, shortcut = row['integrator'], row['shortcut']
    seconds = sorted(sample[0] for sample in row['samples'])
    if integrator >= minimum_samples and len(seconds) >= min(minimum_samples, PF.MAX_SAMPLES):
        return dict(basis='class', low=seconds[(len(seconds)-1)//4], mid=_median(seconds),
                    high=1.25*seconds[-1], samples=integrator, share=integrator/(integrator+shortcut))
    if not integrator and shortcut >= minimum_samples:
        return dict(basis='class', low=0.0, mid=0.0, high=0.0, samples=shortcut, share=0.0)
    return None


def exact_estimate(row):
    """Estimate from one earlier observation of the identical request."""
    if row[0] != 'integrator':
        return dict(basis='exact-request', low=0.0, mid=0.0, high=0.0, samples=1, share=0.0)
    return dict(basis='exact-request', low=0.8*row[1], mid=row[1], high=1.25*row[1], samples=1, share=1.0)


def _own(clock, work, alive, slowdown):
    """When the parent finishes ``work`` seconds of its own contacts begun at ``clock``.

    Until ``alive``, when the last worker of the plan ends, the parent runs
    ``slowdown`` times slower: the threads that watch its workers share its
    interpreter.
    """
    if clock >= alive or slowdown == 1:
        return clock+work
    fits = (alive-clock)/slowdown
    return clock+work*slowdown if work <= fits else alive+(work-fits)


def schedule(costs, eligible, *, workers, startup, transfer, contention, benefit_ratio, parent_slowdown=1.0):
    """Best set of at most ``workers`` eligible positions to dispatch; pure.

    costs are conservative serial seconds in router order, zero for unknown
    work. The parent walks the list from time zero. The k-th launched job is
    launched at k*transfer and its worker finishes startup+contention*cost
    later; the parent adopts it on reaching its position, at the later of the
    two times plus transfer. Every other position costs the parent its own
    seconds, parent_slowdown times as many while any worker of the plan is
    still alive (1 models an unaffected parent). Only one prepare exists, so
    a job at the head of the queue can never be worth a worker: the parent
    would only wait for it.

    A set pays when its saving is positive and at least benefit_ratio times
    the overhead it costs, len(set)*(startup+transfer). ``selected`` is the
    paying set with the largest saving (fewer jobs, then earlier ones, on a
    tie), so a second job that adds too little never costs the first its
    worker. ``considered`` is the set with the largest saving whether or not
    it pays; ``saving`` and ``overhead`` describe the selected set, or the
    considered one when nothing is selected.
    """
    prefix = [0.0]
    for cost in costs:
        prefix.append(prefix[-1]+cost)
    serial, best, chosen, worth, selected = prefix[-1], 0.0, (), 0.0, ()
    # Rounding may neither turn a saving of exactly nothing into a gain nor
    # let a larger set displace an equal smaller one.
    noise = 1e-9*max(1.0, serial)
    for size in range(1, min(workers, len(eligible))+1):
        for positions in combinations(sorted(eligible), size):
            ends = [order*transfer+startup+contention*costs[position] for order, position in enumerate(positions)]
            alive, clock, done = max(ends), 0.0, 0
            for position, end in zip(positions, ends, strict=True):
                clock = _own(clock, prefix[position]-prefix[done], alive, parent_slowdown)
                clock = max(clock, end)+transfer
                done = position+1
            # Work behind the last dispatched position costs the same either
            # way, so it is left out and cannot cancel against the total.
            saving = prefix[done]-clock
            if not chosen or saving > best+noise:
                best, chosen = saving, positions
            if (saving > noise and saving >= benefit_ratio*size*(startup+transfer)
                    and (not selected or saving > worth+noise)):
                worth, selected = saving, positions
    return dict(selected=selected, considered=chosen, serial_seconds=serial,
                saving=worth if selected else best, overhead=len(selected or chosen)*(startup+transfer))


def _public(text):
    """An error text as the decision record may carry it: bounded, and naming no path.

    A decision is printed and saved beside a run's artifacts, and a worker's
    stderr or an OSError names directories of this machine. The first line
    and, of a longer text such as a traceback, its last line are kept;
    whatever reads like a path is cut to the end of its line. The complete
    text stays where it was raised and on the session's ``last_error``.
    """
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if len(lines) > 2:
        lines = [lines[0], lines[-1]]
    # Each line is bounded before it is searched: more than the record keeps is never needed.
    return ' ... '.join(re.sub(_PATHLIKE, '<path>', line[:1000]) for line in lines)[:400]


def _text(error):
    return _public('%s: %s' % (type(error).__name__, error))


def _execution_mode():
    try:
        from .reuse import execution_mode
        return execution_mode()
    except Exception as error:
        return 'unavailable: '+type(error).__name__


class _Observer:
    """Per-call timing observer of the ALE router: observation, never control.

    Every hook swallows its own Exception and switches the observer off after
    the first one. Hooks read ``measured``, the issued row, and never change
    it. A contact adopted from a worker, one that waited for a worker, and one
    timed beside a running worker are not serial observations.
    """
    def __init__(self, leaves, bucket, limit):
        self.session = self.components = self.boxes = self.error = self._offered = None
        self.walls = {}
        self._off = False
        self._leaves, self._bucket, self._limit = leaves, bucket, limit
        self._wall, self._routes, self._classes, self._exact, self._phases = [0, 0.0, 0, 0.0], {}, {}, [], {}
        self._slow, self._floor = [], 0.0
        self._window = [0, 0.0, 0, 0.0]
        self._calls = self._kept = self._adopted = self._declined = self._waits = 0
        self._contended = False
        self.instrumented = False
        self._mark = perf_counter()

    def _fail(self, error):
        self._off, self.error = True, _text(error)

    def mark(self, phase):
        """Close one phase of the enclosure: seconds since the previous mark."""
        if self._off:
            return
        try:
            now = perf_counter()
            self._phases[phase] = self._phases.get(phase, 0.0)+now-self._mark
            self._mark = now
        except Exception as error:
            self._fail(error)

    def lookahead(self, components, boxes, jobs=None):
        """The router's materialised views, and the contacts its lookahead offers.

        The views are read by the estimates and the classes. ``jobs`` is the
        router's own lazy lookahead, a second instance of what a session
        scans. Only its first ``limit`` contacts can be candidates of a later
        identical call, so only they keep an exact-request observation: the
        router also visits the large groups that the lookahead skips. Without
        it the first ``limit`` interface calls stand for them.
        """
        if self._off:
            return
        try:
            self.components, self.boxes = components, boxes
            if jobs is not None:
                self._offered = {(key, name, pair.get('other_logical_cell_id'))
                                 for _, key, name, pair in islice(jobs, self._limit)}
        except Exception as error:
            self._fail(error)

    def wall(self, measured, seconds):
        if self._off:
            return
        try:
            self.instrumented = self.instrumented or PF.instrumented()
            row = self._wall
            row[0] += 1
            row[1] += seconds
            row[2] += measured.get('work_units', 0)
            if seconds > row[3]:
                row[3] = seconds
            if seconds > self._floor:
                # The few longest walls of the call, named for the report only.
                slow = self._slow
                slow.append((seconds, measured.get('logical_cell_id'), measured.get('axis'), measured.get('end'),
                             measured.get('leaves'), measured.get('work_units', 0)))
                if len(slow) > SLOWEST:
                    slow.remove(min(slow, key=_first))
                if len(slow) == SLOWEST:
                    self._floor = min(slow, key=_first)[0]
        except Exception as error:
            self._fail(error)

    def begin_interface(self):
        """Remember workers and hooks present before a contact starts.

        A worker may finish during the contact: testing only afterwards would
        teach its slowed elapsed time as an uncontended serial observation.
        """
        if self._off:
            return
        try:
            self._contended = self.session is not None and self.session.busy()
            self.instrumented = self.instrumented or PF.instrumented()
        except Exception as error:
            self._fail(error)

    def interface(self, key, name, other, measured, seconds):
        if self._off:
            return
        try:
            self.instrumented = self.instrumented or PF.instrumented()
            integrator = self._integrator(measured)
            rolling = self.__dict__.get('interface_batches')
            # This pass's rolling schedule learns what the parent itself just paid: estimates only.
            # It answers False when its own planning or launching ran inside this contact's timing.
            spoilt = rolling is not None and rolling.observed(key, other, integrator, seconds) is False
            route, clean, session = ('integrator' if integrator else 'shortcut',
                                     not (self._contended or spoilt), self.session)
            self._contended = False
            if session is not None:
                stats, waits = session.stats, session.waits
                if stats['adopted'] != self._adopted:
                    route, clean = 'adopted', False
                elif waits != self._waits or stats['declined'] != self._declined:
                    route, clean = 'waited', False
                elif session.busy():
                    clean = False
                self._adopted, self._declined, self._waits = stats['adopted'], stats['declined'], waits
            work = measured.get('work_units', 0)
            row = self._routes.get(route)
            if row is None:
                row = self._routes[route] = [0, 0.0, 0, 0.0]
            row[0] += 1
            row[1] += seconds
            row[2] += work
            if seconds > row[3]:
                row[3] = seconds
            self._calls += 1
            offered = (self._calls <= self._limit if self._offered is None
                       else (key, name, other) in self._offered)
            if offered:
                # What the lookahead window really cost, whatever was predicted.
                window = self._window
                window[0] += 1
                window[1] += seconds
                window[2] += integrator
                if seconds > window[3]:
                    window[3] = seconds
            if not clean:
                return
            self._kept += 1
            if self.components is not None:
                token = self._class_token(key, name, other)
                held = self._classes.get(token)
                if held is None:
                    held = self._classes[token] = [0, 0, deque(maxlen=PF.MAX_SAMPLES)]
                if integrator:
                    held[1] += 1
                    held[2].append([seconds, work, measured['leaves']])
                else:
                    held[0] += 1
            if offered:
                # Only these can ever be lookahead candidates of a later call.
                self._keep_exact(key, name, other, measured, route, seconds, work)
        except Exception as error:
            self._fail(error)

    def collect(self):
        """This call's observation set for the store and its summary for the report."""
        components, slowest = self.components, []
        for seconds, cell, axis, end, leaves, work in sorted(self._slow, key=_first, reverse=True):
            try:
                voxel = list(components[cell][1]['voxel_index'])
            except Exception:
                voxel = None    # no routing view was offered for it
            slowest.append(dict(seconds=round(seconds, 6), logical_cell_id=cell, voxel_index=voxel, axis=axis,
                                end=end, leaves=leaves, work_units=work))
        self.components = self.boxes = None
        observed = PF.new_observations()
        for token, (shortcut, integrator, samples) in self._classes.items():
            observed['classes'][self._class_key(token)] = dict(
                shortcut=shortcut, integrator=integrator,
                samples=[[round(seconds, 6), work, leaves] for seconds, work, leaves in samples])
        for key, (route, seconds, work, leaves) in self._exact:
            observed['exact'][key] = [route, round(seconds, 6), work, leaves]
        for target, (count, seconds, work, longest) in [(observed['walls'], self._wall)]+[
                (observed['interfaces'].setdefault(route, PF.aggregate()), row) for route, row in self._routes.items()]:
            target.update(count=count, seconds=seconds, work_units=work, max_seconds=longest)
        contacts, seconds, integrator, longest = self._window
        # The store keeps the aggregate only; the report also names the longest walls.
        return observed, dict(interfaces=observed['interfaces'], walls=dict(observed['walls'], slowest=slowest),
            phases=dict(self._phases),
            lookahead_window=dict(contacts=contacts, seconds=seconds, integrator=integrator, max_seconds=longest),
            recorded=self._kept, discarded=self._calls-self._kept, observer_error=self.error)

    def _integrator(self, measured):
        return MOMENTS in measured

    def _class_token(self, key, name, other):
        return other is not None, PF.component_walls(self.components[key][1], self.boxes, self.walls)

    def _class_key(self, token):
        return PF.class_key(self._leaves, self._bucket, *token)

    def _keep_exact(self, key, name, other, measured, route, seconds, work):
        self._exact.append((PF.exact_key(measured['support_id'], key, name, measured.get('other_support_id'),
            other, measured['max_width_m3'], measured['max_leaves']),
            [route, seconds, work, measured.get('leaves', 1)]))


class _Automatic:
    """One ALE call's selection: its session, observer, plan and decision record.

    It is also the session's planner. ``session`` and ``observer`` may each be
    None; ``finish()`` is called once, after the session is closed.
    """
    family = 'interface'

    def __init__(self):
        self.session = self.observer = self.policy = self.budget = None
        self.store = self.digest = self.code = self._context = self._owned = None
        self._rows, self._classes, self._exact, self._finished, self.workers = [], {}, False, False, 0
        self._observations_checked = False
        self.stale = False
        # Whether every gate that does not depend on a profile passed: the rolling passes ask this.
        self.admitted = False
        self.lookahead, self.screen_bytes, self.screen_units = 0, 1, 1
        self.decision = dict(schema=DECISION_SCHEMA, mode=None, route='serial', reason=None, detail=None,
            policy=None, gates=[], binding=None, profile=None,
            lookahead=dict(scanned=0, known=0, unknown=0, cheap=0, eligible=0, expected_seconds=0.0,
                           eligible_seconds=0.0, candidates=[]),
            plan=dict(selected=[], workers=0, child_bytes=None, startup_seconds=None, serial_seconds=None,
                      saving=None, overhead=None, timeout_seconds=None),
            dispatch=dict(started=0, adopted=0, declined=0, refused=[], funding=None, jobs=[],
                          peak_child_rss=0, waits=0, last_error=None),
            observations=dict(interfaces={}, walls=dict(PF.aggregate(), slowest=[]), phases={}, recorded=0, discarded=0,
                              lookahead_window=dict(contacts=0, seconds=0.0, integrator=0, max_seconds=0.0),
                              observer_error=None),
            overhead_seconds=dict(binding=0.0, estimates=0.0, resources=0.0, screens=0.0, save=0.0), notes=[])

    def _serial(self, reason, detail):
        # The first reason stands; a later one is a consequence of it.
        if self.decision['reason'] is None:
            self.decision.update(reason=reason, detail=detail)
        else:
            self.decision['notes'].append('%s: %s' % (reason, detail))

    def _gate(self, name, value, passed):
        self.decision['gates'].append(dict(gate=name, value=value, passed=passed))
        return passed

    def _open(self, budget, max_width_m3, max_leaves, policy, context, *, shared=None, store=None):
        decision = self.decision
        if policy is None:
            policy = DEFAULT_POLICY
        if type(policy) is not InterfaceParallelPolicy:
            self._gate('policy', type(policy).__name__, False)
            return self._serial('invalid policy', 'parallel must be None or an InterfaceParallelPolicy')
        self.policy, self.budget, self._context = policy, budget, context
        decision['policy'] = {field.name: getattr(policy, field.name) for field in fields(policy)}
        if policy.profile_path is not None:
            decision['policy']['profile_path'] = os.fspath(policy.profile_path)
        decision['mode'] = policy.mode
        decision['plan'].update(workers=policy.workers, child_bytes=policy.child_bytes)
        self.lookahead, self.workers = policy.lookahead, policy.workers
        self.screen_bytes, self.screen_units = policy.screen_bytes, policy.screen_units
        if policy.mode == 'off':
            return self._serial('mode', 'selection is off: the previous serial path, unobserved')
        try:
            width = G.W._q(max_width_m3)
        except ValueError:
            width = None
        plain, wide, leafy = (type(budget) is R.WorkBudget, width is not None and width >= 0,
                              type(max_leaves) is int and max_leaves >= 1)
        if not (plain and wide and leafy):
            self._gate('settings', dict(plain_budget=plain, nonnegative_width=wide, positive_leaves=leafy), False)
            return self._serial('settings', 'a plain budget, a nonnegative width and a positive leaf limit are required')
        begun = perf_counter()
        self.leaves, self.width_text = max_leaves, G._qtext(width)
        self.bucket = PF.width_bucket(width)
        self.code, loaded = ((PF.code_digest(), PF.loaded_digest()) if shared is None else
                             (shared.code, shared.decision['binding']['loaded_code']))
        # Timings are taken by the code this process LOADED, while a binding
        # is read from disk. A process that imported the package before an
        # edit neither plans from the profile of the new source nor adds its
        # timings of the old code to it.
        self.stale = loaded != self.code
        record = PF.current_binding(budget, code=self.code, family=self.family)
        self.digest = PF.binding_digest(record)
        decision['binding'] = dict(record, digest=self.digest, loaded_code=loaded, changed=False)
        self.store, note = PF.open_store(policy.profile_path) if store is None else (store, None)
        decision['profile'] = dict(PF.summary(self.store, self.digest), read_error=note, save_error=None, saved=False)
        decision['overhead_seconds']['binding'] = perf_counter()-begun
        self.observer = self._new_observer(max_leaves, self.bucket, policy.lookahead)
        if not self._gate('source', dict(loaded=loaded, current=self.code), not self.stale):
            return self._serial('source', 'the package source on disk is not the source this process imported: '
                                'its timings bind to neither, so nothing is planned from the profile or added to it')
        if not self._gate('mode', policy.mode, policy.mode == 'auto'):
            return self._serial('mode', 'policy mode is serial: observed and reported, never dispatched')
        if not self._gate('instrumentation', record['instrumented'], not record['instrumented']):
            return self._serial('instrumentation', 'registered monitoring, trace or profile hooks have no safely '
                                'reusable timing identity: observed and reported, never used as a profile')
        if not self._gate('seed', record['seed'], record['seed'] == '0'):
            return self._serial('seed', 'the interpreter did not start with PYTHONHASHSEED=0, so no worker can be bound to it')
        mode = _execution_mode()
        if not self._gate('strict-mode', mode, mode == 'strict'):
            return self._serial('strict-mode', 'workers require strict execution mode')
        if not self._gate('ledger', record['ledger'], record['ledger'] == 'predicate'):
            return self._serial('ledger', 'the legacy byte-charged work ledger cannot fund a worker')
        registered = any(node._revoker is not None for node in nodes_for((budget, budget._predicate_work)))
        if not self._gate('owner', registered, not registered):
            return self._serial('owner', 'another optional owner is registered on this budget ancestry')
        cpus = os.cpu_count() or 1
        if not self._gate('workers', dict(policy=policy.workers, logical_cpus=cpus), cpus >= 2):
            return self._serial('workers', 'one logical CPU cannot overlap a worker with its parent')
        self.admitted = True
        # Without a session the enclosure runs its unchanged serial calls: no
        # claim and no request is built per contact. So a profile that cannot
        # reach the threshold in ANY lookahead is decided here, before one exists.
        self._classes = PF.class_rows(self.store, self.digest)
        possible, known = self._possible()
        if not known:
            self._gate('profile', dict(possible_seconds=0.0), False)
            return self._serial('no compatible observations', self._unknown())
        if not self._gate('profile', dict(possible_seconds=possible), possible >= policy.minimum_seconds):
            return self._serial('eligible work below threshold',
                'no lookahead of %d contacts can hold more than %.3f s of known integrator work; threshold %.3f s'
                % (policy.lookahead, possible, policy.minimum_seconds))
        # D-j: above two workers the rolling interface batches own the interface pass; the
        # single-contact planner (at most two workers) would otherwise take it and attach
        # nothing beside itself. At one or two workers this is RC1's route unchanged.
        # A per-contact floor (minimum_job_seconds) is a single-contact rule the rolling schedule
        # does not apply, so a policy that sets one keeps RC1's route.
        if not self._gate('interface-route', dict(workers=policy.workers, batch_seconds=policy.batch_seconds,
                                                  minimum_job_seconds=policy.minimum_job_seconds),
                          policy.workers <= 2 or policy.batch_seconds is None
                          or policy.minimum_job_seconds is not None):
            return self._serial('rolling interface batches',
                'more than two workers: the single-contact planner is not opened, so the rolling '
                'interface batches own the interface pass')
        self.session = self._new_session(budget=budget, context=context, max_width_m3=max_width_m3,
            max_leaves=max_leaves, planner=self, child_bytes=policy.child_bytes,
            predicate_units=policy.predicate_units, timeout_seconds=policy.timeout_seconds)
        self.observer.session = self.session

    def _new_observer(self, leaves, bucket, lookahead):
        return _Observer(leaves, bucket, lookahead)

    def _new_session(self, **kwargs):
        return D.InterfaceParallelSession(**kwargs)

    def _candidate_class(self, key, name, pair):
        return PF.class_key(self.leaves, self.bucket, pair.get('other_logical_cell_id') is not None,
            PF.component_walls(self.observer.components[key][1], self.observer.boxes, self.observer.walls))

    def _candidate_exact(self, first, key, name, second, pair):
        return PF.exact_key(first, key, name, second, pair.get('other_logical_cell_id'), self.width_text, self.leaves)

    def _settings(self, key):
        return key.rsplit(',', 2)[0] == PF.class_key(self.leaves, self.bucket, True, 0).rsplit(',', 2)[0]

    def _possible(self):
        """Upper bound on the expected integrator seconds of any lookahead, and whether anything is known.

        Each contact contributes at most its own exact-request estimate or the
        largest class expectation of these numerical settings.
        """
        policy = self.policy
        found = [estimate for estimate in (class_estimate(row, policy.minimum_samples)
                 for key, row in self._classes.items() if self._settings(key)) if estimate is not None]
        most = max((estimate['share']*estimate['low'] for estimate in found), default=0.0)
        exact = PF.exact_rows(self.store, self.digest) if policy.use_exact else []
        self._exact = bool(exact)
        largest = sorted((exact_estimate(row)['low'] for row in exact), reverse=True)[:policy.lookahead]
        return sum(max(value, most) for value in largest)+(policy.lookahead-len(largest))*most, bool(found or exact)

    def candidates(self, scanned):
        """Stage 1 for the session: positions worth an exact screen, or none.

        Estimates and hints only: no lease, context, decode or directory. An
        empty answer is the recorded serial decision. Never raises an Exception.
        """
        try:
            return self._candidates(scanned)
        except Exception as error:
            self._serial('selection error', 'estimate failed: '+_text(error))
            return []

    def _candidates(self, scanned):
        begun = perf_counter()
        if not self._current_timing_binding():
            return []
        policy, observer, look = self.policy, self.observer, self.decision['lookahead']
        classes, exact = self._classes, self._exact
        estimates, identities, rows, expected = {}, {}, [], 0.0
        for index, (support, key, name, pair) in enumerate(scanned):
            other, found, label = pair.get('other_logical_cell_id'), None, None
            if observer.components is not None:
                label = self._candidate_class(key, name, pair)
            if exact:
                # One digest per distinct support of the lookahead, no decode.
                first, second = (None if item is None else identities.get(id(item)) or
                                 identities.setdefault(id(item), item.support_id)
                                 for item in (support, pair.get('other_support')))
                held = PF.exact_row(self.store, self.digest, self._candidate_exact(first, key, name, second, pair))
                found = None if held is None else exact_estimate(held)
            if found is None and label is not None:
                if label not in estimates:
                    estimates[label] = None if label not in classes else class_estimate(
                        classes[label], policy.minimum_samples)
                found = estimates[label]
            row = dict(index=index, paired=other is not None, basis=None, low=0.0, mid=0.0, high=0.0,
                       samples=0, share=None, screen=None, selected=False, why_not='no compatible observations')
            row['class'], row['class_digest'] = label, None if label is None else PF.class_digest(label)
            if found is not None:
                row.update(found, why_not=None if found['low'] > 0 else 'known exact shortcut')
                expected += found['share']*found['low']
            rows.append(row)
        self._rows = rows
        known = sum(row['basis'] is not None for row in rows)
        cheap = sum(row['basis'] is not None and not row['low'] for row in rows)
        look.update(scanned=len(rows), known=known, unknown=len(rows)-known, cheap=cheap,
                    expected_seconds=expected, candidates=rows)
        self.decision['overhead_seconds']['estimates'] = perf_counter()-begun
        wanted = [row['index'] for row in rows if row['low'] > 0]
        enough = bool(wanted) and expected >= policy.minimum_seconds
        self._gate('expected', dict(seconds=expected, scanned=len(rows), known=known,
                                    threshold_seconds=policy.minimum_seconds), enough)
        if not rows:
            self._serial('no candidates', 'the interface lookahead offered no contact')
        elif not known:
            self._serial('no compatible observations', self._unknown(
                () if observer.components is not None else ('no routing views were offered',)))
        elif not enough:
            self._serial('eligible work below threshold',
                'expected %.3f s of integrator work in %d known of %d scanned contacts; threshold %.3f s'
                % (expected, known, len(rows), policy.minimum_seconds))
        elif self._resources():
            return wanted
        return []

    def _unknown(self, parts=()):
        """Why nothing is known: what is stale, and what is merely not enough yet."""
        classes, stale, parts = self._classes, self.decision['profile']['stale_bindings'], list(parts)
        mine = [key for key in classes if self._settings(key)]
        if stale:
            parts.append('%d stale binding(s) ignored (other code, machine, seed, ledger or instrumentation)' % stale)
        if len(classes) > len(mine):
            parts.append('%d class(es) observed with other numerical settings are stale for this request'
                         % (len(classes)-len(mine)))
        if mine:
            parts.append('%d class(es) of these settings do not match or have fewer than %d integrator observations'
                         % (len(mine), self.policy.minimum_samples))
        return '; '.join(parts) or 'nothing is recorded under the current binding'

    def _resources(self):
        """Machine and ledger hints for the policy's workers, cut down until all fit; nothing is reserved."""
        begun = perf_counter()
        policy, budget = self.policy, self.budget
        try:
            try:
                import psutil
            except ImportError:
                self._gate('psutil', False, False)
                self._serial('psutil', 'psutil is required to watch and stop a worker')
                return False
            cores = psutil.cpu_count(logical=False) or max(1, (os.cpu_count() or 1)//2)
            logical = max(cores, psutil.cpu_count() or os.cpu_count() or cores)
            load = psutil.cpu_percent(interval=0.05)
            # Conservative on both counts. The sample is of logical CPUs, and
            # each busy one is taken to occupy a physical core of its own:
            # eight busy threads on eight cores read as half idle. And the
            # parent slept through the sample, so the core it will go on
            # using looked idle: workers need that many free cores beside it.
            busy = logical*load/100
            free = max(0.0, cores-busy)
            memory = psutil.virtual_memory().available
            one = policy.child_bytes+D.CHILD_BASELINE
            fixed = D.PARENT_STORAGE+8192+256*len(nodes_for((budget,)))
            free_bytes, free_units = budget.available_bytes, budget._predicate_work.available_bytes
            limits = (
                ('cpu', dict(physical_cores=cores, logical_cpus=logical, busy_cpus=round(busy, 2),
                             free_cores=round(free, 2), idle_cores=round(cores*(1-load/100), 2)),
                 lambda n: free >= n+1, 'fewer free cores than the parent and its workers need'),
                ('memory', dict(available_bytes=memory, per_worker_bytes=one, reserve_bytes=policy.ram_reserve_bytes),
                 lambda n: memory >= n*one+policy.ram_reserve_bytes, 'not enough free physical memory beside the reserve'),
                ('budget', dict(available_bytes=free_bytes, fixed_bytes=fixed, per_worker_bytes=one+raw_capacity(0)),
                 lambda n: fixed+n*(one+raw_capacity(0)) <= policy.budget_fraction*free_bytes,
                 'the optional envelope exceeds the allowed fraction of the available budget'),
                ('predicate units', dict(available_units=free_units, per_worker_units=policy.predicate_units),
                 lambda n: n*policy.predicate_units <= policy.budget_fraction*free_units,
                 'the worker unit envelope exceeds the allowed fraction of the available predicate units'))
            workers = policy.workers
            for name, value, fits, refusal in limits:
                while workers and not fits(workers):
                    workers -= 1
                if not self._gate(name, dict(value, workers=workers), workers > 0):
                    self._serial(name, refusal)
                    return False
            self.workers = self.decision['plan']['workers'] = workers
            return True
        finally:
            self.decision['overhead_seconds']['resources'] = perf_counter()-begun

    def context(self):
        """The caller's strict context, or one created here and closed in finish()."""
        if self._context is None:
            from .reuse import ExecutionContext
            self._context = self._owned = ExecutionContext('reference')
        return self._context

    def choose(self, screens):
        """Stage 2 for the session: positions to dispatch and their timeout.

        Eligible work is what the exact screen sent to the integrator. Never
        raises an Exception; an empty choice is the recorded serial decision.
        """
        try:
            return self._choose(screens)
        except Exception as error:
            self._serial('selection error', 'schedule failed: '+_text(error))
            return [], self.policy.timeout_seconds

    def _choose(self, screens):
        if not self._current_timing_binding():
            return [], self.policy.timeout_seconds
        policy, rows, plan = self.policy, self._rows, self.decision['plan']
        observed = [row[0] for row in PF.dispatch_rows(self.store, self.digest) if row[0] is not None]
        startup = _median(observed) if len(observed) >= 3 else policy.startup_seconds
        reasons, costs, eligible, late, floored = dict(_SCREENED), [0.0]*len(rows), [], [], 0
        for row in rows:
            outcome = row['screen'] = screens.get(row['index'])
            if outcome != 'integrator':
                if row['low'] > 0:
                    row['why_not'] = reasons.get(outcome, 'not screened')
                continue
            # The parent pays for this contact whoever runs it.
            costs[row['index']] = row['low']
            # A worker the model itself expects to outlive its plan's timeout
            # would be stopped there, its sibling revoked with it and both
            # rerun serially: all cost, no saving. The right-hand side is a
            # lower bound on the timeout of any plan that holds this contact.
            if startup+policy.contention*row['high'] > min(policy.timeout_seconds, max(120.0, 4*row['high']+startup)):
                row['why_not'] = 'cannot finish inside the worker timeout'
                late.append(row['index'])
            elif policy.minimum_job_seconds is None or row['low'] >= policy.minimum_job_seconds:
                eligible.append(row['index'])
            else:
                row['why_not'], floored = 'below the per-contact floor', floored+1
        seconds, held = sum((costs[index] for index in eligible), 0.0), sum((costs[index] for index in late), 0.0)
        sent, enough = len(eligible)+len(late)+floored, bool(eligible) and seconds >= policy.minimum_seconds
        self.decision['lookahead'].update(eligible=len(eligible), eligible_seconds=seconds)
        self._gate('eligible', dict(seconds=seconds, contacts=len(eligible), integrator_contacts=sent,
            beyond_timeout=len(late), below_floor=floored, threshold_seconds=policy.minimum_seconds), enough)
        if not enough:
            detail = ('%.3f s in %d eligible contact(s) of %d the exact screen sent to the integrator; threshold %.3f s'
                      % (seconds, len(eligible), sent, policy.minimum_seconds))
            if floored:
                detail += '; %d below the %.3f s per-contact floor' % (floored, policy.minimum_job_seconds)
            if late and seconds+held >= policy.minimum_seconds:
                # The work that would have justified workers is the work they could not finish.
                self._serial('worker timeout', '%d contact(s) holding %.3f s cannot finish inside the worker timeout '
                             'of at most %.3f s; %s' % (len(late), held, policy.timeout_seconds, detail))
            else:
                if late:
                    detail += '; %d cannot finish inside the worker timeout of at most %.3f s' % (
                        len(late), policy.timeout_seconds)
                self._serial('eligible work below threshold', detail)
            return [], policy.timeout_seconds
        # The single-contact planner's exhaustive search and its 2-thread dispatcher keep
        # their old bound; extra workers serve the rolling batches.
        found = schedule(costs, eligible, workers=min(self.workers, 2), startup=startup, transfer=policy.transfer_seconds,
                         contention=policy.contention, benefit_ratio=policy.benefit_ratio,
                         parent_slowdown=policy.parent_slowdown)
        selected = list(found['selected'])
        plan.update(workers=min(self.workers, 2), startup_seconds=startup, serial_seconds=found['serial_seconds'],
                    saving=found['saving'],
                    overhead=found['overhead'], selected=selected, timeout_seconds=None)
        for index in eligible:
            rows[index]['selected'] = index in selected
            if index not in selected:
                rows[index]['why_not'] = 'not in the best schedule'
        self._gate('benefit', dict(saving=found['saving'], overhead=found['overhead'], ratio=policy.benefit_ratio,
                                   considered=list(found['considered'])), bool(selected))
        if not selected:
            self._serial('predicted saving does not cover overheads',
                'best plan %s saves %.3f s for %.3f s of worker overhead; required ratio %.3f'
                % (list(found['considered']), found['saving'], found['overhead'], policy.benefit_ratio))
            return [], policy.timeout_seconds
        # Generous for a misprediction, yet far below the hard ceiling for ordinary plans.
        plan['timeout_seconds'] = min(policy.timeout_seconds,
                                      max(120.0, 4*max(rows[index]['high'] for index in selected)+startup))
        return selected, plan['timeout_seconds']

    def close(self):
        """Stop the rolling batch workers of either pass that are still open.

        The router closes each pass itself; this is for an enclosure that ends
        early. An unconfirmed worker shutdown propagates, as from a session.
        """
        observer = self.observer
        try:
            walls = None if observer is None else getattr(observer, 'wall_batches', None)
            if walls is not None:
                walls.close()
        finally:
            interfaces = None if observer is None else getattr(observer, 'interface_batches', None)
            if interfaces is not None:
                interfaces.close()

    def finish(self):
        """Fold the observations, save the store and record the decision.

        Called once, after the session is closed. Never raises an Exception:
        a failure here is a note in the decision, never a failed enclosure.
        """
        if self._finished:
            return
        self._finished = True
        for step in (self._finish_session, self._finish_context, self._finish_observations, self._finish_walls,
                     self._finish_interfaces):
            try:
                step()
            except Exception as error:
                self.decision['notes'].append('%s: %s' % (step.__name__, _text(error)))
        try:
            PF.record_decision(self.decision)
        except Exception:
            pass
        session = self.session
        if session is not None and session.closed:
            # This object is the closed session's planner. Left in place, the
            # pair, the observer and any context created here would be cyclic
            # garbage after every funded enclosure, kept until a full collection.
            session.planner = None
        if self.observer is not None:
            self.observer._automatic = None

    def _finish_session(self):
        session, decision = self.session, self.decision
        if session is None:
            return
        stats, plan, report = session.stats, session.plan, decision['dispatch']
        # The complete text stays on the session: a worker's stderr names source files of this machine.
        last_error = None if session.last_error is None else _public(session.last_error)
        report.update(started=stats['started'], adopted=stats['adopted'], declined=stats['declined'],
            peak_child_rss=stats['peak_child_rss'], waits=session.waits, last_error=last_error,
            refused=list(plan.get('refused', ())), funding=plan.get('funding'))
        if plan.get('cleanup'):
            # Python does not try the removal again, so say what is left and where to look.
            decision['notes'].append('session directory not removed (an atlas-interfaces- folder of the '
                                     'temporary directory still holds files): %s' % _public(plan['cleanup']))
        for outcome in session.outcomes:
            total, body = outcome['total_seconds'], outcome['body_seconds']
            report['jobs'].append(dict(outcome, startup_seconds=None if total is None or body is None
                                       else max(0.0, total-body)))
        decision['overhead_seconds']['screens'] = plan.get('screen_seconds', 0.0)
        if stats['started']:
            if decision['reason'] is not None:
                decision['notes'].append('%s: %s' % (decision['reason'], decision['detail']))
            decision.update(route='parallel', reason='selected', detail='%d worker(s) started, %d adopted, %d declined'
                            % (stats['started'], stats['adopted'], stats['declined']))
        elif decision['reason'] is not None:
            pass    # the planner's own serial decision stands
        elif not session.prepared:
            self._serial('not reached', 'the enclosure ended before its interface lookahead')
        elif plan.get('refused'):
            self._serial('worker funding refused', 'the optional worker envelope, baseline or result slot was refused')
        elif plan.get('funding'):
            self._serial('funding refused', plan['funding'])
        elif session.last_error:
            self._serial('session error', last_error)
        else:
            self._serial('not selected', 'no worker was started')

    def _finish_context(self):
        owned, self._owned = self._owned, None
        if owned is not None:
            # Every adoption was already verified against the live identity
            # at claim time; a failing close is recorded by finish().
            owned.close()

    def _current_timing_binding(self):
        """No plan may use timings after runtime or instrumentation changes."""
        record = PF.current_binding(self.budget, code=self.code, family=self.family)
        matches = (not record['instrumented'] and not self.observer.instrumented and
                   PF.binding_digest(record) == self.digest)
        if not matches:
            self._serial('timing binding changed', 'runtime or instrumentation changed during the call; '
                         'the timing profile is no longer compatible')
        return matches

    def _finish_observations(self):
        decision, observer = self.decision, self.observer
        if observer is None:
            return
        begun = perf_counter()
        observed, summary = observer.collect()
        decision['observations'].update(summary)
        for job in decision['dispatch']['jobs']:
            if job['total_seconds'] is not None:
                observed['dispatch'].append([job['startup_seconds'], job['body_seconds'],
                                             job['total_seconds'], job['adopted']])
        if not (observed['walls']['count'] or observed['interfaces'] or observed['dispatch']):
            return    # nothing was timed: no second source inventory, nothing to fold or save
        stale = self.stale
        changed = timing_changed = False
        try:
            # Timings of a call during which the package source changed bind to neither version.
            # A call that was stale from its start needs no second inventory to say so.
            changed = not stale and PF.code_digest() != self.code
            if not stale and not changed:
                current = PF.current_binding(self.budget, code=self.code, family=self.family)
                timing_changed = (PF.binding_digest(current) != self.digest or current['instrumented'] or
                                  decision['binding']['instrumented'] or observer.instrumented)
        except Exception:
            timing_changed = True
        self._observations_checked = True
        decision['overhead_seconds']['binding'] += perf_counter()-begun
        begun = perf_counter()
        if stale or changed or timing_changed:
            decision['binding']['changed'] = changed
            decision['binding']['timing_changed'] = timing_changed
            decision['observations'].update(recorded=0, discarded=summary['recorded']+summary['discarded'])
            decision['notes'].append('runtime or instrumentation changed or cannot be identified safely: '
                'its observations were discarded' if timing_changed and not (stale or changed) else
                'package source changed during the call: its observations were discarded' if changed else
                'package source differs from the source this process imported: its observations were discarded')
        else:
            PF.fold(self.store, self.digest, observed)
            error = PF.save(self.store)
            decision['profile'].update(PF.summary(self.store, self.digest), save_error=error,
                                       saved=error is None and self.store['path'] is not None)
        decision['overhead_seconds']['save'] = perf_counter()-begun

    def _finish_walls(self):
        controller = None if self.observer is None else getattr(self.observer, 'wall_batches', None)
        if controller is not None:
            controller.finish()

    def _finish_interfaces(self):
        controller = None if self.observer is None else getattr(self.observer, 'interface_batches', None)
        if controller is not None:
            controller.finish()


class _WallObserver(_Observer):
    """The same clean timing rules, for default rigid full-interval walls."""
    def _integrator(self, measured):
        # Zero-valued bounds or met=True alone prove no shortcut. These markers
        # are supplied only by the geometry issuer's exact prefix proofs.
        return not ('exact_zero_normal_flux' in measured or 'exact_zero_wall_measure' in measured)

    def _class_token(self, key, axis, end):
        return axis, end, PF.component_walls(self.components[key][1], self.boxes, self.walls)

    def _class_key(self, token):
        return PF.wall_class_key(self._leaves, self._bucket, *token)

    def _keep_exact(self, key, axis, end, measured, route, seconds, work):
        # Thousands of cheap walls must not evict the scattered expensive ones.
        # Classes still observe every clean wall; exact history remains bounded
        # by the same MAX_EXACT as interfaces and never invents an estimate.
        if route == 'integrator' and seconds >= self.exact_floor:
            self._exact.append((PF.wall_exact_key(measured['support_id'], key, axis, end,
                measured['max_width_m3'], measured['max_leaves']),
                [route, seconds, work, measured.get('leaves', 1)]))


class _AutomaticWalls(_Automatic):
    """One bounded wall batch, reusing the existing policy and funded planner."""
    family = 'wall'

    def __init__(self, batches):
        super().__init__()
        self.batches = batches

    def _new_observer(self, leaves, bucket, lookahead):
        observer = _WallObserver(leaves, bucket, lookahead)
        observer.exact_floor = self.policy.startup_seconds+self.policy.transfer_seconds
        return observer

    def _new_session(self, **kwargs):
        return D.WallParallelSession(**kwargs)

    def context(self):
        return self.batches.parent.context()

    def _settings(self, key):
        return key.rsplit(',', 3)[0] == PF.wall_class_key(self.leaves, self.bucket, 0, 0, 0).rsplit(',', 3)[0]

    def _candidate_class(self, key, axis, pair):
        return PF.wall_class_key(self.leaves, self.bucket, axis, pair['end'],
            PF.component_walls(self.observer.components[key][1], self.observer.boxes, self.observer.walls))

    def _candidate_exact(self, first, key, axis, second, pair):
        return PF.wall_exact_key(first, key, axis, pair['end'], self.width_text, self.leaves)

    def _current_timing_binding(self):
        if self.batches.instrumented or self.batches.parent.observer.instrumented:
            self._serial('timing binding changed', 'instrumentation was observed during an earlier wall batch')
            return False
        return super()._current_timing_binding()

    def finish(self):
        # The router has already confirmed shutdown. No source inventory, file
        # save or global decision entry per batch: the enclosure owns those.
        if self._finished:
            return
        self._finished = True
        try:
            self._finish_session()
            self.batches.collect(self)
        except Exception as error:
            self.batches.report['notes'].append(_text(error))
            del self.batches.report['notes'][:-PF.MAX_DECISIONS]
        finally:
            if self.session is not None and self.session.closed:
                self.session.planner = None


class _WallBatches:
    """Bounded wall history and one active session; never a whole-wall task list.

    Prior clean batches can inform later ones through a private profile copy.
    Their observations reach the real store only after the enclosing source and
    runtime checks. The root observer still reports the complete wall timings.
    """
    def __init__(self, parent):
        self.parent, self.active = parent, None
        self.components = self.boxes = None
        self.limit = parent.policy.lookahead
        self.record = PF.current_binding(parent.budget, code=parent.code, family='wall')
        self.digest = PF.binding_digest(self.record)
        self.store = parent.store
        self.working = PF.fork_store(self.store, self.digest)
        self.pending = PF.fork_store(self.store, self.digest, empty=True)
        self.instrumented = self.finished = False
        self.report = dict(family='wall', batches=0, contacts=0, started=0, adopted=0, declined=0,
            peak_child_rss=0, recorded=0, discarded=0, saved=False, reasons={}, recent=[], notes=[])

    def bind(self, components, boxes):
        self.components, self.boxes = components, boxes

    def prepare(self, jobs):
        """Offer the next at-most-lookahead jobs after closing the previous batch."""
        self.close_batch()
        jobs = list(islice(jobs, self.limit+1))
        if not jobs:
            return
        if len(jobs) > self.limit:
            raise ValueError('wall batch exceeds the policy lookahead')
        automatic = self.active = _AutomaticWalls(self)
        self.report['batches'] += 1
        self.report['contacts'] += len(jobs)
        parent = self.parent
        try:
            automatic._open(parent.budget, G.W._decode(parent.width_text), parent.leaves,
                            parent.policy, parent._context, shared=parent, store=self.working)
            if automatic.observer is not None:
                automatic.observer.lookahead(self.components, self.boxes)
            if automatic.session is not None:
                automatic.session.prepare(iter(jobs))
        except Exception as error:
            automatic._serial('selection error', _text(error))
            # A partially opened session still owns its shutdown. It stays on
            # active until close_batch confirms that every child has stopped.

    def claim(self, request, budget):
        session = None if self.active is None else self.active.session
        return None if session is None else session.claim(request, budget)

    def begin_wall(self):
        observer = None if self.active is None else self.active.observer
        if observer is not None:
            observer.begin_interface()

    def wall(self, key, axis, end, measured, seconds):
        observer = None if self.active is None else self.active.observer
        if observer is not None:
            observer.interface(key, axis, end, measured, seconds)

    def close_batch(self):
        automatic = self.active
        if automatic is None:
            return
        # Never swallow an unconfirmed worker shutdown or release funding first.
        if automatic.session is not None:
            automatic.session.close()
        automatic.finish()
        self.active = None

    def close(self):
        """End of the wall pass: with one session per window this is the last window's close."""
        self.close_batch()

    def collect(self, automatic):
        report, decision, observer = self.report, automatic.decision, automatic.observer
        if observer is not None:
            observed, summary = observer.collect()
            decision['observations'].update(summary)
            self.instrumented = self.instrumented or observer.instrumented
            valid = (not self.parent.stale and not self.instrumented and
                     automatic._current_timing_binding())
            if valid:
                for job in decision['dispatch']['jobs']:
                    if job['total_seconds'] is not None:
                        observed['dispatch'].append([job['startup_seconds'], job['body_seconds'],
                                                     job['total_seconds'], job['adopted']])
                PF.fold(self.working, self.digest, observed)
                PF.fold(self.pending, self.digest, observed)
                report['recorded'] += summary['recorded']
                report['discarded'] += summary['discarded']
            else:
                report['discarded'] += summary['recorded']+summary['discarded']
        dispatch = decision['dispatch']
        for name in ('started', 'adopted', 'declined'):
            report[name] += dispatch[name]
        report['peak_child_rss'] = max(report['peak_child_rss'], dispatch['peak_child_rss'])
        reason = decision['reason'] or 'not selected'
        report['reasons'][reason] = report['reasons'].get(reason, 0)+1
        # Eight bounded lookaheads, not a report that grows with world history.
        report['recent'].append(decision)
        del report['recent'][:-PF.MAX_DECISIONS]

    def finish(self):
        if self.finished:
            return
        self.close_batch()
        self.finished = True
        parent, report = self.parent, self.report
        binding = parent.decision['binding']
        valid = (not parent.stale and not binding.get('changed') and not binding.get('timing_changed') and
                 not self.instrumented and not self.record['instrumented'] and
                 PF.binding_digest(PF.current_binding(parent.budget, code=parent.code, family='wall')) == self.digest)
        if valid and not parent._observations_checked:
            # Standalone bounded callers may not feed the enclosure observer.
            # They still need the final source check, paid once, never per batch.
            valid = PF.code_digest() == parent.code
        if valid and self.pending['bindings']:
            PF.fold(self.store, self.digest, PF.entry_observations(self.pending, self.digest))
            error = PF.save(self.store)
            report.update(saved=error is None and self.store['path'] is not None, save_error=error)
        elif self.pending['bindings']:
            report['discarded'] += report['recorded']
            report['recorded'] = 0
            report['notes'].append('wall observations discarded after source/runtime/instrumentation change')
        report['profile'] = PF.summary(self.store, self.digest)
        parent.decision['wall_parallel'] = report
        if report['started']:
            parent.decision['interface_route'] = {name: parent.decision[name] for name in ('route', 'reason', 'detail')}
            parent.decision.update(route='parallel', reason='wall batches selected',
                detail='%d wall worker(s) started, %d adopted, %d declined across %d batches' % (
                    report['started'], report['adopted'], report['declined'], report['batches']))
        self.components = self.boxes = self.parent = None


class _Rolling:
    """One pass's rolling batch schedule: its estimates, gates, session and report.

    Estimates are transient and belong to this pass alone. They start from the
    class rows and identical requests of the stored binding and then also take
    what the parent itself pays in this pass, uncontended or not: a pass whose
    workers are busy must still learn the classes it meets. A request that a
    worker answered is counted in its class without a timing, so that the
    share of a class that reaches the integrator stays that of all its
    requests and not only of those the parent ran. None of that is stored.
    The store is taught only by the observers and their clean-timing rules,
    exactly as without a schedule.
    """
    family, adoption = None, 1.0

    def __init__(self, parent):
        policy = self.policy = parent.policy
        self.parent, self.session, self.schedule = parent, None, None
        self.components = self.boxes = None
        self.record = PF.current_binding(parent.budget, code=parent.code, family=self.family)
        self.digest = PF.binding_digest(self.record)
        self.rows, self.labels, self.cache, self.walls = {}, {}, {}, {}
        self.identities, self.total, self.closed, self.finished = {}, 0, False, False
        # Two supports for each request in sight: a plan never empties the cache under its own feet.
        self.cached = 2*policy.horizon+64
        self.workers, self.gates, self.notes = policy.workers, [], []
        self.exact = policy.use_exact and bool(PF.exact_rows(parent.store, self.digest))
        self.prefix = [0, 0.0]    # exact-prefix count and seconds: the parent's own shortcuts
        self._mark = None
        try:
            self._seed()
        except Exception as error:
            self.notes.append('stored estimates unreadable: '+_text(error))
        self.reason = self._admission()
        if self.reason is None:
            self.schedule = RB.Schedule(session=self._open, estimate=self._expect, beyond=self._beyond,
                gate=self._current, shippable=self._shippable, weigh=self._weigh,
                capacity=D.MAX_BATCH_INPUT, adoption=self.adoption,
                workers=policy.workers, batch_seconds=policy.batch_seconds, batch_jobs=policy.batch_jobs,
                horizon=policy.horizon, minimum_seconds=policy.minimum_seconds,
                startup_seconds=policy.startup_seconds, transfer_seconds=policy.transfer_seconds,
                contention=policy.contention, benefit_ratio=policy.benefit_ratio,
                timeout_seconds=policy.timeout_seconds)

    def _admission(self):
        """Why this pass may not schedule at all, or None. The profile-free gates of the enclosure."""
        parent = self.parent
        if self.policy.batch_seconds is None:
            return 'batches off', 'policy batch_seconds is None: the single-contact rule alone'
        if not parent.admitted:
            return 'enclosure gate', 'the enclosure decided %s before any profile was read' % (
                parent.decision['reason'] or 'serial')
        if self.record['instrumented'] or parent.observer is None or parent.observer.instrumented:
            return 'instrumentation', 'registered monitoring, trace or profile hooks: observed, never scheduled'
        return None

    def _seed(self):
        """Class rows of these numerical settings under the stored binding, and its typical exact prefix."""
        for key, row in PF.class_rows(self.parent.store, self.digest).items():
            if self._settings(key):
                self.rows[key] = [row['shortcut'], row['integrator'],
                                  deque((sample[0] for sample in row['samples']), maxlen=PF.MAX_SAMPLES)]
        held = PF.entry_observations(self.parent.store, self.digest)['interfaces'].get('shortcut')
        if held and held['count']:
            self.prefix = [held['count'], held['seconds']]

    def _expect(self, label):
        if label not in self.cache:
            row = self.rows.get(label)
            # Requests at least as long as a worker's fixed cost are remembered one by one:
            # the class describes the others.
            self.cache[label] = None if row is None else RB.expectation(
                row[0], row[1], row[2], self.policy.minimum_samples,
                ceiling=self.policy.startup_seconds+self.policy.transfer_seconds)
        return self.cache[label]

    def _learn(self, label, integrator, seconds):
        row = self.rows.get(label)
        if row is None:
            if len(self.rows) >= PF.MAX_CLASSES:
                return
            row = self.rows[label] = [0, 0, deque(maxlen=PF.MAX_SAMPLES)]
        if integrator:
            row[1] += 1
            if seconds is not None:
                row[2].append(seconds)
        else:
            row[0] += 1
            if seconds is not None:
                self.prefix[0] += 1
                self.prefix[1] += seconds
        self.cache.pop(label, None)

    def _typical_prefix(self):
        return self.prefix[1]/self.prefix[0] if self.prefix[0] else 0.0

    def _facts(self, support):
        """[support, its id, its transport weight once asked for] per distinct support of the pass."""
        if getattr(support, '_compact_ref', None) is not None:
            # A temporary native support of a compact partition: keep its handle.
            from partition_routing_patch import rolling_facts
            return rolling_facts(self, support)
        found = self.identities.get(id(support))
        if found is None or found[0] is not support:
            if len(self.identities) >= self.cached:
                self.identities.clear()
            found = self.identities[id(support)] = [support, support.support_id, False]
        return found

    def _identity(self, support):
        """One digest per distinct support of the pass, no decode."""
        return self._facts(support)[1]

    def _weight(self, support):
        """(support id, encoded bytes) of a support the optional transport takes, else None."""
        found = self._facts(support)
        if found[2] is False:
            found[2] = D.transport(support)
        return found[2]

    def _shippable(self, job):
        other = job[3].get('other_support')
        return self._weight(job[0]) is not None and (other is None or self._weight(other) is not None)

    def _weigh(self, job):
        other = job[3].get('other_support')
        return (self._weight(job[0]),) if other is None else (self._weight(job[0]), self._weight(other))

    def _beyond(self):
        return 0

    def _current(self):
        """Per launch: the timing binding still stands and nothing instruments the parent."""
        parent = self.parent
        record = PF.current_binding(parent.budget, code=parent.code, family=self.family)
        if record['instrumented'] or parent.observer.instrumented or PF.binding_digest(record) != self.digest:
            return 'timing binding changed', 'runtime or instrumentation changed during the pass'
        return None

    def _machine(self):
        """The unfunded machine and ledger gates of the single-contact planner, for this pass."""
        probe = _Automatic()
        probe.policy, probe.budget = self.policy, self.parent.budget
        probe.workers = self.policy.workers
        admitted = probe._resources()
        self.gates = probe.decision['gates']
        self.workers = probe.workers if admitted else 0
        return None if admitted else (probe.decision['reason'], probe.decision['detail'])

    def _open(self):
        """The schedule's first batch is worth starting: machine gates, then the funded session."""
        refusal = self._machine()
        if refusal is not None:
            self.notes.append('%s: %s' % refusal)
            return None
        parent, policy = self.parent, self.policy
        session = D.BatchParallelSession(budget=parent.budget, max_width_m3=G.W._decode(parent.width_text),
            max_leaves=parent.leaves, wall=self.family == 'wall', workers=self.workers,
            child_bytes=policy.child_bytes, predicate_units=policy.predicate_units,
            timeout_seconds=policy.timeout_seconds, budget_fraction=policy.budget_fraction)
        self.schedule.workers = self.workers
        # Known to this pass before it funds anything: whatever interrupts its opening, the
        # pass's close reaches it.
        self.session = session
        if not session.open(parent.context):
            self.session = None
            self.notes.append('session: %s' % (session.plan.get('funding') or _public(session.last_error or 'not opened')))
            return None
        self._attached(session)
        return session

    def _attached(self, session):
        pass

    def _begin(self):
        session = self.session
        if session is not None:
            self._mark = session.stats['adopted'], session.stats['declined'], session.waits

    def _paid(self, label, integrator, seconds):
        """The request the parent just finished: what the pass's estimates and its schedule learn of it."""
        if self._own():
            # The parent ran it itself: its stretch is rated against the estimate it had, then learned.
            if self.schedule is not None:
                self.schedule.ran(seconds)
            self._learn(label, integrator, seconds)
        elif self._adopted():
            self._learn(label, integrator, None)

    def _own(self):
        """Whether the parent itself computed the request it just finished."""
        session, mark = self.session, self._mark
        return session is None or mark is None or mark == (
            session.stats['adopted'], session.stats['declined'], session.waits)

    def _adopted(self):
        """Whether the request the parent just finished is a worker's result, adopted."""
        session, mark = self.session, self._mark
        return (session is not None and mark is not None and
                (session.stats['adopted'], session.stats['declined']) == (mark[0]+1, mark[1]))

    def claim(self, request, budget):
        session = self.session
        return None if session is None else session.claim(request, budget)

    def close(self):
        """End of the pass: every worker is confirmed stopped before anything is returned.

        May be called again. After an interrupt or an unconfirmed shutdown in
        the router's close, the enclosure's own close finishes what is left:
        nothing here is marked done before it is done.
        """
        self.closed = True      # nothing more is scheduled
        # The weights name issued supports: a closed pass keeps none alive.
        self.identities.clear()
        if self.schedule is not None:
            self.schedule.close()
        session = self.session
        if session is not None and not session.closed:
            # An unconfirmed worker shutdown propagates from here, as from any session.
            session.close()

    def summary(self):
        """The pass's bounded report; called once, after close()."""
        session, schedule = self.session, self.schedule
        report = dict(family=self.family, binding=self.digest, workers=self.workers, gates=self.gates,
            notes=[_public(note) for note in self.notes[-PF.MAX_DECISIONS:]], prefix_seconds=self._typical_prefix(),
            classes=len(self.rows), exact=self.exact, offered=self.total,
            route='serial', reason=None if self.reason is None else self.reason[0],
            detail=None if self.reason is None else self.reason[1], schedule=None,
            started=0, jobs=0, results=0, decided=0, adopted=0, declined=0, refused=0, waits=0,
            peak_child_rss=0, peak_child_ledger=0, last_error=None, batches=[])
        if schedule is not None:
            planned = schedule.report()
            if planned['stopped'] == 'session not opened' and self.notes:
                planned['detail'] = self.notes[-1]      # which gate, lease or owner refused
            # A stop reason may quote a worker's error, which names directories of this machine.
            planned['detail'] = None if planned['detail'] is None else _public(planned['detail'])
            report.update(schedule=planned, route=planned['route'], reason=planned['reason'], detail=planned['detail'])
        if session is not None:
            stats = session.stats
            report.update(started=stats['started'], jobs=stats['jobs'], results=stats['results'],
                decided=stats['decided'], adopted=stats['adopted'], declined=stats['declined'],
                refused=stats['refused'], waits=session.waits, peak_child_rss=stats['peak_child_rss'],
                last_error=None if session.last_error is None else _public(session.last_error),
                batches=list(session.log)[-PF.MAX_DECISIONS:], peak_child_ledger=stats['peak_child_ledger'])
            if session.plan.get('cleanup'):
                report['notes'].append('session directory not removed: %s' % _public(session.plan['cleanup']))
        return report

    def _promote(self, report, label):
        """A pass that started workers is the enclosure's route; the earlier decision is kept beside it."""
        decision = self.parent.decision
        # Both passes' batch workers in one place: 'dispatch' counts the single-contact route only.
        total = decision.setdefault('batch_workers', dict(started=0, jobs=0, results=0, decided=0, adopted=0,
            declined=0, refused=0, peak_child_rss=0, peak_child_ledger=0,
            parent_seconds=dict(planning=0.0, launch=0.0, receive=0.0, adopt=0.0, waited=0.0)))
        for name in ('started', 'jobs', 'results', 'decided', 'adopted', 'declined', 'refused'):
            total[name] += report[name]
        for name in ('peak_child_rss', 'peak_child_ledger'):
            total[name] = max(total[name], report[name])
        planned = report['schedule'] or {}
        total['parent_seconds']['planning'] += planned.get('planning_seconds') or 0.0
        for name, seconds in (planned.get('parent_seconds') or {}).items():
            total['parent_seconds'][name] += seconds
        if report['started']:
            detail = '%d %s worker(s) started for %d request(s): %d adopted, %d declined' % (
                report['started'], self.family, report['jobs'], report['adopted'], report['declined'])
            if decision['reason'] == 'wall batches selected':
                label, detail = 'wall and interface batches selected', '%s; %s' % (decision['detail'], detail)
            else:
                decision['interface_route'] = {name: decision[name] for name in ('route', 'reason', 'detail')}
            decision.update(route='parallel', reason=label, detail=detail)


class _RollingWalls(_Rolling):
    """The wall pass. One observer per router window keeps the clean-timing rules of the store."""
    family = 'wall'

    def __init__(self, parent):
        super().__init__(parent)
        self.limit = min(parent.policy.lookahead, parent.policy.horizon)
        # Router windows the pass may be shown ahead of the one being walked: as many as its
        # horizon would hold if every wall were a query. A window without queries counts too.
        # A partial extra window would exceed the declared query horizon.
        # Keep whole windows within it; the normal 4096/64 policy is unchanged.
        self.ahead = parent.policy.horizon//self.limit
        self.store = parent.store
        self.pending = PF.fork_store(self.store, self.digest, empty=True)
        self.window = None
        self.instrumented = False
        self.seen = [0, 0, None]    # components and queries offered so far, and the last component
        self.report = dict(family='wall', batches=0, contacts=0, started=0, adopted=0, declined=0,
            peak_child_rss=0, recorded=0, discarded=0, saved=False, reasons={}, recent=[], notes=[])

    def _settings(self, key):
        return key.rsplit(',', 3)[0] == PF.wall_class_key(self.parent.leaves, self.parent.bucket, 0, 0, 0).rsplit(',', 3)[0]

    def bind(self, components, boxes):
        self.components, self.boxes = components, boxes

    def _label(self, key, axis, end):
        token = axis, end, PF.component_walls(self.components[key][1], self.boxes, self.walls)
        label = self.labels.get(token)
        if label is None:
            label = self.labels[token] = PF.wall_class_key(self.parent.leaves, self.parent.bucket, *token)
        return label

    def _beyond(self):
        components, queries, _ = self.seen
        left = len(self.components)-components
        return left*queries/components if components and left > 0 else 0

    def hungry(self):
        return not self.closed and self.schedule is not None and self.schedule.hungry()

    def offer(self, events):
        """One later router window, metadata only: its queries join the lookahead in order."""
        schedule, seen = self.schedule, self.seen
        if schedule is None or self.closed or schedule.stopped is not None:
            return
        try:
            prefix = self._typical_prefix()
            for event in events:
                if 'error' in event:
                    break
                key = event['key']
                if key != seen[2]:
                    seen[0], seen[2] = seen[0]+1, key
                if not event['query']:
                    continue
                seen[1] += 1
                self.total += 1
                support, axis, end = event['support'], event['axis'], event['end']
                exact = None
                if self.exact:
                    held = PF.exact_row(self.store, self.digest, PF.wall_exact_key(
                        self._identity(support), key, axis, end, self.parent.width_text, self.parent.leaves))
                    if held is not None:
                        exact = (held[1], 1.25*held[1]) if held[0] == 'integrator' else (0.0, 0.0)
                schedule.offer((support, key, axis, dict(end=end)), prefix, self._label(key, axis, end), exact)
        except Exception as error:
            schedule._stop('schedule error', _text(error))

    def prepare(self, jobs):
        """The router enters a window: its clean timings are observed as one bounded set."""
        self.close_batch()
        jobs = list(islice(jobs, self.limit+1))
        if len(jobs) > self.limit:
            raise ValueError('wall batch exceeds the policy lookahead')
        if not jobs:
            return
        self.report['batches'] += 1
        self.report['contacts'] += len(jobs)
        observer = self.window = _WallObserver(self.parent.leaves, self.parent.bucket, self.limit)
        observer.exact_floor = self.policy.startup_seconds+self.policy.transfer_seconds
        self._follow(observer, self.session)
        observer.lookahead(self.components, self.boxes)

    @staticmethod
    def _follow(observer, session):
        """A window's observer joins a session of the whole pass: it counts from where that session is.

        Counting from zero, the first wall of every window after the first
        adoption or wait would be filed as adopted or waited.
        """
        observer.session = session
        if session is not None:
            observer._adopted, observer._declined = session.stats['adopted'], session.stats['declined']
            observer._waits = session.waits

    def _attached(self, session):
        if self.window is not None:
            self._follow(self.window, session)

    def begin_wall(self):
        schedule = self.schedule
        if schedule is not None:
            schedule.reached()
            schedule.advance()
        self._begin()
        if self.window is not None:
            self.window.begin_interface()

    def wall(self, key, axis, end, measured, seconds):
        if self.window is not None:
            self.window.interface(key, axis, end, measured, seconds)
        if self.schedule is not None:
            try:
                self._paid(self._label(key, axis, end), not ('exact_zero_normal_flux' in measured
                           or 'exact_zero_wall_measure' in measured), seconds)
            except Exception as error:
                self.schedule._stop('schedule error', _text(error))

    def close_batch(self):
        """The router leaves a window: fold its clean observations. Workers keep running."""
        observer, self.window = self.window, None
        if observer is None:
            return
        report = self.report
        try:
            observed, summary = observer.collect()
            self.instrumented = self.instrumented or observer.instrumented
            if not self.parent.stale and not self.instrumented:
                PF.fold(self.pending, self.digest, observed)
                report['recorded'] += summary['recorded']
                report['discarded'] += summary['discarded']
            else:
                report['discarded'] += summary['recorded']+summary['discarded']
        except Exception as error:
            report['notes'].append(_text(error))
            del report['notes'][:-PF.MAX_DECISIONS]

    def close(self):
        self.close_batch()
        super().close()

    def finish(self):
        """Commit the pass's clean observations after the enclosure's source and runtime checks."""
        if self.finished:
            return
        self.finished = True
        try:
            self.close()
        except Exception as error:
            # The router and the enclosure already closed this pass; this is a second attempt only.
            self.notes.append('close: '+_text(error))
        parent, report = self.parent, self.report
        binding = parent.decision['binding']
        valid = (not parent.stale and not binding.get('changed') and not binding.get('timing_changed') and
                 not self.instrumented and not self.record['instrumented'] and
                 PF.binding_digest(PF.current_binding(parent.budget, code=parent.code, family='wall')) == self.digest)
        if valid and not parent._observations_checked:
            valid = PF.code_digest() == parent.code
        if valid and self.pending['bindings']:
            PF.fold(self.store, self.digest, PF.entry_observations(self.pending, self.digest))
            error = PF.save(self.store)
            report.update(saved=error is None and self.store['path'] is not None, save_error=error)
        elif self.pending['bindings']:
            report['discarded'] += report['recorded']
            report['recorded'] = 0
            report['notes'].append('wall observations discarded after source/runtime/instrumentation change')
        report['profile'] = PF.summary(self.store, self.digest)
        rolling = self.summary()
        for name in ('started', 'adopted', 'declined', 'peak_child_rss'):
            report[name] = rolling[name]
        # 'batches' keeps its earlier meaning, the router's windows; the workers are under 'rolling'.
        report['windows'], report['rolling'] = report['batches'], rolling
        report['reasons'] = dict((rolling['schedule'] or {}).get('reasons') or
                                 {rolling['reason'] or 'not selected': 1})
        parent.decision['wall_parallel'] = report
        self._promote(rolling, 'wall batches selected')
        self.components = self.boxes = self.parent = self.session = self.schedule = None


class _RollingInterfaces(_Rolling):
    """The moving-interface pass. The enclosure's own observer keeps the store's clean-timing rules."""
    family, adoption = 'interface', 0.5

    def __init__(self, parent, jobs):
        self.order, self.jobs, self.left = deque(), None, 0
        self._spent = 0.0       # the schedule's own seconds inside the contact being timed
        super().__init__(parent)
        observer = parent.observer
        self.components, self.boxes = observer.components, observer.boxes
        if self.schedule is not None and self.components is None:
            self.schedule, self.reason = None, ('no routing views', 'the router offered no views to label contacts')
        if self.schedule is not None:
            # One instance of the lazy lookahead is only counted, a second is read as the parent moves.
            self.left = sum(1 for _ in jobs())
            self.jobs = jobs()
            self._fill()

    def _settings(self, key):
        return key.rsplit(',', 2)[0] == PF.class_key(self.parent.leaves, self.parent.bucket, True, 0).rsplit(',', 2)[0]

    def _label(self, key, paired):
        token = paired, PF.component_walls(self.components[key][1], self.boxes, self.walls)
        label = self.labels.get(token)
        if label is None:
            label = self.labels[token] = PF.class_key(self.parent.leaves, self.parent.bucket, *token)
        return label

    def _beyond(self):
        return self.left

    def _fill(self):
        """Read the lazy lookahead only as far as the schedule asks; never past its horizon."""
        schedule, jobs = self.schedule, self.jobs
        if schedule is None or jobs is None:
            return
        try:
            prefix = self._typical_prefix()
            while schedule.hungry():
                job = next(jobs, None)
                if job is None:
                    self.jobs, self.left = None, 0
                    return
                self.left -= 1
                self.total += 1
                support, key, name, pair = job
                other = pair.get('other_logical_cell_id')
                exact = None
                if self.exact:
                    held = PF.exact_row(self.parent.store, self.digest, PF.exact_key(
                        self._identity(support), key, name,
                        None if pair.get('other_support') is None else self._identity(pair['other_support']),
                        other, self.parent.width_text, self.parent.leaves))
                    if held is not None:
                        exact = (held[1], 1.25*held[1]) if held[0] == 'integrator' else (0.0, 0.0)
                self.order.append((key, name, other))
                schedule.offer(job, prefix, self._label(key, other is not None), exact)
        except Exception as error:
            schedule._stop('schedule error', _text(error))

    def _attached(self, session):
        # The enclosure's observer must not teach the store a timing taken beside these workers.
        self.parent.observer.session = session

    def claim(self, request, budget):
        """The issuer's seam for every contact: where the parent is, then its funded result if any."""
        schedule = self.schedule
        if schedule is not None and not self.closed:
            begun = perf_counter()
            order = self.order
            if order and order[0] == (request['logical_cell_id'], request['constraint_name'],
                                      request['other_logical_cell_id']):
                order.popleft()
                schedule.reached()
            else:
                schedule.unlisted()
            self._fill()
            schedule.advance()
            # This seam lies inside the contact's timing: a plan, a launch or the opening of the
            # session made here is the schedule's work, not the contact's.
            self._spent = perf_counter()-begun
        self._begin()
        return super().claim(request, budget)

    def observed(self, key, other, integrator, seconds):
        """From the enclosure's observer, after each contact: what the parent itself just paid.

        False when the schedule's own work ran inside this contact's timing:
        the pass then learns the contact without those seconds, and the
        observer keeps the timing out of the store.
        """
        spent, self._spent = self._spent, 0.0
        clean = spent < OWN_WORK
        if self.schedule is not None and not self.closed:
            self._paid(self._label(key, other is not None), integrator, seconds if clean else max(0.0, seconds-spent))
        return clean

    def finish(self):
        if self.finished:
            return
        self.finished = True
        try:
            self.close()
        except Exception as error:
            self.notes.append('close: '+_text(error))
        rolling = self.summary()
        self.parent.decision['interface_batches'] = rolling
        self._promote(rolling, 'interface batches selected')
        self.components = self.boxes = self.parent = self.session = self.schedule = self.jobs = None


def open_wall_batches(observer, components, boxes):
    """Lazily attach wall scheduling to the ordinary automatic enclosure only."""
    parent = getattr(observer, '_automatic', None)
    if parent is None:
        return None
    controller = getattr(observer, 'wall_batches', None)
    if controller is None:
        try:
            rolling = parent.policy is not None and parent.policy.batch_seconds is not None
            controller = observer.wall_batches = (_RollingWalls if rolling else _WallBatches)(parent)
        except Exception as error:
            parent.decision['notes'].append('wall selection unavailable: '+_text(error))
            return None
    controller.bind(components, boxes)
    return controller


def open_interface_batches(observer, session, jobs):
    """Attach the rolling interface pass, or None. ``jobs()`` gives a fresh lazy lookahead.

    A single-contact session that the enclosure opened and that is still open
    after its one prepare owns this pass, and nothing is attached beside it:
    the budget has room for one optional owner. One that decided serial there
    has closed, and leaves the pass to the batches. Never raises an Exception.
    """
    parent = getattr(observer, '_automatic', None)
    if (parent is None or session is not None and not getattr(session, 'closed', False)
            or parent.policy is None or parent.policy.batch_seconds is None):
        return None
    try:
        controller = observer.interface_batches = _RollingInterfaces(parent, jobs)
    except Exception as error:
        parent.decision['notes'].append('interface batches unavailable: '+_text(error))
        return None
    return controller


def open_automatic(*, budget, max_width_m3, max_leaves, policy=None, context=None):
    """Selection for one ALE call: ``.session``, ``.observer`` and ``.finish()``.

    Either part may be None: no interface session leaves that pass serial;
    the observer lazily attaches bounded wall sessions to the wall pass. No
    observer means nothing is timed. ``context`` is the caller's strict
    reference ExecutionContext, if it holds one. Never raises an Exception:
    whatever goes wrong here is a recorded reason to stay serial.
    """
    automatic = _Automatic()
    try:
        automatic._open(budget, max_width_m3, max_leaves, policy, context)
        if automatic.observer is not None:
            automatic.observer._automatic = automatic
    except Exception as error:
        automatic.session = automatic.observer = None
        automatic._serial('selection error', _text(error))
    return automatic


def last_decision():
    """Detached copy of this process's most recent selection decision, or None."""
    return PF.last_decision()


def decisions():
    """Detached copies of this process's last decisions, oldest first (at most eight)."""
    return PF.decisions()
