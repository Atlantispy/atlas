"""H5a: reuse functionals ``_prepare`` within ONE verified ``advance`` call (S6 memo, T/so/s6/S6-MEMO.md).

functionals kernel r5 -> r6, forward kernel r13 -> r14. Groundwork only: to be folded into the next forward
successor (Steps 8-9 / H4 / item 9), so the forward pin cascade (checkpoint_consumer_r10, joined_consumer_r6,
restored_binding_r10, restored_binding_ram_context_r1, the two r9 copies, composition.json) is paid once.
This module only rewrites text; it does not repin anything.

What changes:
- functionals r6 adds ``prepare_shared`` and ``SharedPrepared``, and gives ``reconstruct`` a ``shared=None``
  argument ``prepared_shared=None``. With it given and matching, ``reconstruct`` uses the shared prepared geometry instead of
  calling ``_prepare``. It matches only when all three hold:
    - ``payload`` IS the same object;
    - each boundary partition has the same type, length and members;
    - the conductivity has the same type and value.
  Otherwise ``reconstruct`` prepares afresh, exactly as in r5. A closed SharedPrepared raises. Without
  it, ``reconstruct`` is r5's code path.
- ``_prepare`` takes a ``category`` keyword, defaulting to r5's 'heat-functional-geometry'. The shared copy
  is booked as 'heat-functional-geometry-shared'.
- forward r14 makes one SharedPrepared just before the first reconstruct call and owns it on its own stack
  (``retain``, lower-case local). It passes the SharedPrepared to every reconstruct call of that advance,
  then closes it where the payload is no longer consumed, before the HIGH solve. There is no module-level
  cache: a module-level cache would pin the 0.94 GB payload, and the loaded-identity guard records
  upper-case module state.
Why it is exact:
- ``_prepare`` reads only the payload, the two boundary partitions and k. All three forward calls pass the
  same objects.
- Nothing after ``_prepare`` writes to the prepared value: the only stores are inside ``_prepare``;
  functionals_parallel_r1 serialises it per call.
- Rows that share objects with it stay valid after it closes: ``OwnedSolve.close`` drops a reference and
  clears nothing. Retention already counts the shared objects once for each use.
Expected effect:
- Two ``_prepare`` runs and their 2.17 GB transient bookings disappear per IV1 interval.
- About 66.6 MB is held from the first reconstruct call to the HIGH solve (about 270 MB at 4x). The LOW
  peak is unchanged.
Proof still owed (not run here): W4 same-call control D-b, refinement rows and census equal apart from
``seconds``, and one refuter. Small optimisations measures T_prepare first; under about 2 s, H5a is dropped.
"""
from hashlib import sha256

FUNCTIONALS_INPUT_SHA256 = frozenset({'85991687f0a6ba57c333cb1f1fc5904e2c21a5ab19f1f26c68a3c6b06ec577ca'})
FORWARD_INPUT_SHA256 = frozenset({'5c9ad7371e30f29ad56865cbad109c5bfce9fc0c5dab8fc0a015fa52e512826d'})

_PREPARE_BLOCK = '''\
        prepared_owner = work.stack.enter_context(_prepare(payload, boundary_point_faces,
            boundary_power_faces, conductivity, budget=budget, cancelled=cancelled))
        prepared = prepared_owner.value
        if COUNT.supported(G):
            # _prepare has returned: its arena, scratch and local maps are gone,
            # and what it built exists. Hold that, not the worst case for it.
            settled = _prepared_bytes(prepared, cancelled)
            if settled is not None and settled < prepared_owner._workspace.lease.count:
                prepared_owner._workspace.resize_before_allocation_or_after_drop(settled)
'''

_SHARED_DEFS = '''\


def _shared_key(boundary_point_faces, boundary_power_faces, conductivity):
    """What ``_prepare`` reads besides the payload object, or None when it would refuse them."""
    kinds = (tuple, list, set, frozenset)
    if type(boundary_point_faces) not in kinds or type(boundary_power_faces) not in kinds:
        return None
    if type(conductivity) not in (int, Fraction, G.mpq):
        return None
    try:
        return (type(boundary_point_faces), len(boundary_point_faces), frozenset(boundary_point_faces),
                type(boundary_power_faces), len(boundary_power_faces), frozenset(boundary_power_faces),
                type(conductivity), conductivity)
    except TypeError:
        return None


class SharedPrepared:
    """One verified advance call's prepared geometry, reused by that call's reconstructions (R6).

The caller owns it on its own stack and closes it once the payload is no longer
consumed. It matches only the same payload object with equal boundary partitions
and the same exact conductivity; anything else is prepared afresh. Never keep one
at module level: it would pin the payload across calls.
"""
    __slots__ = ('_owner', '_payload', '_key', 'uses')

    def __init__(self, owner, payload, key):
        self._owner, self._payload, self._key, self.uses = owner, payload, key, 0

    def matches(self, payload, boundary_point_faces, boundary_power_faces, conductivity):
        if self._owner is None:
            raise RuntimeError('Shared prepared geometry is closed')
        key = _shared_key(boundary_point_faces, boundary_power_faces, conductivity)
        return key is not None and payload is self._payload and key == self._key

    @property
    def value(self):
        if self._owner is None:
            raise RuntimeError('Shared prepared geometry is closed')
        return self._owner.value

    def close(self):
        owner, self._owner, self._payload = self._owner, None, None
        if owner is not None:
            owner.close()

    def __enter__(self):
        self.value
        return self

    def __exit__(self, kind, error, traceback):
        owner, self._owner, self._payload = self._owner, None, None
        if owner is None:
            return False
        return owner.__exit__(kind, error, traceback)


def prepare_shared(payload, boundary_point_faces, boundary_power_faces, conductivity, *, budget, cancelled=None):
    """Prepare once, settle the reservation as ``reconstruct`` does, and return a SharedPrepared."""
    F.K._require_gmp()
    I.check(cancelled)
    key = _shared_key(boundary_point_faces, boundary_power_faces, conductivity)
    owner = _prepare(payload, boundary_point_faces, boundary_power_faces, conductivity, budget=budget,
                     cancelled=cancelled, category='heat-functional-geometry-shared')
    try:
        if key is None:
            raise AssertionError('Prepared geometry accepted inputs the reuse key cannot represent')
        if COUNT.supported(G):
            settled = _prepared_bytes(owner.value, cancelled)
            if settled is not None and settled < owner._workspace.lease.count:
                owner._workspace.resize_before_allocation_or_after_drop(settled)
        return SharedPrepared(owner, payload, key)
    except BaseException:
        owner.__exit__(*sys.exc_info())
        raise
'''

R6_NOTE = '''\

R6 (H5a) reuses one call's prepared geometry: ``prepare_shared`` returns a
``SharedPrepared`` that a caller owns and passes to each ``reconstruct`` of one
verified advance call. It is used only for the same payload object, equal
boundary partitions and the same exact conductivity; otherwise ``_prepare`` runs
as in R5. Rows, their order, every census field but ``seconds`` and every
reservation formula are R5's; the shared copy is booked once under its own
category instead of once per call.
'''


def _apply(text, pairs):
    for old, new in pairs:
        if text.count(old) != 1:
            raise ValueError('anchor not found exactly once: %r' % old[:80])
        text = text.replace(old, new)
    return text


def functionals(source, *, allow_unreviewed_input=False):
    """functionals kernel r5 text -> r6 text."""
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in FUNCTIONALS_INPUT_SHA256:
        raise ValueError('unreviewed functionals input')
    indented = ''.join(('    '+line if line.strip() else line) for line in _PREPARE_BLOCK.splitlines(True))
    return _apply(source, [
        ("prepared geometry) is listed in that module.\n\"\"\"\n",
         "prepared geometry) is listed in that module.\n"+R6_NOTE+"\"\"\"\n"),
        ("def _prepare(payload, boundary_point_faces, boundary_power_faces, conductivity, *, budget, cancelled):\n",
         "def _prepare(payload, boundary_point_faces, boundary_power_faces, conductivity, *, budget, cancelled,\n"
         "             category='heat-functional-geometry'):\n"),
        ("    work = R.OwnedWorkspace(budget, metadata, category='heat-functional-geometry', cancelled=cancelled)\n",
         "    work = R.OwnedWorkspace(budget, metadata, category=category, cancelled=cancelled)\n"),
        ("PREPARED_OWNER = 8192\n", "PREPARED_OWNER = 8192\n"+_SHARED_DEFS),
        ("                certification_precisions=PRECISIONS):\n    \"\"\"Owner.value is (rows, evidence)",
         "                certification_precisions=PRECISIONS, prepared_shared=None):\n    \"\"\"Owner.value is (rows, evidence)"),
        (_PREPARE_BLOCK,
         "        if prepared_shared is not None and prepared_shared.matches(payload, boundary_point_faces,\n"
         "                boundary_power_faces, conductivity):\n"
         "            # R6: this advance call's prepared geometry, settled once; the caller owns it.\n"
         "            prepared = prepared_shared.value\n"
         "            prepared_shared.uses += 1\n"
         "        else:\n"+indented),
    ])


def forward(source, *, allow_unreviewed_input=False):
    """forward kernel r13 text -> r14 text (imports functionals r6)."""
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in FORWARD_INPUT_SHA256:
        raise ValueError('unreviewed forward input')
    return _apply(source, [
        ("import private_heat_functionals_kernel_r5 as FUNCTIONS\n",
         "import private_heat_functionals_kernel_r6 as FUNCTIONS\n"),
        ("            stage('certify-full-polygon-functionals')\n"
         "            row_owner = complete(FUNCTIONS.reconstruct(payload,\n"
         "                boundary_point_faces=temperatures, boundary_power_faces=powers,\n"
         "                conductivity=k, budget=budget, cancelled=check))\n",
         "            stage('certify-full-polygon-functionals')\n"
         "            # R14 (H5a): one prepared geometry for every reconstruction of this\n"
         "            # call, on this frame's stack; closed below once the payload is no\n"
         "            # longer consumed. It is used only for this payload, these sets and k.\n"
         "            prepared_shared = retain(FUNCTIONS.prepare_shared(payload, temperatures, powers, k,\n"
         "                budget=budget, cancelled=check))\n"
         "            row_owner = complete(FUNCTIONS.reconstruct(payload,\n"
         "                boundary_point_faces=temperatures, boundary_power_faces=powers,\n"
         "                conductivity=k, budget=budget, cancelled=check, prepared_shared=prepared_shared))\n"),
        ("                            selected_faces=faces, certification_precisions=offered))\n",
         "                            selected_faces=faces, certification_precisions=offered,\n"
         "                            prepared_shared=prepared_shared))\n"),
        ("            payload = None\n            startup = retain(LIFE.compact(startup,",
         "            prepared_shared.close()  # R14: no reconstruction follows; idempotent on the stack\n"
         "            prepared_shared = None\n"
         "            payload = None\n            startup = retain(LIFE.compact(startup,"),
    ])


if __name__ == '__main__':
    import sys
    from pathlib import Path
    helpers = Path(sys.argv[1])        # a helpers folder holding the two reviewed inputs; new files are added
    for name, fn, out in (('private_heat_functionals_kernel_r5.py', functionals, 'private_heat_functionals_kernel_r6.py'),
                          ('private_heat_forward_kernel_r13.py', forward, 'private_heat_forward_kernel_r14.py')):
        if (helpers/out).exists():
            raise SystemExit('%s exists; refusing to overwrite' % out)
        before = (helpers/name).read_bytes()
        after = fn(before.decode('utf8')).encode('utf8')
        (helpers/out).write_bytes(after)
        print(name, sha256(before).hexdigest(), '->', out, sha256(after).hexdigest())
