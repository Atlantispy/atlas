"""S4 (Small optimisations, backlog 20, 16 Oct 2026): retry a machine-gate-refused first open later.

Source transform of atlas_tectonics/integration_parallel_rolling.py, generated from Small optimisations' reviewed
candidate (T/so/s4, INTEGRATION.md 13:43) by Geometry's make_s4_transforms.py: the hunks of
base 6daa2d3a... -> candidate c6c8a702..., applied in order, reproduce the candidate byte
for byte. A first worker session that only the machine and ledger gates refused (free cores,
memory, budget or predicate units at that moment) is looked for again at 15 s doubling to
120 s, at most 24 times, while the parent goes on serially; psutil missing still stops at once.
Records and the parent's adoption order cannot change (a late session is an ordinary first
session opened later in the pass). Owner review: G/reviews/s4-retry-review.md.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '6daa2d3a84a224fe9e4724cd0212d0195c474a044440a5f6df36c9cd37c7981a':
        'RC1 composed-r1 runtime-src (no transform touches the rolling module before S4)',
}
CANDIDATE_SHA256 = 'c6c8a7025733f8972ce96f3ea52b43b336bb876cfa833e15bf9397ac1297899b'   # T/so/s4/integration_parallel_rolling.py

EDITS = (
    ('inactive session or a failed gate also stops the schedule. A stopped schedule\n'
     'is never restarted and nothing is retried.\n'
     '\n',
     'inactive session or a failed gate also stops the schedule. A stopped schedule\n'
     'is never restarted and nothing is retried. The one exception comes before any\n'
     'batch: a first session that only the machine and ledger gates refused (free cores,\n'
     'memory, budget or predicate units at that moment) is looked for again, at growing\n'
     "intervals of the schedule's clock and a bounded number of times, while the\n"
     'parent goes on serially; a late session only changes which later requests are\n'
     "offered to workers, never the parent's order or what it adopts.\n"
     '\n'),
    ('PREFERRED = 0.5      # a batch nobody waits for is started only if it brings this share of the best in sight\n'
     "_FAILED = object()   # a guarded step of the schedule's own raised, and the schedule has stopped\n",
     'PREFERRED = 0.5      # a batch nobody waits for is started only if it brings this share of the best in sight\n'
     'DEFER = 15.0         # seconds before a first session the machine gates refused is looked for again\n'
     'DEFER_MAX = 120.0    # the interval doubles up to this\n'
     'DEFERRALS = 24       # refused first opens before the pass stops looking (about 45 minutes)\n'
     'LATER = object()     # what session() returns when only the machine gates refused: open again later\n'
     "_FAILED = object()   # a guarded step of the schedule's own raised, and the schedule has stopped\n"),
    ('    ``session()`` returns an opened batch session, or None when none could be\n'
     '    opened; it is called once, when the first batch is worth starting.\n'
     '    ``estimate(label)`` returns the (expected, high) seconds of a class, or\n',
     '    ``session()`` returns an opened batch session, or None when none could be\n'
     '    opened; it is called when the first batch is worth starting. It may return\n'
     '    LATER instead when only the machine gates refused: it is then called again\n'
     '    once a deferral interval has passed and a batch is still worth starting.\n'
     '    ``estimate(label)`` returns the (expected, high) seconds of a class, or\n'),
    ('        self._again, self._declined = None, 0\n'
     '        self.totals = dict(batches=0, jobs=0, expected_seconds=0.0, avoided_seconds=0.0, finished=0,\n',
     '        self._again, self._declined = None, 0\n'
     '        self._retry, self._deferrals = None, 0\n'
     '        self.totals = dict(batches=0, jobs=0, expected_seconds=0.0, avoided_seconds=0.0, finished=0,\n'),
    ('        session = self.session\n'
     '        running, held = (0, 0) if session is None else (session.running(), len(session.batches))\n',
     '        session = self.session\n'
     '        if session is None and self._retry is not None and self.clock() < self._retry:\n'
     '            return      # the machine gates refused the first session: nothing can start before the retry\n'
     '        running, held = (0, 0) if session is None else (session.running(), len(session.batches))\n'),
    ('                    return\n'
     '                self.session = session\n',
     '                    return\n'
     '                if session is LATER:\n'
     '                    return self._defer()\n'
     '                self.session = session\n'),
    ('\n'
     '    def _note(self, reason, detail):\n',
     '\n'
     '    def _defer(self):\n'
     '        """Only the machine gates refused the first session: look again later, a bounded number of times."""\n'
     '        self._deferrals += 1\n'
     '        if self._deferrals > DEFERRALS:\n'
     "            return self._stop('session not opened', 'the machine gates refused all %d first opens of this pass'\n"
     '                              % self._deferrals)\n'
     '        self._retry = self.clock()+min(DEFER_MAX, DEFER*2**(self._deferrals-1))\n'
     "        self._note('session deferred', 'the machine gates refused a first session (%d so far); the parent '\n"
     "                   'goes on serially and it is looked for again later' % self._deferrals)\n"
     '        return None\n'
     '\n'
     '    def _note(self, reason, detail):\n'),
    ('        self.closed = True\n'
     '        try:\n',
     '        self.closed = True\n'
     '        if self.session is None and self._deferrals and self.stopped is None:\n'
     '            # Ended while a deferred first open was pending: as before deferral, no session was opened.\n'
     "            self._stop('session not opened', 'the pass ended before a deferred first session opened '\n"
     "                       '(%d machine-gate refusal(s))' % self._deferrals)\n"
     '        try:\n'),
)


def transform(source, *, allow_unreviewed_input=False):
    if 'def _defer(self):' in source:
        raise ValueError('S4 retry already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('integration_parallel_rolling.py input is not the reviewed module; pass allow_unreviewed_input and re-run parity')
    for old, new in EDITS:
        if source.count(old) != 1:
            raise ValueError('S4 anchor must occur exactly once: %r' % old[:60])
        source = source.replace(old, new)
    return source
