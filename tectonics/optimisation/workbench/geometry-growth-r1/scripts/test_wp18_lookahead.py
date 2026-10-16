"""Unit test of WP18 part 1's endpoint lookahead (transforms/wp18_endpoint_lookahead.py) on fakes.

Drives AutomaticEndpoints exactly as integration_differential_ale._enclose does (prepare, then per
support: bind_support, then claim or checkpoint_consumed per endpoint request in router order)
against a fake schedule, and checks that:
1. every request is offered once, in router order, with RC1's label, and every claim/checkpoint
   reaches the request it offered (no 'unlisted', no stop), at several horizons;
2. supports are read ahead across support boundaries, and _beyond() estimates the rest;
3. a router support that differs from the read-ahead one stops the schedule (serial continues);
4. without prepare() the route is per support, as in RC1;
5. compact supports: offered jobs hold Step 8's retained handle (faked here), read ahead through
   support_fields, and never the temporary native support;
6. (r2) with no worker session open, supports are read ahead only while the schedule's plan
   asks for more (offered < wanted), and reading ahead resumes once a session opens; once a
   lookahead reaches its horizon with no session open, nothing more is read ahead (sated);
7. (r2) compact: the identities memo drops each retained handle once the router has passed its
   support, so the pass holds only the handles in sight; handles are held (not their ids) and
   only for supports with requests; the peaks are reported;
8. (r2) a stop drops the support being read at once (non-compact and compact).
Usage: test_wp18_lookahead.py <runtime folder holding atlas_tectonics>
"""
import sys
from collections import deque
from pathlib import Path

# The runtime first, then composed-r1's helpers (its dispatch module imports Step 8's
# partition_routing_patch at load), as rc1_env does for test runtimes.
sys.path[:0] = [sys.argv[1], str(Path(__file__).resolve().parents[2] / 'composed-r1' / 'helpers')]
from atlas_tectonics import integration_component_volume_auto as E  # noqa: E402
import partition_routing_patch as fake  # noqa: E402  (two functions replaced below, this process only)

assert 'def _read_ahead' in open(E.__file__, encoding='utf8').read(), 'runtime lacks the WP18 transform'


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
    print('%-58s %s' % (name, 'ok' if condition else 'FAIL'))


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

print('FAILED: %s' % failures if failures else 'ALL PASS')
sys.exit(1 if failures else 0)
