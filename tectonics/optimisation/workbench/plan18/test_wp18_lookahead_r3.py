"""Synthetic endpoint lookahead controls for the selected runtime.
Usage: test_wp18_lookahead_r3.py SOURCE_TREE/src SOURCE_TREE/helpers [--overlay TRANSFORM]
Exercises router order, bounded lookahead, deferral, mismatch cleanup and fake-session scheduling.
No real worker, captured interval or scientific workload is launched.
"""
import ctypes
import sys
from collections import deque
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

if len(sys.argv) not in (3, 5) or (len(sys.argv) == 5 and sys.argv[3] != '--overlay'):
    raise SystemExit(__doc__)
RUNTIME, HELPERS = sys.argv[1:3]
OVERLAY = sys.argv[4] if len(sys.argv) == 5 else None
if sys.platform == 'win32':
    # Idle priority: a test must not disturb a quiet measurement that starts while it runs.
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
sys.path[:0] = [RUNTIME, HELPERS]
from atlas_tectonics import integration_component_volume_auto as E  # noqa: E402
from atlas_tectonics import integration_parallel_rolling as RB  # noqa: E402
import partition_routing_patch as fake  # noqa: E402  (two functions replaced below, this process only)


def _sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


executed = Path(E.__file__).read_bytes()
if OVERLAY is not None:
    import importlib.util
    spec = importlib.util.spec_from_file_location('wp18_r3_transform', OVERLAY)
    transform = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transform)
    text = transform.transform(executed.decode('utf-8'))      # refuses an unreviewed input
    exec(compile(text, E.__file__ + ' [r3 overlay]', 'exec'), E.__dict__)
    executed = text.encode('utf-8')
print('test        %s %s' % (Path(__file__).name, _sha(__file__)))
print('runtime     %s' % RUNTIME)
print('auto        %s on disk %s, executed %s' % (Path(E.__file__).name, _sha(E.__file__), sha256(executed).hexdigest()))
print('rolling     %s %s' % (Path(RB.__file__).name, _sha(RB.__file__)))
print('helpers     %s %s' % (Path(fake.__file__).name, _sha(fake.__file__)))
if OVERLAY is not None:
    print('overlay     %s %s' % (Path(OVERLAY).name, _sha(OVERLAY)))
print('python      %s' % sys.version.split()[0])

assert hasattr(E, '_WANTING') and 'def _read_ahead' in executed.decode('utf-8'), 'runtime lacks the WP18 r3 transform'


class Native:
    def __init__(self, sid, parts):
        self.support_id, self._parts = sid, parts

    def record(self):
        return {'components': [dict(p) for p in self._parts]}


class CompactNative(Native):
    _compact_ref = 'ref'


class Handle:
    def __init__(self, native):
        self.support_id, self._parts = native.support_id, native._parts


class Owned:
    def __init__(self, value):
        self.value = value


reads = []


def _fields(handle, fields):
    assert type(handle) is Handle and fields == ('components',)
    reads.append(handle.support_id)
    return Owned({'components': [dict(p) for p in handle._parts]})


fake.retain_support = lambda s: s if type(s) is Handle else Handle(s)
fake.support_fields = _fields


class Schedule:
    def __init__(self, horizon):
        self.horizon, self.ahead, self.stopped, self.log, self.given = horizon, deque(), None, [], []
        self.session, self.on_offer = 'open', None
        self.offered, self._wanted = 0, 0       # as the rolling Schedule: offers made, offers its plan asked for
        self.reason = None                      # as the rolling Schedule: its last plan's note (r3 reads it)

    def hungry(self):
        return self.stopped is None and len(self.ahead) < self.horizon

    def offer(self, job, prefix, label):
        self.ahead.append(job)
        self.given.append((job, label))
        self.offered += 1
        if self.on_offer is not None:
            self.on_offer(job)

    def reached(self):
        self.log.append(('reached', self.ahead.popleft()[1:3]))

    def checkpoint_consumed(self):
        self.log.append(('checkpoint', self.ahead.popleft()[1:3]))

    def unlisted(self):
        self.log.append(('unlisted', None))

    def advance(self):
        pass

    def _stop(self, reason, detail):
        if self.stopped is None:
            self.stopped = (reason, detail)


def controller(horizon):
    c = object.__new__(E.AutomaticEndpoints)
    c.width, c.order, c.jobs, c.left = None, deque(), None, 0
    c.label = c.started = None
    c.prepared, c.checkpoint_hits = False, 0
    c.supports, c.cursor, c.bound = None, 0, 0
    c.unbound, c.read = deque(), [0, 0]
    c.handles, c.peak, c.sated, c.identities = deque(), [0, 0], False, {}
    c.deferrals = 0
    c.schedule, c.closed, c.session, c.total, c._mark = Schedule(horizon), False, None, 0, None
    return c


def mesh(kind=Native, n=9):
    supports = []
    for s in range(n):
        parts = [dict(logical_cell_id='s%dc%d' % (s, k), parent_cell_id=None if (s+k) % 3 == 0 else 'p',
                      constraints=['a']*(k % 4), partition_path=[0]*(s % 5)) for k in range(s % 6)]
        supports.append(kind('sid%d' % s, parts))
    return supports


def drive(c, supports, prepare=True, checkpoints=(), bound=None):
    if prepare:
        c.prepare(supports)
    serial, labels = [], []
    for index, support in enumerate(supports):
        router = bound(index, support) if bound else support
        c.bind_support(router, {'components': support.record()['components']})
        for part in support._parts:
            for endpoint in ('start', 'end'):
                if endpoint == 'start' and part['parent_cell_id'] is None:
                    continue
                request = (part['logical_cell_id'], endpoint)
                serial.append(request)
                labels.append((endpoint, len(part['constraints']), len(part['partition_path'])))
                if request in checkpoints:
                    c.checkpoint_consumed(*request)
                else:
                    c.claim(dict(logical_cell_id=request[0], endpoint=endpoint), None)
    return serial, labels


failures = []


def check(name, condition):
    if not condition:
        failures.append(name)
    print('%-72s %s' % (name, 'ok' if condition else 'FAIL'))


# 1 and 2: serial order, labels, reach, at several horizons; reading across supports.
for horizon in (1, 2, 3, 7, 64, 4096):
    supports = mesh()
    c = controller(horizon)
    serial, labels = drive(c, supports, checkpoints={('s4c1', 'end'), ('s8c0', 'end')})
    s = c.schedule
    offered = [job[1:3] for job, _ in s.given]
    check('h=%d no stop' % horizon, s.stopped is None)
    check('h=%d offered once in router order' % horizon, offered == serial)
    check('h=%d RC1 labels' % horizon, [label for _, label in s.given] == labels)
    check('h=%d every claim reached its offer' % horizon,
          [entry[1] for entry in s.log] == serial and all(entry[0] != 'unlisted' for entry in s.log))
    check('h=%d jobs are (support, key, endpoint, {})' % horizon,
          all(type(job[0]) is Native and job[3] == {} for job, _ in s.given))
    check('h=%d nothing left unbound' % horizon, not c.unbound and not c.order and c.bound == len(supports))

# _beyond after the first support at a large horizon: everything was read ahead.
c = controller(4096)
supports = mesh()
c.prepare(supports)
c.bind_support(supports[0], {'components': supports[0].record()['components']})
total = sum(1 + (p['parent_cell_id'] is not None) for s in supports for p in s._parts)
check('lookahead offered the whole small mesh after one bind', len(c.schedule.given) == total)
check('_beyond is zero when all supports are read', c._beyond() == 0)
c = controller(4)
c.prepare(supports)
c.bind_support(supports[0], {'components': supports[0].record()['components']})
supports_read, jobs_read = c.read
expect = c.left + (len(supports)-c.cursor)*jobs_read/supports_read
check('_beyond = left + unread supports x jobs per support', abs(c._beyond()-expect) < 1e-12 and c._beyond() > 0)

# 3: a router support differing from the read-ahead one stops the schedule.
supports = mesh()
c = controller(4096)
drive(c, supports, bound=lambda i, s: Native('other', s._parts) if i == 5 else s)
check('differing router support stops the schedule',
      c.schedule.stopped is not None and 'differs from the router order' in str(c.schedule.stopped[1]))

# 4: no prepare: per support, as RC1.
supports = mesh()
c = controller(3)
serial, _ = drive(c, supports, prepare=False)
s = c.schedule
check('no prepare: no stop, router order, all reached',
      s.stopped is None and [job[1:3] for job, _ in s.given] == serial and [e[1] for e in s.log] == serial)
check('no prepare: nothing read ahead', c.read[0] == len([x for x in supports]) and not c.unbound)

# 5: compact supports hold handles, read ahead through support_fields.
reads.clear()
supports = mesh(CompactNative)
c = controller(4096)
serial, _ = drive(c, supports)
s = c.schedule
check('compact: no stop, router order', s.stopped is None and [job[1:3] for job, _ in s.given] == serial)
check('compact: every offered job holds a retained handle', all(type(job[0]) is Handle for job, _ in s.given))
check('compact: supports after the first read via support_fields once',
      reads == ['sid%d' % i for i in range(1, len(supports))])

# 6 (r2): with no worker session open, read ahead only what the schedule's plan asks for.
# 6a: nothing asked (below threshold, no estimates yet, refused or deferred): nothing read ahead.
supports = mesh()
c = controller(4096)
c.schedule.session = None
serial, _ = drive(c, supports)
s = c.schedule
check('no session: no stop, router order, all reached',
      s.stopped is None and [job[1:3] for job, _ in s.given] == serial and [e[1] for e in s.log] == serial)
check('no session: nothing read ahead', c.peak[0] == 0 and c.read[0] == len(supports) and not c.unbound)
# 6b: the plan asks for 5 offers to cut a first batch: supports are read ahead until 5 are offered
# (the support being read is finished), then no further, and the order is unchanged.
supports = mesh()
c = controller(4096)
c.schedule.session, c.schedule._wanted = None, 5
asked = []
serial, _ = drive(c, supports, bound=lambda i, s, c=c: asked.append((i, c.schedule.offered, c.cursor)) or s)
s = c.schedule
check('asked: no stop, router order, all reached',
      s.stopped is None and [job[1:3] for job, _ in s.given] == serial and [e[1] for e in s.log] == serial)
check('asked: read ahead to the request, then stopped reading',
      asked[1][1] >= 5 and 1 < asked[1][2] < len(supports) and c.peak[0] >= 1)
check('asked: no read ahead once offered reached wanted',
      all(cursor == i for i, _, cursor in asked if i >= asked[1][2]))
# 6c: a session that opens mid-pass resumes reading ahead from there.
supports = mesh()
c = controller(4096)
c.schedule.session = None
cursors = []


def opens(i, s, c=c):
    cursors.append((i, c.cursor))
    if i == 4:
        c.schedule.session = 'open'
    return s


serial, _ = drive(c, supports, bound=opens)
s = c.schedule
check('opens: no stop, router order, all reached',
      s.stopped is None and [job[1:3] for job, _ in s.given] == serial and [e[1] for e in s.log] == serial)
check('opens: nothing ahead before, reading ahead after',
      all(cursor == i for i, cursor in cursors if i <= 4) and cursors[5][1] > 5 and c.peak[0] >= 1)
# 6d: the plan keeps asking (wanted never met) but no session opens: once the lookahead reaches
# its horizon, nothing more is read ahead; the router catches up and stays caught up.
supports = mesh()
c = controller(7)
c.schedule.session, c.schedule._wanted = None, 10**9
seen6d = []
serial, _ = drive(c, supports, bound=lambda i, s, c=c: seen6d.append((i, c.cursor, c.sated)) or s)
s = c.schedule
caught = [i for i, cursor, _ in seen6d if cursor == i and i > 0]
check('sated: no stop, router order, all reached',
      s.stopped is None and [job[1:3] for job, _ in s.given] == serial and [e[1] for e in s.log] == serial)
check('sated: read ahead to the horizon, then no further',
      c.sated and seen6d[1][1] > 2 and caught and all(cursor == i for i, cursor, _ in seen6d if i >= caught[0]))

# 7 (r2): the identities memo (filled here per offer, as _choose does) keeps only handles in sight.
reads.clear()
supports = mesh(CompactNative)
c = controller(4096)
seen = []


def memo(job, c=c):
    c.identities[id(job[0])] = [job[0], job[0].support_id, False]
    seen.append(len(c.identities))


stale = []


def router(index, support, c=c):
    # Before support `index` binds, every support before index-1 was pruned at an earlier bind.
    found = {entry[1] for entry in c.identities.values()} & {'sid%d' % k for k in range(index-1)}
    if found:
        stale.append((index, sorted(found)))
    return support


c.schedule.on_offer = memo
drive(c, supports, bound=router)
check('compact memo: no stop; no passed support stays in the memo', c.schedule.stopped is None and not stale)
check('compact memo: only the last support remains at the end',
      {entry[1] for entry in c.identities.values()} <= {'sid%d' % (len(supports)-1)})
check('compact memo: memo held more than one support while reading ahead', max(seen) > 2)
check('compact memo: peaks reported', c.peak[0] >= 1 and c.peak[1] >= 1)

# 8 (r2): a stop drops the support being read at once (non-compact and compact).
for kind in (Native, CompactNative):
    supports = mesh(kind)
    c = controller(3)
    held = []
    if kind is CompactNative:
        # Fill the memo per offer as in 7; a stop must release every held handle and its entry.
        c.schedule.on_offer = lambda job, c=c: (c.identities.__setitem__(id(job[0]), [job[0], job[0].support_id, False]),
                                                held.append(len(c.handles)))
    drive(c, supports, bound=lambda i, s: Native('other', s._parts) if i == 5 else s)
    check('%s stop: stopped, reading dropped' % kind.__name__,
          c.schedule.stopped is not None and c.jobs is None and not c.unbound and c.left == 0)
    check('%s stop: no handle or memo entry outlives the stop' % kind.__name__,
          not c.handles and not c.identities and (kind is Native or max(held) >= 1))

# 8b (r2.1): a stop by the schedule itself (not a lookahead error) also releases held handles
# and their memo entries at the next bind, not at close.
supports = mesh(CompactNative)
c = controller(3)
held = []
c.schedule.on_offer = lambda job, c=c: (c.identities.__setitem__(id(job[0]), [job[0], job[0].support_id, False]),
                                        held.append(len(c.handles)))
drive(c, supports, bound=lambda i, s, c=c: (c.schedule._stop('session error', None) if i == 5 else None, s)[1])
check('schedule stop: stopped, reading dropped, nothing held',
      c.schedule.stopped == ('session error', None) and c.jobs is None and c.left == 0
      and not c.unbound and not c.handles and not c.identities and max(held) >= 1)


def router_order(c, serial):
    s = c.schedule
    return s.stopped is None and [job[1:3] for job, _ in s.given] == serial and [e[1] for e in s.log] == serial


# 9 (r3 A): with no session open, the schedule's last verdict decides whether to read ahead.
for reason, wants in (('lookahead still growing', True), ('predicted saving does not cover overheads', True),
                      ('eligible work below threshold', False), ('no compatible observations', False),
                      ('nothing to dispatch', False), (None, False)):
    supports = mesh(n=18)
    c = controller(7)
    c.schedule.session, c.schedule.reason = None, reason
    seen9 = []
    serial, _ = drive(c, supports, bound=lambda i, s, c=c: seen9.append((i, c.cursor)) or s)
    caught = [i for i, cursor in seen9 if cursor == i and i > 0]
    check('verdict %r: no stop, router order, all reached' % reason, router_order(c, serial))
    if wants:
        check('verdict %r: reads ahead to the horizon, then no further' % reason,
              c.sated and seen9[1][1] > 2 and caught and all(cursor == i for i, cursor in seen9 if i >= caught[0]))
    else:
        # (sated may still be set: the router's own support can fill a horizon of 7 by itself.)
        check('verdict %r: nothing read ahead' % reason,
              c.peak[0] == 0 and c.read[0] == len(supports) and not c.unbound
              and all(cursor == i for i, cursor in seen9))

# 10 (r3 B): each deferred first open (a changed _deferrals count) renews the cap once.
supports = mesh(n=36)
c = controller(7)
c.schedule.session, c.schedule.reason, c.schedule._deferrals = None, 'lookahead still growing', 0
seen10 = []


def defers(i, s, c=c):
    seen10.append((i, c.cursor, c.sated))
    if i in (12, 24):
        c.schedule._deferrals += 1      # the machine gates deferred a first open
    return s


serial, _ = drive(c, supports, bound=defers)
cursor_at = {i: cursor for i, cursor, _ in seen10}
sated_at = {i: sated for i, _, sated in seen10}
check('deferrals: no stop, router order, all reached', router_order(c, serial))
check('deferrals: sated and caught up before the first deferral', sated_at[12] and cursor_at[12] == 12)
check('deferrals: reading ahead resumes after each deferral', cursor_at[13] > 13 and cursor_at[25] > 25)
check('deferrals: sated and caught up again before the next one',
      sated_at[24] and cursor_at[24] == 24 and all(cursor_at[i] == i for i in range(19, 25)))
check('deferrals: one horizon per deferral, then caught up to the end',
      c.sated and c.deferrals == 2 and all(cursor_at[i] == i for i in range(31, 36)))

# 11 (r3 C): the checkpoint-order and observation-error stops drop the reading at once.
for kind in (Native, CompactNative):
    for fault in ('checkpoint', 'observation'):
        supports = mesh(kind)
        c = controller(3)
        held = []
        if kind is CompactNative:
            c.schedule.on_offer = lambda job, c=c: (c.identities.__setitem__(id(job[0]), [job[0], job[0].support_id, False]),
                                                    held.append(len(c.handles)))
        c.prepare(supports)
        state = None
        for index, support in enumerate(supports):
            c.bind_support(support, {'components': support.record()['components']})
            if index == 5:
                reading = c.jobs is not None or bool(c.unbound)
                holding = kind is Native or bool(c.handles)
                if fault == 'checkpoint':
                    c.checkpoint_consumed('no-such-cell', 'end')
                else:
                    def paid(*args):
                        raise ValueError('observation fault')
                    c.label, c.started, c._paid = ('end', 0, 0), 0.0, paid
                    c.observed()
                state = (reading, holding, c.schedule.stopped, c.jobs, c.left, len(c.unbound), len(c.handles),
                         len(c.identities))
                break
            for part in support._parts:
                for endpoint in ('start', 'end'):
                    if endpoint != 'start' or part['parent_cell_id'] is not None:
                        c.claim(dict(logical_cell_id=part['logical_cell_id'], endpoint=endpoint), None)
        want = 'checkpoint order mismatch' if fault == 'checkpoint' else 'endpoint observation error'
        name = '%s %s stop' % (kind.__name__, fault)
        check('%s: reading and holding when the stop came' % name, state[0] and state[1])
        check('%s: stopped, reading and handles dropped at once' % name,
              state[2] is not None and state[2][0] == want and state[3] is None and state[4:] == (0, 0, 0, 0))

# 12: the real Schedule of this runtime, with fake sessions and a fake clock.


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


clock = Clock()


class FakeSession:
    opened = []

    def __init__(self, **kw):
        self.plan, self.last_error, self.closed = {}, None, False
        self.stats = dict(refused=0, adopted=0, declined=0, started=0, jobs=0, results=0, decided=0,
                          peak_child_rss=0, peak_child_ledger=0)
        self.batches, self.log, self.seconds, self.waits, self.on_wait = [], [], {}, 0, None
        self._n = 0

    def open(self, context):
        FakeSession.opened.append(round(clock.now, 2))
        return True

    def running(self):
        return len(self.batches)

    def check(self):
        return True

    def active(self):
        return True

    def done(self, batch):
        return False

    def launch(self, jobs, timeout):
        self._n += 1
        batch = dict(index=self._n, jobs=len(jobs))
        self.batches.append(batch)
        self.stats['started'] += 1
        return batch

    def retire(self, batch):
        self.batches = [b for b in self.batches if b is not batch]

    def claim(self, request, budget):
        return None

    def close(self):
        self.closed = True


E.ComponentParallelSession = FakeSession
HORIZON, PARTS = 4096, 4
ONE_HORIZON = HORIZON//(2*PARTS) + 1     # supports in one horizon of requests, plus the one being read
DEFERS = hasattr(RB, 'LATER')


def real(plan, minimum, refusals):
    """Drive a real-Schedule pass; plan is [(cost, components)] per support in router order."""
    costs = sorted({cost for cost, _ in plan})
    klass = {cost: index for index, cost in enumerate(costs)}
    clock.now = 0.0
    FakeSession.opened = []
    c = object.__new__(E.AutomaticEndpoints)
    c.width, c.order, c.jobs, c.left = 0, deque(), None, 0
    c.label = c.started = None
    c.prepared, c.checkpoint_hits = False, 0
    c.supports, c.cursor, c.bound = None, 0, 0
    c.unbound, c.read = deque(), [0, 0]
    c.handles, c.peak, c.sated, c.identities = deque(), [0, 0], False, {}
    c.deferrals = 0
    c.closed, c.finished, c.session, c.total, c._mark = False, False, None, 0, None
    c.notes, c.gates, c.workers = [], [], 2
    c.policy = SimpleNamespace(child_bytes=1, predicate_units=1, timeout_seconds=1800.0, budget_fraction=0.5,
                               workers=2)
    c.parent = SimpleNamespace(budget=None, leaves=1, context=None,
                               decision=dict(notes=[], route='serial', reason=None, detail=None))
    c.digest, c.rows, c.exact, c.reason, c.prefix = None, {}, False, None, [0, 0.0]
    left = [refusals]

    def machine():
        if left[0] > 0:
            left[0] -= 1
            c.workers = 0
            return ('cpu', 'busy logical CPUs')
        c.workers = 2
        return None
    c._machine = machine
    c.schedule = sch = RB.Schedule(session=c._open, estimate=lambda label: (costs[label[1]], 2*costs[label[1]]),
                                   beyond=c._beyond, workers=2, batch_seconds=20.0, batch_jobs=512,
                                   horizon=HORIZON, minimum_seconds=minimum, startup_seconds=3.0,
                                   transfer_seconds=0.4, contention=1.3, benefit_ratio=1.0,
                                   timeout_seconds=1800.0, clock=clock)
    given, unlisted, ahead = [], [], [0]
    offer, miss = sch.offer, sch.unlisted
    sch.offer = lambda job, prefix, label: (given.append(job[1:3]), offer(job, prefix, label))[1]
    sch.unlisted = lambda: (unlisted.append(1), miss())[1]
    read_ahead = c._read_ahead

    def counted():
        ahead[0] += sch.session is None
        return read_ahead()
    c._read_ahead = counted
    supports = [Native('sid%d' % s, [dict(logical_cell_id='s%dc%d' % (s, k), parent_cell_id='p',
                                          constraints=[0]*klass[cost], partition_path=[]) for k in range(parts)])
                for s, (cost, parts) in enumerate(plan)]
    c.prepare(supports)
    serial = []
    for support, (cost, _) in zip(supports, plan):
        c.bind_support(support, support.record())
        for part in support._parts:
            for endpoint in ('start', 'end'):
                serial.append((part['logical_cell_id'], endpoint))
                c.claim(dict(logical_cell_id=part['logical_cell_id'], endpoint=endpoint), None)
                clock.now += cost
    stopped = sch.stopped
    c.close()
    # order: every request offered once in router order and reached; prefix: the offers are the
    # router order's first requests (after a stop the rest is unlisted and runs serially).
    result = dict(opened=(FakeSession.opened or [None])[0], order=given == serial and not unlisted,
                  prefix=bool(given) and given == serial[:len(given)], claims=len(serial), offered=len(given),
                  unlisted=len(unlisted), ahead=ahead[0], sated=c.sated, stopped=stopped,
                  deferrals=getattr(sch, '_deferrals', 0),
                  route=(c.parent.decision.get('endpoint_batches') or {}).get('route'))
    print('    pass: %s' % ' '.join('%s=%s' % item for item in sorted(result.items())))
    return result


# 12a: a cheap below-threshold prefix, then requests worth batching (r2 never opened at 0.0197 s).
for cost in (0.0197, 0.040):
    r = real([(0.005, PARTS)]*600 + [(cost, PARTS)]*1900, 120.0, 0)
    check('real %.4f s after a cheap prefix: order kept, every claim reached' % cost, r['order'] and r['stopped'] is None)
    check('real %.4f s after a cheap prefix: a session opens after the prefix' % cost,
          r['opened'] is not None and 24.0 <= r['opened'] < 40.0 and r['route'] == 'parallel')
# 12b: a pass below its threshold reads nothing ahead.
r = real([(0.004, PARTS)]*2500, 120.0, 0)
check('real below threshold: order kept, nothing read ahead, serial',
      r['order'] and r['ahead'] == 0 and r['opened'] is None and r['route'] == 'serial')
# 12c: above threshold, but a cheap prefix of more than a horizon never pays: at most one horizon
# is read ahead without a session (r2's cap, kept; later dearer supports stay serial).
r = real([(0.006, PARTS)]*700 + [(0.03, PARTS)]*1800, 30.0, 0)
check('real never-paying lookahead: order kept, one horizon read ahead, sated',
      r['order'] and r['sated'] and 0 < r['ahead'] <= ONE_HORIZON)
# 12d: machine-gate refusals of the first open.
regions = [(288, 0.007), (125, 0.020), (337, 0.007), (1750, 0.012)]
plan = [(cost, PARTS) for count, cost in regions for _ in range(count)]
if DEFERS:
    for refusals in (1, 2):
        r = real(plan, 120.0, refusals)
        check('real deferral x%d: order kept, a session opens' % refusals,
              r['order'] and r['stopped'] is None and r['opened'] is not None and r['deferrals'] == refusals)
        check('real deferral x%d: at most one horizon per deferral read without a session' % refusals,
              r['ahead'] <= (1 + r['deferrals'])*ONE_HORIZON)
    r = real(plan, 120.0, 3)
    check('real deferral x3: serial once the rest is below threshold, bound kept',
          r['order'] and r['opened'] is None and r['route'] == 'serial' and r['ahead'] <= 4*ONE_HORIZON)
else:
    r = real(plan, 120.0, 1)
    check('real refusal without deferral: stops, offers a router-order prefix, rest serial',
          r['prefix'] and r['offered'] + r['unlisted'] == r['claims'] and r['opened'] is None
          and r['stopped'] == 'session not opened' and r['route'] == 'serial')
    check('real refusal without deferral: one horizon read ahead at most', 0 < r['ahead'] <= ONE_HORIZON)

print('FAILED: %s' % failures if failures else 'ALL PASS')
sys.exit(1 if failures else 0)
