"""S4 (Small optimisations, backlog 20, 16 Oct 2026): retry a machine-gate-refused first open later.

Source transform of atlas_tectonics/integration_parallel_selection.py, generated from Small optimisations' reviewed
candidate (T/so/s4, INTEGRATION.md 13:43) by Geometry's make_s4_transforms.py: the hunks of
base 7d4d4037... -> candidate a0d90167..., applied in order, reproduce the candidate byte
for byte. A first worker session that only the machine and ledger gates refused (free cores,
memory, budget or predicate units at that moment) is looked for again at 15 s doubling to
120 s, at most 24 times, while the parent goes on serially; psutil missing still stops at once.
Records and the parent's adoption order cannot change (a late session is an ordinary first
session opened later in the pass). Owner review: G/reviews/s4-retry-review.md.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '7d4d4037ae35a320575ca874ea54ea48ad4e0ab956ee6b69c44ece53dce87a9e':
        'gg/workers6-r6 (composed-r1 + workers_six + workers_six_rolling_interfaces)',
}
CANDIDATE_SHA256 = 'a0d90167b44425171ec7ff8359997dc820ffac4c3863d324605aa796a6927aff'   # T/so/s4/integration_parallel_selection.py

EDITS = (
    ("OWN_WORK = 0.001    # seconds of a schedule's own work inside a contact's timing that spoil it as an observation\n"
     "_SCREENED = (('decided', 'an exact shortcut decides it'), ('refused', 'the exact screen was refused'),\n",
     "OWN_WORK = 0.001    # seconds of a schedule's own work inside a contact's timing that spoil it as an observation\n"
     "PERMANENT_GATES = frozenset({'psutil'})    # machine-gate refusals that no later look can pass: the open stops\n"
     "_SCREENED = (('decided', 'an exact shortcut decides it'), ('refused', 'the exact screen was refused'),\n"),
    ('\n'
     '    def _open(self):\n'
     '        """The schedule\'s first batch is worth starting: machine gates, then the funded session."""\n'
     '        refusal = self._machine()\n'
     '        if refusal is not None:\n'
     "            self.notes.append('%s: %s' % refusal)\n"
     '            return None\n'
     '        parent, policy = self.parent, self.policy\n',
     '\n'
     '    def _refused(self, refusal):\n'
     '        """A machine-gate refusal of the first open: RB.LATER to look again, or None if it can never pass.\n'
     '\n'
     '        Repeated refusals by the same gate keep one note (the latest), so the\n'
     "        bounded report keeps the pass's earlier notes.\n"
     '        """\n'
     "        note = '%s: %s' % refusal\n"
     "        if self.notes and self.notes[-1].startswith(refusal[0]+': '):\n"
     '            self.notes[-1] = note\n'
     '        else:\n'
     '            self.notes.append(note)\n'
     '        return None if refusal[0] in PERMANENT_GATES else RB.LATER\n'
     '\n'
     '    def _open(self):\n'
     '        """The schedule\'s first batch is worth starting: machine gates, then the funded session.\n'
     '\n'
     '        Machine gates are momentary hints (nothing is reserved), so their refusal\n'
     '        defers the open (RB.LATER); a refused session or its funding still stops.\n'
     '        """\n'
     '        refusal = self._machine()\n'
     '        if refusal is not None:\n'
     '            return self._refused(refusal)\n'
     '        parent, policy = self.parent, self.policy\n'),
)


def transform(source, *, allow_unreviewed_input=False):
    if 'PERMANENT_GATES = ' in source:
        raise ValueError('S4 retry already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('integration_parallel_selection.py input is not the reviewed module; pass allow_unreviewed_input and re-run parity')
    for old, new in EDITS:
        if source.count(old) != 1:
            raise ValueError('S4 anchor must occur exactly once: %r' % old[:60])
        source = source.replace(old, new)
    return source
