"""Bounded rolling schedule of cost-targeted worker batches.

Scheduling only. A schedule looks a bounded distance ahead of the parent in
the router's own order, groups upcoming requests into batches of a target
expected cost and gives each batch to one one-shot worker of a batch session.
It never computes, validates or adopts anything: the session and the issuer
do that, at the parent's serial position, exactly as without a schedule.

What it decides, from estimates alone:

* whether enough eligible work is expected in this pass at all. The threshold
  is applied once, before the first worker is started, to the work in sight
  plus the work beyond the lookahead at the rate seen in it;
* which requests the parent keeps: unknown ones, known exact shortcuts,
  requests that cannot be shipped, and everything in front of a batch. A
  batch begins where the parent, running everything before it itself, would
  arrive no earlier than the batch's worker finishes; so parent and workers
  all compute, and nobody stands waiting;
* where a batch ends: at the target seconds, the job limit or the transport
  capacity, before a request that would carry it more than a quarter past
  the target, and before a batch that is already held. Past its target a
  batch grows only while the parent would still arrive after it, and never
  beyond twice the target;
* whether a batch pays: the seconds by which it brings the parent forward
  must cover a worker's fixed cost, and half of what the best batch in sight
  would bring. When no batch can be cut that the parent would not wait for,
  the one that brings the parent furthest forward is taken if it pays, wait
  included: a large request on an otherwise idle worker, for instance.

Finished batches correct it, and so does the parent: the realised seconds of
each batch, and of each stretch of the target seconds that the parent itself
ran, rescale the class expectations within fixed bounds. The seconds of an
identical earlier request are never rescaled. When the seconds the finished
batches took off the parent stay below what the parent spent on them, the
schedule stops for the rest of its pass. A batch that ran for more than twice
what its classes had ever suggested is a surprise and is left out of that
verdict, wait and work alike: whoever had run it would have been busy as
long, and it says nothing about whether batches pay. A failed worker, an
inactive session or a failed gate also stops the schedule. A stopped schedule
is never restarted and nothing is retried.

An Exception of the schedule's own steps (its estimates, its plan, its gate,
its books) is a recorded reason to stop. What its session raises is not: the
session keeps its failures to itself except a worker that could not be
confirmed stopped, and that one must reach the caller.

Bounds: at most ``horizon`` requests ahead, ``workers`` running batches,
twice as many held batches, ``batch_jobs`` requests and ``capacity`` encoded
bytes in one batch, and a fixed number of rows in its report. Estimates,
seconds and decisions never enter an issued record, a receipt row, a measure
or any identity.
SPDX-License-Identifier: AGPL-3.0-only
"""
from collections import deque
from time import perf_counter

RATIOS = 5           # finished batches and parent stretches whose realised seconds rescale the expectations
SCALE = (0.25, 2.0)  # bounds of that rescaling
PROBATION = 3        # finished batches before the realised saving may stop the schedule
REPLAN = 64          # requests the parent passes before a declined plan is looked at again
BACKOFF = 16         # a plan declined again and again is looked at this many times less often
RECENT = 8           # launched batches named in the report
OVERSHOOT = 1.25     # below its target a batch takes no request that would carry it further than this
GROW = 2.0           # past its target a batch grows no further than this, and only while nobody would wait
PARTIAL = 0.5        # share of the target a batch needs before it is cut while more may still be offered
RATED = 0.1          # share of the target of class-estimated work a batch needs to rate its class estimates
PREFERRED = 0.5      # a batch nobody waits for is started only if it brings this share of the best in sight
_FAILED = object()   # a guarded step of the schedule's own raised, and the schedule has stopped


def expectation(shortcut, integrator, samples, minimum_samples, ceiling=None):
    """(expected integrator seconds, high seconds) of one contact of a class, or None while unknown.

    The expectation is the observed share of contacts that reached the
    integrator times the mean of the kept integrator seconds; the high value
    is 1.25 times the largest of them. A class seen at least minimum_samples
    times and only ever as an exact shortcut is known and costs nothing.
    Contacts counted without a timing change the share, never the mean.

    With a ceiling, the mean is that of the kept seconds below it. Requests
    at least that long are remembered one by one where they can be; a few of
    them among sixteen samples would otherwise price every contact of their
    class as a large one, which the cheap many are not.
    """
    if integrator >= minimum_samples and len(samples) >= min(minimum_samples, integrator):
        usual = samples if ceiling is None else [seconds for seconds in samples if seconds < ceiling] or samples
        return integrator/(integrator+shortcut)*sum(usual)/len(usual), 1.25*max(samples)
    if not integrator and shortcut >= minimum_samples:
        return 0.0, 0.0
    return None


def _median(values):
    ordered = sorted(values)
    return (ordered[(len(ordered)-1)//2]+ordered[len(ordered)//2])/2


class _Window:
    """Requests that one worker would take, in order, from one first request on."""
    __slots__ = ('rows', 'start', 'count', 'cost', 'prefix', 'high', 'size', 'shared')

    def __init__(self, rows):
        # rows: every request a worker may take, as (entry, index, expected, prefix, high, arrival, sizes)
        self.rows, self.start, self.count = rows, 0, 0
        self.cost = self.prefix = self.high = 0.0
        self.size, self.shared = 0, {}

    def first(self):
        """When the parent reaches the window's first request, running everything before it itself."""
        return self.rows[self.start][5]

    def added(self, sizes):
        return sum(amount for identity, amount in sizes if identity not in self.shared)

    def add(self):
        """Take the newest row."""
        if not self.count:
            self.start = len(self.rows)-1
        _, _, expected, prefix, high, _, sizes = self.rows[-1]
        self.count += 1
        self.cost += expected
        self.prefix += prefix
        self.high += high
        for identity, amount in sizes:
            held = self.shared.get(identity, 0)
            if not held:
                self.size += amount
            self.shared[identity] = held+1

    def drop(self):
        """The parent keeps the first request after all."""
        _, _, expected, prefix, high, _, sizes = self.rows[self.start]
        self.start += 1
        self.count -= 1
        if not self.count:
            self.cost = self.prefix = self.high = 0.0
            self.size = 0
            self.shared.clear()
            return
        self.cost -= expected
        self.prefix -= prefix
        self.high -= high
        for identity, amount in sizes:
            self.shared[identity] -= 1
            if not self.shared[identity]:
                del self.shared[identity]
                self.size -= amount

    def span(self):
        return self.start, self.count, self.cost, self.prefix, self.high, self.first()


class Schedule:
    """One pass's rolling schedule over the requests its router offers, in order.

    ``session()`` returns an opened batch session, or None when none could be
    opened; it is called once, when the first batch is worth starting.
    ``estimate(label)`` returns the (expected, high) seconds of a class, or
    None while it is unknown. ``beyond()`` estimates how many requests follow
    the lookahead. ``gate()``, if given, returns None or the (reason, detail)
    that ends the schedule. ``shippable(job)``, if given, says whether a
    request fits the optional transport, and ``weigh(job)`` names what it
    would ship as (identity, encoded bytes) pairs, of which one batch holds
    at most ``capacity`` bytes. ``adoption`` is the share of a request's
    exact prefix the parent still pays when a worker answers it.
    No method raises an Exception of its own: a failure here is a recorded
    reason to stop. ``advance`` and ``reached`` let through what the session
    raises, which is an unconfirmed worker shutdown and nothing else.
    """
    def __init__(self, *, session, estimate, beyond, workers, batch_seconds, batch_jobs, horizon,
                 minimum_seconds, startup_seconds, transfer_seconds, contention, benefit_ratio,
                 timeout_seconds, gate=None, shippable=None, weigh=None, capacity=None, adoption=1.0,
                 replan=REPLAN, clock=perf_counter):
        self._open, self._estimate, self._beyond, self._gate = session, estimate, beyond, gate
        self._shippable = (lambda job: True) if shippable is None else shippable
        self._weigh = (lambda job: ()) if weigh is None else weigh
        self.capacity = capacity
        self.workers, self.target, self.limit, self.horizon = workers, batch_seconds, batch_jobs, horizon
        self.minimum, self.startup, self.transfer = minimum_seconds, startup_seconds, transfer_seconds
        self.contention, self.timeout = contention, timeout_seconds
        self.worth = benefit_ratio*(startup_seconds+transfer_seconds)
        self.adoption, self.replan, self.clock = adoption, replan, clock
        self.session = None
        # ahead: [job, prefix seconds, held batch or None, class label, exact estimate or None,
        #         seconds in sight, whether it must stay with the parent]
        self.ahead, self.live = deque(), deque()
        self.position = self.offered = 0
        self.closed, self.stopped, self.engaged = False, None, False
        self.reason = self.detail = None
        self.scale, self._ratios = 1.0, deque(maxlen=RATIOS)
        self._stretch, self._head = [0.0, 0.0], None
        self._plans, self._settled = {}, set()
        self._sight, self._free, self._wanted = 0.0, 0, 0
        self._again, self._declined = None, 0
        self.totals = dict(batches=0, jobs=0, expected_seconds=0.0, avoided_seconds=0.0, finished=0,
                           longest_lookahead=0, projected_seconds=None, plans=0, planning_seconds=0.0,
                           stretches=0, waited_seconds=0.0, judged=0, surprises=0)
        self.reasons, self.recent = {}, deque(maxlen=RECENT)

    def offer(self, job, prefix, label, exact=None):
        """One upcoming request, in router order.

        ``prefix`` is the parent's typical exact-prefix seconds for it,
        ``label`` its class and ``exact`` the (expected, high) seconds of an
        identical earlier request, if one is known.
        """
        found = exact if exact is not None else self._estimate(label)
        sight = 0.0 if found is None else found[0]
        self.ahead.append([job, prefix, None, label, exact, sight, False])
        self._sight += sight
        self._free += 1
        self.offered += 1
        if len(self.ahead) > self.totals['longest_lookahead']:
            self.totals['longest_lookahead'] = len(self.ahead)

    def hungry(self):
        """Whether the router should show more: never beyond the horizon, nor beyond a round of work.

        A round is the target seconds for the parent and for each worker, and
        at least two unassigned requests for each of them: a request that is
        a batch of its own must not hide the ones behind it. A plan that found
        too little behind the parent's own stretch asks for as much again.
        """
        lanes = self.workers+1
        return (not self.closed and self.stopped is None and len(self.ahead) < self.horizon
                and (self.offered < self._wanted or self._sight*self.scale < lanes*self.target
                     or self._free < 2*lanes))

    def reached(self):
        """The parent is about to run its next offered request; whether no batch holds it.

        Batches wholly behind the parent are returned to their session.
        """
        kept, self._head = True, None
        if self.ahead:
            entry = self.ahead.popleft()
            if entry[2] is None:
                self._sight -= entry[5]
                self._free -= 1
                self._head = entry
            else:
                kept = False
        position, self.position = self.position, self.position+1
        while self.live and self.live[0]['last'] < position:
            passed = self.live.popleft()
            if self.session is not None:
                # Stops a worker nobody will ask; an unconfirmed stop propagates from the session.
                self.session.retire(passed['batch'])
        return kept

    def unlisted(self):
        """The parent is about to run a request that was never offered: nothing is learned of it."""
        self._head = None

    def ran(self, seconds):
        """The parent itself ran the request it last reached, which no batch held.

        Every stretch of the target seconds that it runs so is rated as a
        finished batch is: realised against expected. A pass whose workers
        went through a poor region learns from its own requests when the work
        becomes worth a worker again.
        """
        entry, self._head = self._head, None
        if entry is None or self.closed or entry[4] is not None:
            return      # nothing reached, or a request remembered one by one: it says nothing of its class
        found = self._estimate(entry[3])
        if found is None or found[0] <= 0:
            return
        held = self._stretch
        held[0] += max(0.0, seconds-entry[1])
        held[1] += found[0]
        if held[1] >= self.target:
            self._ratios.append(held[0]/held[1])
            held[0] = held[1] = 0.0
            self.totals['stretches'] += 1
            self._rescale()

    def _rescale(self):
        self.scale = min(SCALE[1], max(SCALE[0], _median(self._ratios)))

    def advance(self):
        """Start whatever is worth starting now. Cheap when nothing changed since it last looked.

        The session's own calls (check, launch) are made outside every guard:
        whatever they raise is a worker that could not be confirmed stopped.
        """
        if self.closed or self.stopped is not None:
            return
        session = self.session
        running, held = (0, 0) if session is None else (session.running(), len(session.batches))
        if self._again is not None:
            position, offered, ran, kept = self._again
            if self.position < position and self.offered < offered and running >= ran and held >= kept:
                return
            self._again = None
        if session is not None:
            # A worker that failed is noticed here, before anything further is started.
            if not session.check():
                return self._stop(*session.ended())
            if self._guard(self._settle, session) is _FAILED or self.stopped is not None:
                return
        while running < self.workers and (session is None or len(session.batches) < 2*self.workers):
            self.totals['plans'] += 1
            begun = self.clock()
            chosen = self._guard(self._choose, begun)
            if chosen is _FAILED:
                return
            self.totals['planning_seconds'] += self.clock()-begun
            if chosen is None:
                return self._later(session, True, running)
            members, cost, prefix, high, finish, first, last = chosen
            if self._gate is not None:
                refusal = self._guard(self._gate)
                if refusal is _FAILED:
                    return
                if refusal is not None:
                    return self._stop(*refusal)
            if session is None:
                session = self._guard(self._open)
                if session is _FAILED:
                    return
                self.session = session
                if session is None:
                    return self._stop('session not opened', 'the optional session, its storage or its owner was refused')
                session.on_wait = self.advance
            timeout = min(self.timeout, max(120.0, self.startup+4*self.contention*high))
            refused = session.stats['refused']
            batch = session.launch([entry[0] for entry in members], timeout)
            if batch is None:
                if not session.active():
                    return self._stop(*session.ended())
                if session.stats['refused'] == refused:
                    # Nothing was refused funding: this request list cannot be bound. Its
                    # requests stay with the parent, and what follows them is looked at again.
                    for entry in members:
                        entry[6] = True
                    self._note('batch not bound', str(session.last_error)[:200])
                    continue
                # Looked at again as soon as the session holds less: waiting longer teaches nothing.
                self._note('worker funding refused', 'the envelope, baseline or transport of a batch was refused')
                return self._later(session, False, running)
            if self._guard(self._launched, batch, members, cost, prefix, finish, first, last, timeout) is _FAILED:
                return
            running += 1
        # Every worker is busy, or as much is held as may be: looked at again when that changes.
        self._later(session, False, running)

    def _guard(self, step, *operands):
        """One step of the schedule's own: its Exception is a recorded reason to stop, never raised."""
        try:
            return step(*operands)
        except Exception as error:
            self._stop('schedule error', '%s: %s' % (type(error).__name__, error))
            return _FAILED

    def _launched(self, batch, members, cost, prefix, finish, first, last, timeout):
        """The schedule's books for a batch its session has just started."""
        held = dict(batch=batch, first=self.position+first, last=self.position+last, estimate=finish,
                    index=batch['index'])
        # What of its expected seconds came from class estimates, unscaled, and what from identical requests.
        known = sum(entry[4][0] for entry in members if entry[4] is not None)
        self._plans[batch['index']] = (cost-known)/self.scale, known, prefix, cost
        for entry in members:
            entry[2] = held
            self._sight -= entry[5]
            self._free -= 1
        self.live.append(held)
        self.live = deque(sorted(self.live, key=lambda row: row['last']))
        self.engaged, self._declined = True, 0
        self.totals['batches'] += 1
        self.totals['jobs'] += len(members)
        self.totals['expected_seconds'] += cost
        self.recent.append(dict(index=batch['index'], first=held['first'], last=held['last'],
                                jobs=len(members), expected_seconds=round(cost, 3), timeout_seconds=timeout))

    def _fits(self, window, now, expected, prefix, sizes):
        """Whether the window may take one more request."""
        if window.count >= self.limit:
            return False
        if self.capacity is not None and window.size+window.added(sizes) > self.capacity:
            return False
        grown = window.cost+expected
        if window.cost < self.target and grown <= OVERSHOOT*self.target:
            return True
        # Past its target a batch grows only while the parent would still arrive after it.
        return (grown <= GROW*self.target and
                now+self.startup+self.contention*(grown+window.prefix+prefix) <= window.first())

    def _choose(self, now):
        """The next batch as (entries, expected, prefix, high, finish, first, last), or None with a note.

        One walk along the lookahead beside the parent's own arrival, taken as
        if it ran everything that no batch holds yet. A window slides along
        the requests a worker may take: it grows while it can, and where it
        cannot, it is one candidate batch; then its first request is left to
        the parent and it moves on. The first candidate behind every batch
        still running that the parent would not wait for is started, if it
        pays and brings at least half of what the best candidate would.
        Otherwise the candidate that brings the parent furthest forward is,
        if that pays; while the router still has more to show for a window
        that is too small to judge, that second choice waits for it.
        """
        session = self.session
        rows, spans, gates = [], [], []
        window, arrival, seen = _Window(rows), now, None
        sight, known, unassigned = 0.0, 0, 0
        for index, entry in enumerate(self.ahead):
            job, prefix, held = entry[0], entry[1], entry[2]
            if held is not None:
                # A batch never reaches across one that is already held.
                while window.count:
                    spans.append(window.span())
                    window.drop()
                if held is not seen:
                    seen = held
                    if not session.done(held['batch']):
                        # Still running: (its first request ahead, the parent's arrival there, its finish).
                        gates.append((index, arrival, held['estimate']))
                arrival = max(arrival, held['estimate'])+prefix*self.adoption
                continue
            unassigned += 1
            found = entry[4] if entry[4] is not None else self._estimate(entry[3])
            if found is None:
                arrival += prefix
                continue
            known += 1
            # The seconds of an identical earlier request stand as they are; a class estimate is rescaled.
            expected = found[0] if entry[4] is not None else found[0]*self.scale
            sight += expected
            if expected > 0 and not entry[6] and self._shippable(job):
                sizes = self._weigh(job)
                while window.count and not self._fits(window, now, expected, prefix, sizes):
                    spans.append(window.span())
                    window.drop()
                rows.append((entry, index, expected, prefix, found[1], arrival, sizes))
                window.add()
            arrival += prefix+expected
        projected = sight+self._beyond()*(sight/unassigned if unassigned else 0.0)
        if not self.engaged:
            self.totals['projected_seconds'] = projected
        if not known:
            return self._note('no compatible observations', 'no request in the lookahead has an estimate')
        if not self.engaged and projected < self.minimum:
            return self._note('eligible work below threshold',
                'expected %.3f s of eligible work in this pass (%.3f s in a lookahead of %d); threshold %.3f s'
                % (projected, sight, len(self.ahead), self.minimum))
        starved = (window.count and window.cost < PARTIAL*self.target
                   and len(self.ahead) < self.horizon and self._beyond() > 0)
        if not starved:
            # Nothing more will be offered behind this window, or it is worth cutting as it stands.
            while window.count:
                spans.append(window.span())
                window.drop()
        behind = max((gate[0] for gate in gates), default=-1)
        best = short = None
        rated = []
        for span in spans:
            start, count, cost, prefix, high, first = span
            finish = now+self.startup+self.contention*(cost+prefix)
            wait = max(0.0, finish-first)
            # What the parent would have paid for these requests itself, less what it still pays.
            gain = cost+prefix*(1.0-self.adoption)-wait
            last = rows[start+count-1][1]
            for index, reached, estimate in gates:
                if index > last:
                    # A batch in front of one still running only helps as far as that one lets it.
                    gain = max(reached, estimate)-max(reached-gain, estimate)
            value = gain-self.transfer
            if value < self.worth:
                if short is None or value > short[0]:
                    short = value, count, cost
                continue
            if not wait and rows[start][1] > behind:
                rated.append((value, span, finish, last))
            if best is None or value > best[0]:
                best = value, span, finish, last
        chosen = None
        if best is not None:
            # A small batch that nobody waits for must not take the worker a far better one needs.
            enough = PREFERRED*min(best[0], self.target)
            chosen = next((found[1:] for found in rated if found[0] >= enough), None)
            if chosen is None and not starved:
                chosen = best[1:]
        if chosen is not None:
            (start, count, cost, prefix, high, _), finish, last = chosen
            return [row[0] for row in rows[start:start+count]], cost, prefix, high, finish, rows[start][1], last
        if starved:
            # The router is asked for as much again as the lookahead holds, and at least one of its windows.
            self._wanted = self.offered+max(REPLAN, len(self.ahead))
            return self._note('lookahead still growing', 'too little lies behind the parent\'s own work to cut a batch yet')
        if short is not None:
            return self._note('predicted saving does not cover overheads',
                'the best batch, %d request(s) expecting %.3f s, would bring the parent %.3f s forward; '
                'a worker must bring %.3f s' % (short[1], short[2], short[0], self.worth))
        return self._note('nothing to dispatch', 'no known request ahead is expected to need a worker')

    def _settle(self, session):
        """Fold newly finished batches: realised seconds rescale expectations and may stop the schedule."""
        self._settled &= {row['index'] for row in session.log}
        for row in session.log:
            index = row['index']
            if index in self._settled:
                continue
            self._settled.add(index)
            self.totals['finished'] += 1
            plain, known, prefix, cost = self._plans.pop(index, (0.0, 0.0, 0.0, 0.0))
            body = row['body_seconds']
            # A wait is charged with its own batch: one for a batch still held is not yet set against it.
            self.totals['waited_seconds'] += row['waited_seconds']
            if body is None or cost+prefix <= 0:
                self.totals['judged'] += 1
                continue
            if plain >= RATED*self.target:
                ratio = max(0.0, body-known-prefix)/plain
                self._ratios.append(ratio)
                if ratio > SCALE[1]:
                    # Longer than the rescaling can express: a surprise, not a verdict on batches.
                    self.totals['surprises'] += 1
                    self.totals['waited_seconds'] -= row['waited_seconds']
                    continue
            self.totals['judged'] += 1
            # The share of the worker's seconds that the parent's own exact prefix would not have paid.
            self.totals['avoided_seconds'] += body*cost/(cost+prefix)
        if self._ratios:
            self._rescale()
        spent = self.totals['waited_seconds']+sum(
            seconds for name, seconds in session.seconds.items() if name != 'waited')
        if self.totals['judged'] >= PROBATION and self.totals['avoided_seconds'] < spent:
            self._stop('batches are not paying', '%d finished batch(es) took %.3f s off the parent and cost it %.3f s'
                       % (self.totals['judged'], self.totals['avoided_seconds'], spent))

    def _note(self, reason, detail):
        self.reason, self.detail = reason, detail
        self.reasons[reason] = self.reasons.get(reason, 0)+1
        return None

    def _later(self, session, declined, running):
        """Look again when the parent has moved on, more was offered, a worker is free or less is held.

        ``running`` is what this look believed was running, its own launches
        included: a worker that exited while another was being launched then
        counts as a change, and is not read back as the state to wait on.
        """
        step = self.replan
        offered = self.offered+step
        if declined and self.offered < self._wanted:
            offered = self._wanted      # what the plan asked the router for
        elif declined:
            # A plan declined again and again is looked at less and less often.
            self._declined += 1
            step *= min(BACKOFF, self._declined)
            offered = self.offered+step
        self._again = self.position+step, offered, running, 0 if session is None else len(session.batches)

    def _stop(self, reason, detail):
        if self.stopped is None:
            self.stopped, self.reason = reason, reason
            self.detail = None if detail is None else str(detail)[:400]
            self.reasons[reason] = self.reasons.get(reason, 0)+1

    def close(self):
        """End of the pass: nothing more is planned. The owner closes the session itself."""
        if self.closed:
            return
        self.closed = True
        try:
            if self.session is not None:
                self._settle(self.session)
        except Exception:
            pass
        self.ahead.clear()
        self.live.clear()
        self._head = None

    def report(self):
        started, session = self.totals['batches'], self.session
        return dict(route='parallel' if started else 'serial',
                    reason='selected' if started and self.stopped is None else self.reason,
                    detail=self.detail, stopped=self.stopped, batches=started, jobs=self.totals['jobs'],
                    finished=self.totals['finished'], plans=self.totals['plans'],
                    planning_seconds=self.totals['planning_seconds'], scale=self.scale,
                    stretches=self.totals['stretches'], surprises=self.totals['surprises'],
                    expected_seconds=self.totals['expected_seconds'],
                    projected_seconds=self.totals['projected_seconds'],
                    avoided_seconds=self.totals['avoided_seconds'],
                    parent_seconds=None if session is None else dict(session.seconds),
                    longest_lookahead=self.totals['longest_lookahead'], reasons=dict(self.reasons),
                    recent=list(self.recent))
