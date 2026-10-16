import sys
sys.path[:0] = ['C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/so/s4/pkg']
from atlas_tectonics import integration_parallel_rolling as RB

class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now

class FakeSession:
    def __init__(self):
        self.batches, self.log, self.seconds = {}, [], {}
        self.stats = {'refused': 0}; self.launched = []; self.on_wait = None; self.last_error = None
    def running(self): return sum(1 for b in self.batches.values() if not b['done'])
    def check(self): return True
    def ended(self): return 'ended', None
    def active(self): return True
    def done(self, b): return b['done']
    def launch(self, jobs, timeout):
        i = len(self.launched); b = self.batches[i] = dict(index=i, jobs=list(jobs), done=False)
        self.launched.append(b); return b
    def retire(self, b): self.batches.pop(b['index'], None)

def mk(opener, clock, **kw):
    args = dict(session=opener, estimate=lambda l: (2.0, 3.0), beyond=lambda: 0, workers=2, batch_seconds=4.0,
                batch_jobs=8, horizon=64, minimum_seconds=1.0, startup_seconds=0.1, transfer_seconds=0.01,
                contention=1.0, benefit_ratio=1.0, timeout_seconds=60.0, clock=clock)
    args.update(kw)
    return RB.Schedule(**args)

def drive(plan, clock, n, step, opens):
    kept_log = []
    for i in range(n):
        while plan.hungry() and plan.offered < n:
            plan.offer(('job', plan.offered), 0.0, 'c')
        plan.advance()
        kept = plan.reached(); kept_log.append(kept)
        if kept: plan.ran(step)
        clock.now += step
    plan.close()
    return kept_log

# 1. pass ends during a deferral: report
c = Clock(); opens = []
p = mk(lambda: (opens.append(c.now), RB.LATER)[1], c)
drive(p, c, 10, 1.0, opens)
r = p.report()
print('1 ended-deferred:', r['route'], r['reason'], r['stopped'], repr(r['detail']), r['reasons'], 'opens', len(opens))

# 2. clock backwards after a deferral
c = Clock(); opens = []
p = mk(lambda: (opens.append(c.now), RB.LATER)[1], c)
for i in range(8): p.offer(('job', i), 0.0, 'c')
p.advance(); c.now = -1e6
for i in range(1000): p.advance()
print('2 clock-back opens', len(opens), 'plans', p.totals['plans'])

# 3. count at stop
c = Clock(); opens = []
p = mk(lambda: (opens.append(c.now), RB.LATER)[1], c)
drive(p, c, 4000, 1.0, opens)
print('3 opens', len(opens), 'stopped', p.stopped, repr(p.detail), p.reasons)

# 4. LATER then None: stops at once, no more opens
c = Clock(); opens = []; answers = [RB.LATER, None]
def op():
    opens.append(c.now); return answers[min(len(opens), 2)-1]
p = mk(op, c)
drive(p, c, 200, 1.0, opens)
print('4 opens', len(opens), 'stopped', p.stopped, p.reasons)

# 5. late open: first launched index never below position at open
c = Clock(); opens = []; s = FakeSession(); answers = [RB.LATER, RB.LATER, s]
def op2():
    opens.append(c.now); return answers[min(len(opens), 3)-1]
p = mk(op2, c)
log = drive(p, c, 200, 1.0, opens)
firsts = [row['first'] for row in p.recent]
print('5 opens', opens, 'first held positions', firsts[:3], 'first not-kept index', log.index(False) if False in log else None, 'report', p.report()['route'])

# 6. gate refusal between deferrals stops; gate exception
c = Clock(); opens = []; g = [None]
p = mk(lambda: (opens.append(c.now), RB.LATER)[1], c, gate=lambda: g[0])
for i in range(8): p.offer(('job', i), 0.0, 'c')
p.advance(); g[0] = ('timing binding changed', 'x'); c.now = 100
p.advance()
print('6 opens', len(opens), 'stopped', p.stopped)
