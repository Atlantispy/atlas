"""I02.4 one accepted clock for the first I02 route: candidate, coupled checks, atomic commit. WORKING NON-CANON.

A Clock advances a ledger's accepted head by whole steps of the history's fixed global schedule. Each candidate step
is the package-owned coupled core (integration_state.Continuation and its one prepared runner) applied to the current
accepted state, with its retained window, temperature-step, constitutive and deadline checks; accepted steps are
published only as ledger commits, whose single transaction also carries every account and any attached stocks at the
same time. Nothing advances ahead of the accepted parent, and no participant publishes on its own.

Requests name a whole number of steps or a whole-step end time; the schedule dt = duration/steps is never recomputed
from a request, and accepted prefixes are never replayed. Savepoints are global step indices of that schedule. The
step index, its cumulative ceiling of at most 256, the 1e14 s horizon, the windows and the 5 K guard belong to the
settings and cannot be reset by a request, a savepoint, a failure or a new clock. The event calendar is declared
with the ledger, so every clock of the history honours it, and requests may add savepoints only. This route supports
prescribed savepoints: any other declared event stops the clock at the last whole step not after it, rather than
stepping past physics this route does not represent, and the ledger refuses any commit that would. Each transfer
declares the interval of whole steps it was produced for, and the clock commits exactly that interval with it, so the
interval's steps and its exchange are accepted together or not at all. A cancellation, retained refusal, expired
budget or exception commits the whole steps already accepted, except those of a transfer interval not yet complete,
and reports (or keeps) the last accepted time; a competing writer's commit makes this clock stale. A schedule whose
step boundaries are not all distinct at its epoch is refused. Storage never chooses a physical step.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import integration_ledger as _ledger
from . import integration_state as _state
from ._validation import TectonicsError, scalar
from .timebase import advance_time


SAVEPOINT = 'savepoint'
SUPPORTED_EVENTS = _ledger.SUPPORTED_EVENTS
COMPLETED = 'COMPLETED'                          # the requested whole steps were accepted and committed
HISTORY_COMPLETE = _state.HISTORY_COMPLETE       # ... and they finish the declared schedule
CANCELLED = 'CANCELLED'
REFUSED_UNSUPPORTED_EVENT = 'REFUSED_UNSUPPORTED_EVENT'
REFUSED_STALE_PARENT = 'REFUSED_STALE_PARENT'
REFUSED_EXCHANGE = 'REFUSED_EXCHANGE'           # its interval's steps not committed, or a rival record of them adopted
# Retained refusals of the coupled core pass through unchanged: REFUSED_STRETCH_WINDOW, REFUSED_TEMPERATURE_WINDOW,
# REFUSED_TEMPERATURE_STEP, REFUSED_CONSTITUTIVE and REFUSED_DEADLINE.


class ClockError(TectonicsError):
    """A request the fixed schedule cannot honour (fractional, beyond the cumulative limit, past event); nothing ran."""


@dataclass(frozen=True, slots=True)
class Event:
    """One calendar entry at an absolute epoch time: declared with a ledger, or a savepoint of one request.

    Kinds and labels are ASCII tokens. Only savepoints are supported by this route.
    """
    time_s: float
    kind: str
    label: str

    def __post_init__(self):
        if isinstance(self.time_s, bool):
            raise ClockError('an event time is a real number')
        object.__setattr__(self, 'time_s', scalar(self.time_s, 'event time'))
        _ledger._token(self.kind, 'event kind')
        _ledger._token(self.label, 'event label')


@dataclass(frozen=True, eq=False, init=False, slots=True)
class Outcome(_state._Immutable):
    """The result of one request. ``head`` is the last accepted commit and ``time_s``/``step`` its accepted time.

    ``accepted_steps`` whole steps were accepted and committed by this request, in ``commits``; ``status`` is
    COMPLETED, HISTORY_COMPLETE, CANCELLED, REFUSED_UNSUPPORTED_EVENT (with ``event``), REFUSED_EXCHANGE,
    REFUSED_STALE_PARENT or a retained refusal of the coupled core with its ``reason``. What stopped the request
    decides the status; a commit that succeeds only on its retry does not change it. Steps computed inside a declared
    transfer interval are committed only together with its exchange: a refused exchange, or a stop inside the interval,
    leaves them uncommitted and the reason says so. A record of the same steps that another writer committed with other
    transfers is adopted as the head instead, and the reason names it: at a savepoint commit the status is
    REFUSED_EXCHANGE, while after an early stop, including one at an unsupported event, the stop's status is kept.
    Every other accepted step is committed.
    """
    status: str
    reason: str | None
    requested_steps: int
    accepted_steps: int
    head: object
    time_s: float
    step: int
    commits: tuple
    event: Event | None

    def __init__(self, *args, **kwargs):
        raise TypeError('Outcome is issued by Clock.advance() only')


def _issue(cls, **values):
    item = object.__new__(cls)
    for key, value in values.items():
        object.__setattr__(item, key, value)
    return item


def _cancelled(cancel):
    if cancel is None:
        return lambda: False
    if hasattr(cancel, 'is_set'):
        if not callable(cancel.is_set):
            raise ClockError('cancel is an event with is_set() or a callable')
        return cancel.is_set
    if callable(cancel):
        return cancel
    raise ClockError('cancel is an event with is_set() or a callable')


def _deadline(value):
    if value is None:
        return None
    if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value):
        raise ClockError('a deadline is a finite perf_counter instant in seconds')
    return float(value)


class Clock:
    """The accepted clock of one ledger, prepared at its current head: operators are rebuilt once and reused.

    One Continuation serves every request, so consecutive whole steps continue its warm endpoint stage exactly as an
    uninterrupted run would. A new clock starts cold: its first step re-solves the head's endpoint stage (unbooked), so
    a history continued in another process agrees with an uninterrupted one within the retained parity, not bitwise.
    The same holds for the request after one whose accepted steps could not be committed (a refused exchange, a stop
    inside a transfer interval or a failed commit): the warm entry is then ahead of the head. A commit whose outcome
    could not be read is settled at the clock's next request, which adopts the clock's own record if it was published.
    Not thread-safe; one writer per clock. A clock whose head was overtaken refuses further requests: open a new clock
    at the accepted head.
    """
    __slots__ = ('_ledger', '_head', '_state', '_run', '_stale', '_unsettled')

    def __init__(self, ledger, *, head=None, budget=None):
        if type(ledger) is not _ledger.Ledger:
            raise ClockError('a Ledger is required')
        accepted = ledger.head()
        head = accepted if head is None else ledger._own(head)
        if head.key != accepted.key:
            raise ClockError('a clock starts at the accepted head; an earlier commit cannot be continued or branched')
        state = ledger.state(head)
        settings = state.settings
        times = [advance_time(state.start_time_s, k*settings.step_s) for k in range(settings.steps+1)]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ClockError("the fixed schedule's step boundaries are not all distinct at this epoch time; choose a "
                             'nearer epoch or a longer step')
        self._ledger, self._head, self._state = ledger, head, state
        self._run = _state.Continuation(state, budget=budget)
        self._stale, self._unsettled = False, None

    def __reduce__(self):
        raise TypeError('a Clock holds rebuilt operators and a live ledger; open a new one at the accepted head')

    @property
    def head(self):
        return self._head

    @property
    def state(self):
        return self._state

    @property
    def continuation(self):
        """The one Continuation serving this clock's requests, for reports and direct comparison. Advancing through it
        directly is outside the clock: it moves the Continuation's one warm entry, so the clock's next request
        re-solves its starting stage cold (unbooked) and agrees within the retained parity rather than bitwise."""
        return self._run

    def time_at(self, step):
        """Epoch time of global step ``step``, exactly as an accepted state records it."""
        settings = self._state.settings
        if type(step) is not int or not 0 <= step <= settings.steps:
            raise ClockError('a global step index of the fixed schedule is required')
        return advance_time(self._state.start_time_s, step*settings.step_s)

    def step_at(self, time_s, *, whole=True):
        """The last global step index not after ``time_s``; with ``whole`` the time must be that step exactly."""
        if isinstance(time_s, bool):
            raise ClockError('a requested time is a real number')
        try:
            time_s = scalar(time_s, 'requested time')
        except TectonicsError as exc:
            raise ClockError('a requested time is a finite real number of epoch seconds') from exc
        settings, start, last = self._state.settings, self._state.start_time_s, self._state.settings.steps
        if time_s < start:
            raise ClockError('requested time precedes the history start')
        if time_s >= self.time_at(last):
            step = last
        else:
            step = min(max(int((time_s-start)/settings.step_s), 0), last)
            while step > 0 and self.time_at(step) > time_s:
                step -= 1
            while step < last and self.time_at(step+1) <= time_s:
                step += 1
        if whole and self.time_at(step) != time_s:
            raise ClockError('requested time is not a whole step of the fixed global schedule')
        return step

    def _calendar(self, events, current, target):
        """Savepoint steps and the earliest unsupported event, which fixes the last step the clock may accept.

        The ledger's declared calendar always applies; a request adds savepoints only.
        """
        if type(events) not in (tuple, list):
            raise ClockError('events are a sequence of Event records')
        now, checked = self.time_at(current), []
        for item in events:
            if type(item) is not Event:
                raise ClockError('typed Event records required')
            if item.kind not in SUPPORTED_EVENTS:
                raise ClockError('unsupported events are declared in the ledger calendar when the history is created, '
                                 'so every clock honours them; a request adds savepoints only')
            if item.time_s < now:
                raise ClockError('a declared event precedes the accepted head; the calendar cannot run backwards')
            checked.append(item)
        checked.extend(Event(*entry) for entry in self._ledger.calendar if entry[0] >= now)
        saves, stop, event = set(), target, None
        for item in sorted(checked, key=lambda e: (e.time_s, e.kind, e.label)):
            if item.kind in SUPPORTED_EVENTS:
                step = self.step_at(item.time_s)
                if current < step <= target:
                    saves.add(step)
                continue
            step = self.step_at(item.time_s, whole=False)
            if step < stop:
                stop, event = step, item
        return saves, stop, event

    def advance(self, *, steps=None, until_s=None, savepoint_steps=None, events=(), transfers=None, cancel=None,
                deadline=None):
        """Accept and commit whole global steps from the head: ``steps`` of them, or up to the step at ``until_s``.

        ``savepoint_steps`` commits at every global step index divisible by it (and always at the end); prescribed
        savepoint events add commits at their whole steps. ``transfers`` is a sequence of Transfer proposals, each
        declaring the interval (start_step, end_step] of whole global steps it was produced for. An interval starts at
        or after the head, ends within the request and overlaps no other; both ends become savepoints, a savepoint
        event (of the request or the ledger calendar) or an unsupported event before its end refuses the request, and
        ``savepoint_steps`` multiples inside it are skipped. The proposals of one interval are committed in the one
        commit spanning it, so its steps are committed together with its exchange or not at all: a refused exchange
        (REFUSED_EXCHANGE) or a stop inside the interval leaves the head at the interval's start. ``cancel`` (an event
        or callable) is polled between steps and ``deadline`` is the core's cooperative perf_counter instant. Invalid
        requests raise ClockError before any work. A commit that raises is retried once, and a retry that succeeds
        changes nothing; otherwise the exception propagates with a note saying whether the steps were committed.
        Everything else returns an Outcome whose head holds every committed step.
        """
        current, target, saves, stop, event, exchanges, polled, deadline = self._plan(
            steps, until_s, savepoint_steps, events, transfers, cancel, deadline)
        ledger, head = self._ledger, self._head
        if ledger.head().key != head.key:
            self._stale = True
            return self._outcome(REFUSED_STALE_PARENT, 'another writer advanced this ledger', target-current, 0,
                                 ledger.head(), (), None)
        return self._run_plan(current, target, saves, stop, event, exchanges, polled, deadline)

    def check(self, *, steps=None, until_s=None, savepoint_steps=None, events=(), transfers=None, cancel=None,
              deadline=None):
        """Validate a request as advance() would, without running or committing anything.

        Returns the target step, the step the calendar lets it reach, the savepoint steps and any stopping event. Like
        advance(), it first settles a commit of this clock whose outcome could not be read; unlike advance(), it does
        not look for a head another writer has advanced, which advance() reports as REFUSED_STALE_PARENT.
        """
        current, target, saves, stop, event, _, _, _ = self._plan(steps, until_s, savepoint_steps, events, transfers,
                                                                  cancel, deadline)
        return dict(start_step=current, target_step=target, stop_step=stop, savepoints=sorted(saves),
                    event=None if event is None else (event.time_s, event.kind, event.label))

    def _plan(self, steps, until_s, savepoint_steps, events, transfers, cancel, deadline):
        self._reconcile()
        if self._stale:
            raise ClockError('this clock was overtaken by another writer; open a new clock at the accepted head')
        settings = self._state.settings
        current = self._state.column.accepted_steps
        if (steps is None) == (until_s is None):
            raise ClockError('request either whole steps or a whole-step end time')
        if steps is not None:
            if type(steps) is not int or steps < 1:
                raise ClockError('a request advances a positive integer number of whole steps')
            target = current+steps
        else:
            target = self.step_at(until_s)
            if target <= current:
                raise ClockError('the requested time is not after the accepted head')
        if target > settings.steps:
            raise ClockError('request exceeds the %d remaining whole steps of the fixed schedule; the cumulative '
                             'limit is never reset' % (settings.steps-current))
        if savepoint_steps is not None and (type(savepoint_steps) is not int or savepoint_steps < 1):
            raise ClockError('savepoints are every positive whole number of global steps')
        polled = _cancelled(cancel)
        deadline = _deadline(deadline)
        exchanges = self._exchanges(transfers, current, target)
        saves, stop, event = self._calendar(events, current, target)
        spans = [(start, end) for end, (start, _) in exchanges.items()]
        for start, end in spans:
            if end > stop:
                raise ClockError('the ledger calendar stops the clock at global step %d, before the end of the '
                                 'interval (%d, %d] a transfer declares' % (stop, start, end))
            if any(start < step < end for step in saves):
                raise ClockError('a declared savepoint splits the interval (%d, %d] a transfer declares'
                                 % (start, end))
        if savepoint_steps is not None:
            saves.update(k for k in range(current+1, stop+1)
                         if k % savepoint_steps == 0 and not any(start < k < end for start, end in spans))
        saves.update(start for start, _ in spans if start > current)
        saves.update(end for _, end in spans)
        saves.add(stop)
        return current, target, saves, stop, event, exchanges, polled, deadline

    def _run_plan(self, current, target, saves, stop, event, exchanges, polled, deadline):
        settings, state = self._state.settings, self._state
        pending, commits, status, reason, done, committing = [], [], None, None, current, False
        try:
            while done < stop:
                if polled():
                    status, reason = CANCELLED, 'cancelled between whole steps'
                    break
                piece = self._run.advance(state, 1, deadline=deadline)
                if piece.accepted_steps == 0:
                    status, reason = piece.status, piece.reason
                    break
                state, done = piece.state, done+1
                pending.append(state)
                if done in saves:
                    committing = True
                    committed, refusal, stale = self._settle(pending, self._moves(done, exchanges))
                    committing, pending = False, []
                    if committed is not None:
                        commits.append(committed)
                    if stale:
                        return self._overtaken(target-current, current, commits, refusal)
                    if refusal is not None:
                        if committed is not None and event is not None and done == stop < target:
                            reason = _joined(reason, refusal)    # the adopted record reached the event stop
                        else:
                            status, reason = REFUSED_EXCHANGE, refusal
                            break
        except BaseException as exc:
            if not committing:                 # a commit that raised has already said what became of its steps
                self._rescue(exc, pending, done, exchanges, current)
            raise
        if pending:                            # the request stopped early; its stop reason decides the status
            span = self._interval(done, exchanges)
            if span is not None and done < span[1]:
                reason = _joined(reason, self._unfinished(span))
            else:
                committed, refusal, stale = self._settle(pending, () if span is None else span[2])
                if committed is not None:
                    commits.append(committed)
                if stale:
                    return self._overtaken(target-current, current, commits,
                                           reason if refusal is None else _joined(reason, refusal))
                if refusal is not None:
                    reason = _joined(reason, refusal)
        if status is None:
            if event is not None and done < target:
                text = ('declared %s event %r is not supported by this route; stopped at the last whole step not after '
                        'it' % (event.kind, event.label))
                status, reason = REFUSED_UNSUPPORTED_EVENT, text if reason is None else _joined(text, reason)
            else:
                status = HISTORY_COMPLETE if self._head.accepted_steps == settings.steps else COMPLETED
        return self._outcome(status, reason, target-current, self._head.accepted_steps-current, self._head,
                             tuple(commits), event if status == REFUSED_UNSUPPORTED_EVENT else None)

    def _exchanges(self, transfers, current, target):
        """Transfer proposals grouped by their declared interval: {end_step: (start_step, proposals)}."""
        if transfers is None:
            return {}
        if type(transfers) not in (tuple, list) or any(not _ledger._proposal(p) for p in transfers):
            raise ClockError('transfers are a sequence of Transfer proposals, each declaring its interval')
        groups = {}
        for proposal in transfers:
            start, end = proposal.start_step, proposal.end_step
            if start < current:
                raise ClockError('the interval (%d, %d] a transfer declares starts before the accepted head at global '
                                 'step %d; an earlier commit splits it' % (start, end, current))
            if end > target:
                raise ClockError('the interval (%d, %d] a transfer declares ends after this request' % (start, end))
            groups.setdefault((start, end), []).append(proposal)
        spans = sorted(groups)
        for (a, b), (c, d) in zip(spans, spans[1:]):
            if c < b:
                raise ClockError('the transfer intervals (%d, %d] and (%d, %d] overlap; each is committed whole, once'
                                 % (a, b, c, d))
        return {end: (start, tuple(groups[start, end])) for start, end in spans}

    def _interval(self, done, exchanges):
        """(start, end, proposals) of the declared interval holding the steps after the head up to ``done``, if any."""
        head = self._head.accepted_steps
        for end, (start, proposals) in exchanges.items():
            if start <= head < done <= end:
                return start, end, proposals
        return None

    def _moves(self, done, exchanges):
        span = self._interval(done, exchanges)
        return () if span is None else span[2]

    def _unfinished(self, span):
        return ('the steps accepted after global step %d lie inside the interval (%d, %d] declared for transfers and '
                'were not committed' % (self._head.accepted_steps, span[0], span[1]))

    def _carried(self, commit):
        """The transfers the stored record of ``commit`` carries, in order, by their declared content, then (I03.2)
        the motion of an attached network; the finite-stock transfers that motion produced are its own."""
        metadata = self._ledger.store.metadata(commit.key)
        own, motion = _ledger._network_content(metadata)
        return [(r['label'], r['producer'], r['donor'], r['receiver'], sorted(r['component_mass_kg'].items()),
                 r['enthalpy_j'], r['basis'], r['interval']['start_step'], r['interval']['end_step'])
                for r in metadata['transfers'] if r['producer'] != own]+motion

    @staticmethod
    def _content(moves):
        """The declared content of proposed transfers, then of a proposed motion, comparable with _carried()."""
        return [(m.label, m.producer, m.donor, m.receiver, sorted(dict(m.component_mass_kg).items()), m.enthalpy_j,
                 m.basis, m.start_step, m.end_step) for m in moves if type(m) is _ledger.Transfer]+[
                     ('motion', m.motion_id) for m in moves if type(m) is not _ledger.Transfer]

    def _commit(self, pending, moves):
        """One attempt to commit the pending steps after the head: (commit or None, refusal or None, overtaken).

        A refused exchange (the ledger's ExchangeRefused) commits nothing, since an interval's steps stand or fall with
        its exchange; any other failure of the commit propagates. A conflict with a record holding exactly these steps
        (this clock's own commit, published by an earlier attempt interrupted after COMMIT) is adopted rather than
        taken for another writer.
        """
        head = self._head
        try:
            committed = self._ledger.commit(head, tuple(pending), moves)
        except _ledger.LedgerConflict:
            adopted = self._adopt(pending, moves)
            if adopted is None:            # a conflict, yet nothing follows the head: its record was replaced
                self._stale = True
                return None, None, True
            return adopted
        except _ledger.ExchangeRefused as exc:
            return None, ('the exchange declared for the interval (%d, %d] was refused, so its steps were not '
                          'committed: %s' % (head.accepted_steps, pending[-1].column.accepted_steps, exc)), False
        self._head, self._state = committed, pending[-1]
        return committed, None, False

    def _adopt(self, pending, moves):
        """What became of the pending steps, as _commit() reports it; None while nothing follows the head.

        The record following the clock's head on the accepted chain is adopted when it holds exactly the pending end
        state: this clock's own commit, published by an attempt that failed afterwards, or the same steps committed by
        another writer (then with a refusal when it carries other transfers than ``moves``). Any other record makes
        this clock stale, and so does a history another writer has continued beyond the adopted record.
        """
        chain, head = self._ledger.chain(), self._head
        keys = [commit.key for commit in chain]
        if head.key not in keys:
            self._stale = True
            return None, None, True
        after = keys.index(head.key)+1
        if after == len(chain):
            return None
        successor = chain[after]
        if successor.state_id != pending[-1].state_id:
            self._stale = True
            return None, None, True
        refusal = None
        if self._carried(successor) != self._content(moves):
            refusal = ('the accepted record of global step %d carries other transfers than this request'
                       % pending[-1].column.accepted_steps)
        self._head, self._state = successor, pending[-1]
        overtaken = after+1 < len(chain)
        self._stale = self._stale or overtaken
        return successor, refusal, overtaken

    def _reconcile(self):
        """Settle a commit of this clock whose outcome could not be read: adopt its record if it was published.

        A record of the same steps with other transfers is not this clock's own: the clock is then stale, and the
        request is refused rather than continuing silently from transfers it never proposed.
        """
        if self._unsettled is not None:
            pending, moves = self._unsettled
            result = self._adopt(pending, moves)   # a read that fails again propagates, and it stays unsettled
            self._unsettled = None
            if result is not None and result[0] is not None and result[1] is not None:
                self._stale = True
                raise ClockError('the commit whose outcome could not be read was made by another writer with other '
                                 'transfers; open a new clock at the accepted head')

    def _twice(self, pending, moves):
        """Commit with one retry: (result, the first failure or None).

        ``result`` is what _commit() returned; after two failures it is the published record an attempt may have left
        (adopted), None when nothing follows the head, or _UNKNOWN when even that could not be read.
        """
        failure = None
        for _ in range(2):
            try:
                return self._commit(pending, moves), failure
            except BaseException as exc:
                failure = exc if failure is None else failure
        try:
            return self._adopt(pending, moves), failure
        except BaseException:
            self._unsettled = (list(pending), tuple(moves))
            return _UNKNOWN, failure

    def _settle(self, pending, moves):
        """Commit the pending steps: (commit or None, refusal or None, overtaken).

        A failure that the retry recovers from changes nothing. Otherwise, and for any interruption that is not an
        ordinary Exception, the first failure propagates with a note saying what became of the steps.
        """
        result, failure = self._twice(pending, moves)
        if failure is not None and (result is None or result is _UNKNOWN or not isinstance(failure, Exception)):
            self._report(failure, result, pending)
            raise failure
        return result

    def _rescue(self, exc, pending, done, exchanges, current):
        """Before ``exc`` propagates, commit the pending steps unless they lie in an unfinished transfer interval, and
        say in a note what became of them (or what the request had committed before it)."""
        if not pending:
            if self._head.accepted_steps > current:
                exc.add_note('the steps accepted up to global step %d were committed as %s before this propagated'
                             % (self._head.accepted_steps, self._head.key))
            else:
                exc.add_note('no further steps were committed; the last accepted global step is %d at epoch time '
                             '%r s, committed as %s' % (self._head.accepted_steps, self._head.time_s, self._head.key))
            return
        span = self._interval(done, exchanges)
        if span is not None and done < span[1]:
            exc.add_note(self._unfinished(span))
            return
        result, _ = self._twice(pending, () if span is None else span[2])
        self._report(exc, result, pending)

    def _report(self, exc, result, pending):
        """Note on a propagating exception what became of the pending steps."""
        first, last = self._head.accepted_steps, pending[-1].column.accepted_steps
        if result is None:
            text = 'the steps accepted after global step %d up to %d were not committed' % (first, last)
        elif result is _UNKNOWN:
            text = ('whether the steps accepted up to global step %d were committed could not be read; reopen the '
                    'ledger for its accepted head' % last)
        else:
            committed, refusal, overtaken = result
            if committed is not None:
                text = ('the steps accepted up to global step %d were committed as %s before this propagated'
                        % (committed.accepted_steps, committed.key))
                if overtaken:
                    text += '; another writer has since continued the history, so this clock is stale'
                if refusal is not None:
                    text += '; '+refusal
            elif overtaken:
                text = ('the steps accepted up to global step %d were not committed: another candidate was accepted '
                        'after their parent' % last)
            else:
                text = refusal
        exc.add_note(text)

    def _overtaken(self, requested, current, commits, reason):
        return self._outcome(REFUSED_STALE_PARENT, _joined(reason, 'another candidate was accepted after this parent'),
                             requested, self._head.accepted_steps-current, self._ledger.head(), tuple(commits), None)

    def _outcome(self, status, reason, requested, accepted, head, commits, event):
        return _issue(Outcome, status=status, reason=reason, requested_steps=requested, accepted_steps=accepted,
                      head=head, time_s=head.time_s, step=head.accepted_steps, commits=commits, event=event)


_UNKNOWN = object()                    # a commit whose outcome could not be read back


def _joined(reason, more):
    return more if not reason else reason+'; '+more
