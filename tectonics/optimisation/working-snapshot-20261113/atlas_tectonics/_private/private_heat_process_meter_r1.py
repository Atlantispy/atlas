"""Measured admission for one forward call: the run's ledger follows the process.

The numerical stages of the forward producer reserve, before they compute, an
upper limit for values that do not exist yet. Those limits assume the worst the
allocators can do and stand five to fifty times above what the process takes.
While a forward call is metered, the run's ledger is not charged with those
limits. It is charged with what the operating system reports the process has
committed, plus a margin, plus whatever a declared single large step may still
take, plus what the call's worker processes hold. The limits are still computed
by the unchanged inventories, admitted on a side ledger that has no ceiling,
and kept for the record: what the earlier rule would have held, stage by stage.

What is guaranteed, and by what:

- At every reading the run's ledger is brought to at least ``reading + MARGIN``,
  where the reading is the larger of the process's private bytes and its
  working set. The process's memory is therefore inside the ledger at every
  instant for as long as it does not rise by more than the margin between two
  readings.
- That condition is checked, not assumed. Every reading first compares the
  process with what the ledger held for it as it stood, before the reading
  moves anything: every other owner's reservation and this meter's share less
  its workers'. A process above that raises ``MemoryLimitError``: the scope
  ends, because the ledger stood below the process for a moment. The largest
  rise seen and the least room ever left are kept in the report.
- Memory taken and returned between two readings does not show in a reading.
  The operating system keeps the highest commit the process has ever reached;
  whenever that peak has moved since the last reading, it is compared with the
  same standing figure. A transient that stays below an earlier peak of the
  process cannot be seen this way and is not claimed.
- A step that allocates a large amount at once, with no reading inside it,
  keeps its calculated reservation: ``burst(count)`` adds ``count`` to the
  charge before the step and takes off what the process has grown by since.
- A reservation that outlives the call (the returned result) and any category
  outside the scope's own are admitted on the run's ledger exactly as before.
  The meter's own share is the remainder up to the figure above (nothing, where
  the others already exceed it). When such an owner returns part of its
  reservation between two readings the ledger falls by as much until the next
  reading; the check above uses the ledger as it then stands, so a return the
  margin does not cover refuses. An admission by another owner is preceded by
  a reading, so what it adds funds only what is allocated after it.
- A scope that has failed, by a refusal or by any error of its caller, stays
  installed and goes on bringing the ledger to the process at every admission,
  but is not judged again: the reservations its unwinding returns are not a
  second refusal.
- A worker process is charged an allowance from before it is started until its
  first reading, and from then on its own private bytes and a margin of its own,
  with the same check on its rise and on a new highest commit of its own. At
  its first reading its highest commit and working set so far, not only its
  present size, must be inside the starting allowance. As for the caller, a
  transient of a worker below an earlier peak of that worker is not seen.

Readings are taken when a workspace of the scope is admitted and at the
producer's own safe points, at most once a millisecond, and before every
admission by another owner.

A scope is one forward call (every category of the producer's own), or one
exact-arithmetic workspace outside the producer (``scope``: the categories it
names). The second kind lets a re-check of a stored result hold what its
arithmetic takes instead of the worst case of every operand.

This is a meter with a margin, not a calculated upper limit. A stage is no
longer refused before it starts on its worst case; the call is stopped at the
next reading if the process and its margin no longer fit the ledger. The
real-memory guards of the caller are unchanged and remain the hard stop.

``open`` returns None on any runtime this was not measured on, when the
interpreter does not use its default allocator, while allocations are traced,
when the runtime's ``resources`` module does not offer scope admission, and
when the ledger is too small to hold the process and its margin at all (a
small test allowance). The earlier rules then apply unchanged, as they do to
every budget that is not metered. No physical value, precision, order or certified number is read or
changed here.
"""
from contextlib import contextmanager
import os
import sys
from time import perf_counter

SCHEMA = 'atlas.private.heat-process-meter.r1'
HOOK = 'scope-admission.r1'      # what the runtime's resources module must advertise
MARGIN = 256 << 20               # above the parent's reading
CHILD_MARGIN = 128 << 20         # above a worker's reading
CHILD_START = 384 << 20          # held for a worker until its first reading
INTERVAL = .001                  # seconds between two readings, at least
CATEGORY = 'heat-process-metered'
PREFIX = 'heat-'                 # the producer's own workspaces
KEPT = frozenset(('heat-completed-forward-result',))   # outlives the call: admitted as before
EVERY = 'every-category'         # a re-read of committed records: all it admits but what the reader keeps
RETAINED = '-retained'           # ... which is named so
CARRIED = 'heat-process-metered-carried'   # what a re-read left reserved, held on the run's ledger
STEP_FLOOR = 64 << 20            # a re-read's reservation at least this large is followed as one step
SIDE_BYTES = 1 << 62             # the side ledger never refuses
KEPT_REPORTS = 16                # of the scopes that returned, for the record


def _default_allocator():
    """No allocator debug hooks or replacement were requested for this process."""
    if sys.flags.dev_mode or hasattr(sys, 'gettotalrefcount'):
        return False
    return (bool(sys.flags.ignore_environment)
            or os.environ.get('PYTHONMALLOC', '') in ('', 'default', 'pymalloc'))


def _resources(budget):
    return sys.modules.get(type(budget).__module__)


def runtime(budget):
    """The facts ``supported`` tests, by name, for the record."""
    resources = _resources(budget)
    try:
        import psutil
        reading = psutil.Process().memory_info()
        counters = all(type(getattr(reading, name, None)) is int for name in ('private', 'rss'))
    except Exception:       # no reading at all on this runtime: the earlier rules apply
        counters = False
    import tracemalloc
    return dict(
        implementation=sys.implementation.name == 'cpython',
        version=sys.version_info[:2] == (3, 12),
        platform=sys.platform == 'win32' and sys.maxsize == (1 << 63)-1,
        allocator=_default_allocator(),
        untraced=not tracemalloc.is_tracing(),
        process_counters=counters,
        scope_admission=getattr(resources, 'SCOPE_ADMISSION', None) == HOOK,
        budget=resources is not None and type(budget) is getattr(resources, 'WorkBudget', None))


def supported(budget):
    """The runtime and interpreter mode this meter and its margin were measured on."""
    return all(runtime(budget).values())


def active(budget):
    """The meter of this budget's forward call in progress, or None."""
    meter = getattr(budget, '_scope', None)
    return meter if type(meter) is Meter and not meter.closed else None


def tick(budget):
    """A safe point of the producer: take a reading if one is due. No-op without a meter."""
    meter = getattr(budget, '_scope', None)
    if meter is not None:
        meter.tick()


@contextmanager
def burst(budget, count):
    """Keep ``count`` calculated bytes reserved across one step that has no reading inside."""
    meter = active(budget)
    if meter is None:
        yield
        return
    entry = meter.begin_burst(count)
    try:
        yield
    finally:
        meter.end_burst(entry)


class Meter:
    """One metered scope on one budget. Single owner, one thread.

    ``categories`` None is a forward call: every category of the producer's
    own is its work in progress. A set of names is a smaller scope around one
    exact-arithmetic workspace outside the producer: only those categories.
    """

    def __init__(self, budget, categories=None, name='forward-call'):
        import psutil
        self.resources = _resources(budget)
        self.budget = budget
        self.categories = categories if categories is None or categories is EVERY else frozenset(categories)
        self.name = name
        self.step = 0                # the largest single live step a re-read has had on the ledger
        self.steps = {}              # a re-read's categories: [its own ledger under the side ledger, largest figure]
        self.asked = (None, 0)       # the category and figure just asked for, before it is charged
        self.asked_read = True       # whether a reading has been taken since it was asked for
        self.carried = None          # what a re-read left reserved on the side ledger, held on the run's
        self.side = type(budget)(SIDE_BYTES)
        self.psutil = psutil
        self.process = psutil.Process()
        self.lease = self.resources._ResizableLease(budget, category=CATEGORY)
        self.closed = self.failed = False
        self.reading_now = False
        self.next = 0.
        self.last = None             # the parent's last reading
        self.bursts = []             # [count, reading when declared, other reservations when declared]
        self.children = {}           # pid -> dict(process, last, peak)
        self.expected = 0            # workers charged at CHILD_START, not yet read
        self.readings = self.admissions = self.side_admissions = 0
        self.largest_rise = self.largest_child_rise = self.largest_return = self.largest_transient = 0
        self.largest_child_transient = self.largest_child_start = 0
        self.last_peak = 0           # the operating system's highest commit of this process, at the last reading
        self.longest_gap = 0.
        self.last_time = None
        self.others = 0              # what the run's ledger holds apart from this meter
        self.worker_share = 0        # the part of this lease that is its workers', at the last reading
        self.least_room = None       # the closest the process came to what the ledger held for it
        self.earlier_rule_refusal = None
        self.refusal = None
        self.began = perf_counter()
        self.stages = []
        self.whole = self._row('whole-call')
        self.stage('begin')

    # ------------------------------------------------------------------ record
    def _row(self, name):
        return dict(name=name, began_seconds=round(perf_counter()-self.began, 3), seconds=None,
                    earlier_rule_peak_bytes=0, reserved_peak_bytes=0, process_peak_bytes=0,
                    private_peak_bytes=0, working_set_peak_bytes=0, workers_peak_bytes=0,
                    readings=0, largest_rise_bytes=0, largest_transient_bytes=0)

    def stage(self, name):
        """Start a row of the stage table. Called at the producer's stage boundaries."""
        now = perf_counter()-self.began
        if self.stages:
            self.stages[-1]['seconds'] = round(now-self.stages[-1]['began_seconds'], 3)
        self.stages.append(self._row(str(name)))
        if self.last is not None:
            self.read()

    def _note(self, key, value):
        for row in (self.whole, self.stages[-1]):
            if value > row[key]:
                row[key] = value

    # --------------------------------------------------------------- admission
    def _own(self, category):
        """Whether a category is this scope's work in progress."""
        if self.categories is EVERY:
            # A re-read of committed records: everything it admits, except what the reader keeps.
            return category[-len(RETAINED):] != RETAINED and category not in KEPT and category != CARRIED
        if self.categories is not None:
            return category in self.categories
        return category[:len(PREFIX)] == PREFIX and category not in KEPT

    def admit(self, budget, count, category):
        """Called by the runtime's admission for this budget: which ledger is charged.

        Returns the side ledger for a workspace of this scope's own, and the
        budget itself for the meter's own lease, for a reservation that
        outlives the call and for every other category.
        """
        if category == CATEGORY or category == CARRIED or self.reading_now:
            return budget
        self.admissions += 1
        if self.closed or not self._own(category):
            if not self.closed:
                # Charged as before. Its memory, when it is allocated, arrives
                # in the readings; the lease is brought down by as much.
                self.read()
            return budget
        self.side_admissions += 1
        earlier = self.others+self.side.reserved_bytes+count
        self._note('earlier_rule_peak_bytes', earlier)
        if earlier > budget.max_bytes and self.earlier_rule_refusal is None:
            self.earlier_rule_refusal = dict(stage=self.stages[-1]['name'], category=category,
                request_bytes=count, earlier_rule_bytes=earlier, max_bytes=budget.max_bytes)
        if self.categories is EVERY:
            # A re-read's reservations are single steps (a decode, an encoding, a restore, an audit)
            # with no safe point inside. Each category is charged on a ledger of its own under the
            # side ledger, so that the meter can tell what of it still lives. The largest calculated
            # figure among those still alive stands on the run's ledger, from before its step runs,
            # on top of the process and its margin: a step keeps its calculated reservation, and a
            # step nobody reserved for is covered up to the same size while that reservation lives.
            # A category keeps one ledger for the whole scope (a growing workspace must be charged
            # where it was charged before); the side ledger above it still holds the sum.
            entry = self.steps.get(category)
            if entry is None:
                entry = self.steps[category] = [type(self.budget)(SIDE_BYTES, parent=self.side), 0]
            if count >= STEP_FLOOR and count > entry[1]:
                entry[1] = count
            self.asked, self.asked_read = (category, count if count >= STEP_FLOOR else 0), False
            self.read()
            return entry[0]
        self.tick()
        return self.side

    def _live_step(self):
        """The largest single calculated reservation of a re-read that is still alive.

        For each category: the largest single figure asked for, but no more
        than the category still holds; nothing once it holds nothing. The one
        just asked for counts in full before it is charged.
        """
        asked, largest = self.asked
        if asked is not None and self.asked_read:
            # A reading after the one that admitted it: it has been charged since, and is followed by
            # what its category holds like every other.
            self.asked = (None, 0)
            asked, largest = None, 0
        self.asked_read = True
        for category, entry in self.steps.items():
            if entry[1]:
                held = entry[0].reserved_bytes
                if held:
                    largest = max(largest, min(entry[1], held))
                elif category != asked:
                    entry[1] = 0                     # everything of that category has been returned
        if largest > self.step:
            self.step = largest
        return largest

    # ---------------------------------------------------------------- readings
    def tick(self):
        if self.reading_now:
            return
        if perf_counter() >= self.next:
            self.read()

    def _burst_remaining(self, reading, others):
        """What declared steps may still take: their counts less what the process has grown by.

        Growth that another owner's own reservation funds is not the step's: a
        rise of the other reservations since the step was declared is taken off
        the growth first. (That owner may have allocated less than it reserved;
        the step then keeps more than it needs, never less.)
        """
        return sum(max(0, count-max(0, reading-declared-max(0, others-beside)))
                   for count, declared, beside in self.bursts)

    def _refuse(self, **facts):
        self.refusal = dict(stage=self.stages[-1]['name'], **facts)
        self.failed = True
        raise self.resources.MemoryLimitError(facts['test'])

    def read(self):
        """Read the process and its workers; check the rise; bring the lease to the reading."""
        if self.reading_now or self.closed:
            return
        self.reading_now = True
        try:
            now = perf_counter()
            info = self.process.memory_info()
            reading = max(info.private, info.rss)
            others = self.budget.reserved_bytes-self.lease.count
            if self.last is not None:
                rise = reading-self.last
                if rise > self.largest_rise:
                    self.largest_rise = rise
                if rise > self.stages[-1]['largest_rise_bytes']:
                    self.stages[-1]['largest_rise_bytes'] = rise
                returned = max(0, self.others-others)
                self.largest_return = max(self.largest_return, returned)
                # What the ledger holds for this process as it stands, before this
                # reading moves the lease: every other reservation, and this lease
                # less its workers' share. Without another owner's doing it is the
                # last reading, the margin and the unused part of a declared step.
                # A reservation another owner returned since then has lowered it by
                # as much; one admitted since then (always after a reading) has
                # raised it. The process must not stand above it, now or at a new
                # highest commit. A scope that is already failing is not judged
                # again: its ledger only goes on following the process.
                standing = others+self.lease.count-self.worker_share
                room = standing-reading
                if self.least_room is None or room < self.least_room:
                    self.least_room = room
                if reading > standing and not self.failed:
                    self._refuse(test='process memory rose above its reservation between two readings',
                                 rise_bytes=rise, other_reservations_returned_bytes=returned,
                                 allowed_bytes=standing-self.last, reading_bytes=reading,
                                 seconds_since_last_reading=now-self.last_time)
                if info.peak_pagefile > self.last_peak:
                    # A new highest commit since the last reading: how far above that reading it stood.
                    transient = info.peak_pagefile-self.last
                    if transient > self.largest_transient:
                        self.largest_transient = transient
                    if transient > self.stages[-1]['largest_transient_bytes']:
                        self.stages[-1]['largest_transient_bytes'] = transient
                    if info.peak_pagefile > standing and not self.failed:
                        self._refuse(test='process memory peaked above its reservation between two readings',
                                     transient_bytes=transient, other_reservations_returned_bytes=returned,
                                     allowed_bytes=standing-self.last, reading_bytes=reading,
                                     peak_bytes=info.peak_pagefile,
                                     seconds_since_last_reading=now-self.last_time)
                self.longest_gap = max(self.longest_gap, now-self.last_time)
            self.last_peak = info.peak_pagefile
            workers = self.expected*CHILD_START
            held = 0
            for pid, child in tuple(self.children.items()):
                try:
                    own = child['process'].memory_info()
                    size = max(own.private, own.rss)
                except (self.psutil.NoSuchProcess, self.psutil.AccessDenied):
                    # Ended between two readings: its memory has been returned.
                    del self.children[pid]
                    continue
                if child['last'] is None:
                    # Until its first reading a worker stands under its starting allowance:
                    # nothing it has taken so far, kept or returned, may have been above it.
                    highest = max(size, own.peak_pagefile, own.peak_wset)
                    self.largest_child_start = max(self.largest_child_start, highest)
                    if highest > CHILD_START and not self.failed:
                        self._refuse(test='a worker process started above its allowance',
                                     worker_bytes=size, worker_peak_bytes=highest, allowed_bytes=CHILD_START)
                else:
                    rise = size-child['last']
                    self.largest_child_rise = max(self.largest_child_rise, rise)
                    if rise > CHILD_MARGIN and not self.failed:
                        self._refuse(test='a worker process rose above its reservation between two readings',
                                     rise_bytes=rise, allowed_bytes=CHILD_MARGIN, worker_bytes=size)
                    if own.peak_pagefile > child['commit']:
                        # A new highest commit of the worker since its last reading, as for the caller.
                        above = own.peak_pagefile-child['last']
                        self.largest_child_transient = max(self.largest_child_transient, above)
                        if above > CHILD_MARGIN and not self.failed:
                            self._refuse(test='a worker process peaked above its reservation between two readings',
                                         transient_bytes=above, allowed_bytes=CHILD_MARGIN, worker_bytes=size,
                                         worker_peak_bytes=own.peak_pagefile)
                child['commit'] = own.peak_pagefile
                child['last'] = size
                child['peak'] = max(child['peak'], size)
                workers += size+CHILD_MARGIN
                held += size
            target = reading+MARGIN+self._burst_remaining(reading, others)+self._live_step()+workers
            self.others = others
            want = max(0, target-self.others)
            self.worker_share = workers
            self.last, self.last_time, self.next = reading, now, now+INTERVAL
            self.readings += 1
            self.whole['readings'] += 1
            self.stages[-1]['readings'] += 1
            self._note('process_peak_bytes', reading+held)
            self._note('private_peak_bytes', info.private)
            self._note('working_set_peak_bytes', info.rss)
            self._note('workers_peak_bytes', held)
            if want != self.lease.count:
                try:
                    self.lease.resize(want)
                except self.resources.MemoryLimitError:
                    self.refusal = dict(stage=self.stages[-1]['name'],
                        test='measured process memory with its margin against the ledger ceiling',
                        reading_bytes=reading, workers_bytes=workers, target_bytes=target,
                        other_reservations_bytes=self.others, max_bytes=self.budget.max_bytes)
                    self.failed = True
                    raise
            self._note('reserved_peak_bytes', self.others+self.lease.count)
        finally:
            self.reading_now = False

    # ------------------------------------------------------------ single steps
    def begin_burst(self, count):
        if type(count) is not int or count < 0:
            raise ValueError('A declared step needs a nonnegative integer count')
        self.read()
        entry = [count, self.last, self.others]
        self.bursts.append(entry)
        try:
            self.read()          # admits the count on the run's ledger, or refuses before the step
        except BaseException:
            self.bursts.remove(entry)
            raise
        return entry

    def end_burst(self, entry):
        # The ledger holds the step's count until the next reading has judged the step
        # against it; that same reading then gives back what the step did not keep.
        self.bursts.remove(entry)
        if not self.failed:
            self.read()

    # ----------------------------------------------------------------- workers
    def expect_workers(self, count):
        """Charge ``count`` workers their starting allowance before any is started."""
        if type(count) is not int or count < 0:
            raise ValueError('Worker count must be a nonnegative integer')
        self.expected += count
        try:
            self.read()
        except BaseException:
            self.expected -= count
            raise

    def worker_started(self, pid):
        if self.expected <= 0:
            raise RuntimeError('A worker must be expected before it is started')
        self.children[pid] = dict(process=self.psutil.Process(pid), last=None, peak=0, commit=0)
        self.read()              # still charged its allowance as well, until the next line
        self.expected -= 1
        self.read()

    def worker_stopped(self, pid):
        """Only after the worker process has ended and been joined."""
        child = self.children.pop(pid, None)
        if child is not None and child['process'].is_running():
            self.children[pid] = child
            raise RuntimeError('A worker is released only after it has ended')
        if not self.failed:
            self.read()

    def unexpect_workers(self, count):
        """Return the starting allowance of workers that were never started."""
        if count > self.expected:
            raise RuntimeError('More starting allowances returned than held')
        self.expected -= count
        if not self.failed:
            self.read()

    # --------------------------------------------------------------- lifecycle
    def start(self):
        self.lease.__enter__()
        self.read()
        return self

    def fail(self):
        """The call is failing: stay installed, so the ledger keeps following the process."""
        self.failed = True

    def close(self):
        """The producer has returned: its workspaces are gone, the result is admitted."""
        if self.closed:
            return
        if self.bursts or self.expected or self.children:
            raise RuntimeError('A declared step or worker outlives the metered call')
        self.read()
        left = self.side.reserved_bytes
        if left and self.categories is not EVERY:
            raise RuntimeError('Producer workspaces remain after the producer returned: %d bytes' % left)
        if left:
            # A re-read may leave objects with the reader (a restored plan, a record) whose
            # reservations carry no name that says so. They were admitted at their calculated
            # figures on the side ledger and are returned there, where the run's ledger cannot see
            # it. That much is therefore held on the run's ledger from here on, under its own
            # category; ``settle_carried`` lowers it to what is still reserved.
            self.left = {name: count for name, count in self.side.statistics()['categories'].items() if count}
            self.carried = self.resources._ResizableLease(self.budget, category=CARRIED)
            self.carried.__enter__()
            self.carried.resize(left)
            _state['carried'].append(self)
        self.stages[-1]['seconds'] = round(perf_counter()-self.began-self.stages[-1]['began_seconds'], 3)
        self.whole['seconds'] = round(perf_counter()-self.began, 3)
        self.closed = True
        self.next = float('inf')         # a safe point that outlives the call reads nothing
        if getattr(self.budget, '_scope', None) is self:
            self.budget._scope = None
        self.lease.__exit__(None, None, None)

    def report(self):
        side = self.side.statistics()
        largest = sorted(side['category_peaks'].items(), key=lambda item: -item[1])[:24]
        return dict(schema=SCHEMA, metered=True, scope=self.name, closed=self.closed, failed=self.failed,
            own_categories=('every category beginning %r except %s' % (PREFIX, ', '.join(sorted(KEPT)))
                            if self.categories is None else
                            'every category except those ending %r and %s' % (RETAINED, ', '.join(sorted(KEPT)))
                            if self.categories is EVERY else sorted(self.categories)),
            largest_live_step_bytes=self.step, step_floor_bytes=STEP_FLOOR,
            carried_after_the_scope=None if self.carried is None else dict(
                bytes=self.carried.count, left_on_the_side_ledger_at_close=getattr(self, 'left', None)),
            margin_bytes=MARGIN, worker_margin_bytes=CHILD_MARGIN, worker_start_bytes=CHILD_START,
            reading_interval_seconds=INTERVAL, reading='max(private bytes, working set) of this process',
            readings=self.readings, admissions=self.admissions, side_ledger_admissions=self.side_admissions,
            largest_rise_between_readings_bytes=self.largest_rise,
            largest_new_peak_above_the_reading_before_it_bytes=self.largest_transient,
            operating_system_peak_commit_bytes=self.last_peak,
            largest_worker_rise_between_readings_bytes=self.largest_child_rise,
            largest_worker_new_peak_above_the_reading_before_it_bytes=self.largest_child_transient,
            largest_worker_at_its_first_reading_peak_included_bytes=self.largest_child_start,
            largest_return_by_other_owners_between_readings_bytes=self.largest_return,
            least_room_between_the_process_and_what_the_ledger_held_for_it_bytes=self.least_room,
            longest_gap_between_readings_seconds=round(self.longest_gap, 4),
            ledger_max_bytes=self.budget.max_bytes, whole=dict(self.whole),
            stages=[dict(row) for row in self.stages if row['name'] != 'begin' or row['readings']],
            earlier_rule_refusal=self.earlier_rule_refusal, refusal=self.refusal,
            side_ledger=dict(reserved_bytes=side['reserved_bytes'], peak_reserved_bytes=side['peak_reserved_bytes'],
                             largest_category_peaks=[list(item) for item in largest]))


# The one mutable object of this module. Lower-case and never rebound, so the loaded-dependency
# identity of the issuer neither captures nor guards it (the candidate's convention for such state).
_state = dict(reports=[], returned=0, carried=[])


def open(budget, *, categories=None, name='forward-call'):
    """Meter one scope on ``budget``; None where the earlier rules apply.

    Without ``categories`` the scope is a forward call. With a set of category
    names it is one exact-arithmetic workspace outside the producer, and only
    those categories are its own. A meter left by a failed scope stays
    installed and is taken over: the failed frames still hold their workspaces
    on its side ledger.
    """
    if not supported(budget):
        return None
    settle_carried(budget)
    current = getattr(budget, '_scope', None)
    if current is not None:
        if type(current) is not Meter or not current.failed:
            raise RuntimeError('This budget already has an admission scope')
        if categories is None or current.categories is None:
            current.categories = None                  # a forward call's categories
        elif categories is EVERY or current.categories is EVERY:
            current.categories = EVERY
        else:
            current.categories |= frozenset(categories)
        current.failed = False
        current.bursts.clear()
        # What the failed scope did to the process is not this one's to be judged for: the next
        # reading starts afresh, as a new meter's first reading does.
        current.last = current.last_time = None
        current.asked, current.asked_read = (None, 0), True
        current.stage('begin-after-failure')
        current.read()
        return current
    if not fits(budget):
        return None
    meter = Meter(budget, categories, name).start()
    budget._scope = meter
    return meter


@contextmanager
def scope(budget, categories, name):
    """Meter one exact-arithmetic workspace outside the producer, where the runtime is supported.

    ``categories`` names that workspace's own categories. Everything else the
    ledger holds while the scope is open must stay as it is: a reservation
    another owner returns in that time counts against the margin. On an
    exception the meter stays, as after a failed forward call.
    """
    if active(budget) is not None and not budget._scope.failed:
        # Inside a metered scope already: its categories are admitted as that scope has them.
        yield None
        return
    meter = open(budget, categories=categories, name=name)
    try:
        yield meter
    except BaseException:
        if meter is not None:
            meter.fail()
        raise
    finish(meter)


def read_scope(budget, name='committed-read'):
    """Meter a re-read of committed records: everything it admits, except what the reader keeps.

    The caller is the holder of the budget (a harness or a reopen probe), around
    one open or inspection of a saved workflow. Inside, the ledger holds the
    process, its margin and the largest single calculated step asked for so
    far; the read's own reservations are admitted on the side ledger at their
    unchanged calculated figures. A category ending ``-retained`` is the
    reader's to keep and is admitted on the run's ledger as before. Anything
    else still reserved when the scope ends is held on the run's ledger from
    then on (see ``Meter.close``). Where the meter does not apply, nothing
    differs.
    """
    return scope(budget, EVERY, name)


def settle_carried(budget=None):
    """Lower what earlier re-reads left held on the run's ledger to what is still reserved.

    Returns the bytes still carried for ``budget`` (for every budget if None).
    """
    total = 0
    for meter in tuple(_state['carried']):
        if budget is not None and meter.budget is not budget:
            continue
        still = meter.side.reserved_bytes
        if still < meter.carried.count:
            meter.carried.resize(still)
        if not still:
            meter.carried.__exit__(None, None, None)
            _state['carried'].remove(meter)
        total += still
    return total


def fits(budget):
    """Whether this ledger can hold the process and its margin at all.

    The meter's share is what the process and its margin exceed the ledger's
    other reservations by. A ledger too small for that (a small test
    allowance, for example) cannot hold a measured charge; its calls run under
    the earlier rules, which never counted the interpreter. Asked once, when a
    scope opens.
    """
    import psutil
    info = psutil.Process().memory_info()
    need = max(info.private, info.rss)+MARGIN-budget.reserved_bytes
    return need <= budget.available_bytes


def finish(meter):
    """Close a meter after its producer returned and keep its report for the caller."""
    if meter is None:
        return None
    meter.close()
    report = meter.report()
    _state['reports'].append(report)
    _state['returned'] += 1
    del _state['reports'][:-KEPT_REPORTS]
    return report


def returned():
    """How many metered calls of this process have returned."""
    return _state['returned']


def last_report():
    """The report of the most recent metered call of this process, or None."""
    return _state['reports'][-1] if _state['reports'] else None


def settle(budget):
    """Close the meter a failed call left, once that call's frames have gone.

    A failed call keeps its workspaces, and so its meter, for as long as its
    error and traceback live. A caller that has dropped them and goes on using
    the budget calls this: if nothing is left on the side ledger the meter is
    closed and its share returned. Returns whether the budget is unmetered now.
    """
    meter = getattr(budget, '_scope', None)
    if meter is None:
        return True
    if type(meter) is not Meter or not meter.failed or meter.side.reserved_bytes:
        return False
    meter.bursts.clear()
    for pid in tuple(meter.children):
        if not meter.children[pid]['process'].is_running():
            del meter.children[pid]
    if meter.children:
        return False
    meter.expected = 0
    meter.failed = False
    finish(meter)
    return True


def unmetered_report(budget):
    """For the record of a call that ran under the earlier rules."""
    facts = runtime(budget)
    return dict(schema=SCHEMA, metered=False, runtime=facts,
                process_and_margin_fit_the_ledger=fits(budget) if all(facts.values()) else None)


def record(budget):
    """What a driver writes into its receipt: every metered scope of this process.

    The reports of the scopes that returned, in order (at most the last
    ``KEPT_REPORTS``), each with its name; the report of one that failed and
    left its meter on the budget; or, when nothing was metered, the runtime
    facts that say why.
    """
    current = getattr(budget, '_scope', None)
    failed = current.report() if type(current) is Meter else None
    if not _state['reports'] and failed is None:
        return unmetered_report(budget)
    return dict(schema=SCHEMA, metered=True, returned_calls=[dict(item) for item in _state['reports']],
                returned_call_count=_state['returned'], failed_call=failed)
