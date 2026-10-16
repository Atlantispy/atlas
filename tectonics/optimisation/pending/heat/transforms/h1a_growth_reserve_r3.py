"""H1a r3 (coordinator D-k, 16 Oct 2026): exact accounting fast path in Arithmetic.reserve().

r3 supersedes h1a_growth_reserve_r2.py (never measured; the H1 refuter's r2 re-check is in
T/hs/refute-h1/repro_hostile_r2.py, case 9). r2 read self.slots and self.containers before
the slot allowance, so with an attribute deleted, or with a non-int width such as
reserve(10.5), the exception type or message could differ from the original. r3 keeps the
original's order: the slot allowance first, then containers, then slots, on every route
where the slot allowance can still raise. r1 (h1_growth_reserve.py) is unchanged and is
what q03 measured.

Earlier closures kept from r2 (refuter cases 3a/3b): reserve() reads `R = self.R` first,
as the original does, and the cached envelope is keyed on the identity of R as well.

Source transform of the heat helper private_heat_exact_growth_r1.py, as emitted by
private_heat_bundle.construct_compact_successor(..., live_memory=True). The output keeps the
same file name in the composition's helpers folder.

Why it is worth doing: on the genuine W4 call, reserve() runs about 9.08M times across the
reconstruction workers, costing 103 s cumulative (G/HANDOFF.md section 11). Most calls do not
raise the high-water width. Even so, every call rebuilds RationalShape(peak, peak), runs
native_slot_allowance and native_workspace_allowance (each re-running the installed-GMP
policy check, three gmpy2 calls) and recomputes the same total.

What changes: reserve() remembers the last envelope it computed and checked. It keeps the
exact int objects (peak, slots, containers), the resources module R and the total. When the
current peak, slots, containers and R are those same objects, it reuses the total instead of
recomputing it.

Read order, route by route:
- peak or R differs from the cached key (and always for a non-int peak, which is never
  cached): the original sequence verbatim. That is the slot allowance (which may raise),
  then containers, then slots, then the workspace allowance with slots read again.
- peak and R match the cached key: this peak was already fully computed and checked with
  this R, so its slot allowance cannot raise (D-k; see below). containers and then slots are
  read, in the original's order. If they are the cached objects, the cached total is used.
  Otherwise the slot allowance is computed and the original expression finishes. The only
  difference from the original is that the pure slot allowance runs after the two attribute
  reads, not before them.
- self._envelope is one extra attribute read, and the cache-hit route reads self.slots once
  where the original reads it twice. That is visible only to attribute access with side
  effects; the reviewed Arithmetic has plain instance attributes.

What does not change:
- R is read first, then the cancellation check runs, on every call.
- The lease comparison `total > workspace.lease.count`, and the resize when it holds, still
  run on every call. A lease that anything shrank is still re-grown before the operation.
- Reservations happen in the same calls and the same order, with the same totals.
- peak_bits and operations are updated exactly as before.

Why the guard is exactly as strong:
- The total is a pure function of the VALUES (peak, slots, containers) and of R's functions.
  R is part of the key; the loaded-implementation guard refuses rebinding R's functions
  in-process. (A fault-injection test that patches R's functions on the same module object
  would not see its patch on a cache hit: documented; not reachable in production.)
- The key components are compared by identity and are cached only when peak, slots and
  containers are each an exact `int`. An int is immutable, so the same object means the same
  value and the same type.
- A key is stored only after the full computation has passed every check for exactly those
  values: RationalShape validation, both installed-policy checks, the _count checks, the
  2**27-bit route ceiling and the sys.maxsize overflow check. An exception skips the store.
- Re-running those checks on the same values therefore cannot raise, except for the
  installed-GMP policy, and that reads constants compiled into the gmpy2 binary already
  loaded in this process, which CPython never re-initialises. Skipping it on a cache hit is
  the approved "policy check once per process" (D-k).
- Any change of peak (a wider operand), slots or containers (callers do `arena.slots += 20`
  and `arena.containers += ...`, then reserve(peak_bits)) gives a new object, so the full
  computation runs again.
- The cache lives on the instance (`self._envelope`). The module gains no upper-case
  name, so the loaded-implementation identity records nothing mutable.

Record identity: numbers byte-identical. Only the helper's source digest changes, which the
issuer binds at runtime into the heat result's private_sources. Coordinator D-b allows
digest-only changes, proved by the same-call control.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '94dfc0164c3f8ad583e2c89761e3c75503c456610c55a9d89937f51700119808':
        'private_heat_exact_growth_r1.py emitted by construct_compact_successor (composed-r1/r2, '
        'reviewed-inputs-r2 "compact-successor")',
}

OLD_CLASS = 'class Arithmetic:\n    def __init__('
NEW_CLASS = ('class Arithmetic:\n'
             '    # H1a r3: (peak, slots, containers, total, R) of the last envelope computed and\n'
             '    # checked by reserve(); exact ints only, compared by identity. None: nothing cached.\n'
             '    _envelope = None\n'
             '\n'
             '    def __init__(')

OLD_RESERVE = '''\
    def reserve(self, bits):
        R = self.R
        if self.cancelled is not None and self.cancelled():
            raise CancelledError('Exact scalar growth admission cancelled')
        bits = max(1, bits)
        peak = max(self.peak_bits, bits)
        slot = R.native_slot_allowance(R.RationalShape(peak, peak))
        # Each slot is charged as a full rational even for integer-only rows.
        # All unreduced scalar products, division parts and getter copies have
        # 64 additional slots; the workspace policy separately funds scratch.
        total = self.containers+(self.slots+64)*slot+R.native_workspace_allowance(8*peak, self.slots+64)
        if total > sys.maxsize:
            raise OverflowError('Exact scalar envelope exceeds addressable storage')
        if total > self.workspace.lease.count:
            self.workspace.resize_before_allocation_or_after_drop(total)
        self.peak_bits = peak
'''

NEW_RESERVE = '''\
    def reserve(self, bits):
        R = self.R
        if self.cancelled is not None and self.cancelled():
            raise CancelledError('Exact scalar growth admission cancelled')
        bits = max(1, bits)
        peak = max(self.peak_bits, bits)
        envelope = self._envelope
        if envelope is not None and envelope[0] is peak and envelope[4] is R:
            # This peak was fully computed and checked with this R: its slot allowance cannot
            # raise. containers, then slots, are read in the original's order.
            containers = self.containers
            slots = self.slots
            if envelope[1] is slots and envelope[2] is containers:
                total = envelope[3]
            else:
                slot = R.native_slot_allowance(R.RationalShape(peak, peak))
                total = containers+(slots+64)*slot+R.native_workspace_allowance(8*peak, self.slots+64)
                if total > sys.maxsize:
                    raise OverflowError('Exact scalar envelope exceeds addressable storage')
                self._envelope = ((peak, slots, containers, total, R)
                                  if type(peak) is int and type(slots) is int and type(containers) is int else None)
        else:
            slot = R.native_slot_allowance(R.RationalShape(peak, peak))
            # Each slot is charged as a full rational even for integer-only rows.
            # All unreduced scalar products, division parts and getter copies have
            # 64 additional slots; the workspace policy separately funds scratch.
            containers = self.containers
            slots = self.slots
            total = containers+(slots+64)*slot+R.native_workspace_allowance(8*peak, self.slots+64)
            if total > sys.maxsize:
                raise OverflowError('Exact scalar envelope exceeds addressable storage')
            self._envelope = ((peak, slots, containers, total, R)
                              if type(peak) is int and type(slots) is int and type(containers) is int else None)
        if total > self.workspace.lease.count:
            self.workspace.resize_before_allocation_or_after_drop(total)
        self.peak_bits = peak
'''


def transform(source, *, allow_unreviewed_input=False):
    if '_envelope' in source:
        raise ValueError('H1a reserve transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('exact_growth input is not the reviewed module; pass allow_unreviewed_input and re-run '
                         'the same-call control')
    for anchor, name in ((OLD_CLASS, 'class header'), (OLD_RESERVE, 'reserve body')):
        if source.count(anchor) != 1:
            raise ValueError('H1a %s anchor must occur exactly once' % name)
    return source.replace(OLD_CLASS, NEW_CLASS).replace(OLD_RESERVE, NEW_RESERVE)


if __name__ == '__main__':
    import sys
    from pathlib import Path
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    out = transform(src.read_bytes().decode('utf8'))
    dst.write_bytes(out.encode('utf8'))
    print(sha256(src.read_bytes()).hexdigest(), '->', sha256(out.encode()).hexdigest())
