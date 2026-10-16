"""Transfer a completed private exact result to its own accounted lifetime.

All input objects are covered by the old owner while inspected. The new charge
is admitted before the old work is released. This is intentionally recursive
without deduplication: aliases cost more, never less. Retention uses complete
actual object counts plus the reviewed native rational-slot policy; traversal
scratch is released and is not multiplied by the number of retained faces. No numeric copy or JSON
conversion is made. Use after the producing numerical frame has returned and
before exposing borrowed references; callbacks retaining temporaries forbid it.

R3 charges each retained object at the blocks it occupies (counted blocks r1)
where that module supports the runtime. A rational that exists reports the
limbs allocated for it, recycled capacity included, so the recycled-slot
allowance that R2 added to every one of them is not needed. On any other
runtime R2's figures are used unchanged.

R4 counts by counted blocks r2. That module also refuses an interpreter with a
debug or replaced allocator and one that is tracing. R2's figure alone is
below the blocks of an object that is not an exact number, so there each
object is charged the larger of R2's figure for it and its blocks as those
allocators make them (that module's ``refused_bytes``): never less than R2
held. It counts a block that may have shrunk from the C heap at the C-heap
figure, and each transfer adds that module's allowance for every record
instance it meets, up to what all the early instances of one class can hold.
"""
from dataclasses import fields
from decimal import Decimal
from fractions import Fraction
import sys

import private_heat_certification_resources_r1 as I
import private_heat_counted_blocks_r2 as COUNT
import private_heat_decimal_sparse_core_r1 as P


MAX_DEPTH = 64


def transfer(owner, *, budget, cancelled=None, category='heat-retained-functional-row', record_types=()):
    from atlas_tectonics.exact_arithmetic import library
    import private_heat_gmp_resources_r1 as R
    G = library()
    if G is None:
        raise RuntimeError('Selected GMP backend required')
    # One recursion frame + one iterator/locals generation per level, plus
    # source-local closure/scalar/owner metadata. This is transient, not a
    # retained per-row256KiB allowance.
    traversal_bytes = I.D.CONTAINER_UNIT*(2*(MAX_DEPTH+1)+32)
    work = R.OwnedWorkspace(budget, traversal_bytes, category=category, cancelled=cancelled)
    work.__enter__()
    try:
        total = 0
        counted, classes = COUNT.supported(G), {}
        # Where the count is refused: what the allocators in use add to a block, asked once for the
        # walk, and the kinds of object for which more of R2's figure follows further down.
        padding, later = (None, ()) if counted else (COUNT.padding(), (G.mpq, Fraction, *record_types))
        plain = (dict, list, tuple, G.mpq, Fraction, str, int, bool, float, Decimal, type(None))
        def visit(value, depth=0):
            nonlocal total
            I.check(cancelled)
            if depth > MAX_DEPTH:
                raise ValueError('Unexpected retained result nesting')
            if not counted:
                # R2's figure for the object is added as it was, here and further down. Once it is
                # complete the object is charged the larger of it and its blocks as they are made.
                base, total = total, I.size(total+sys.getsizeof(value))
                need = (COUNT.refused_bytes(value, G, padding) if type(value) in plain
                        else COUNT.refused_block(sys.getsizeof(value), padding))
                if type(value) not in later:
                    total = I.size(max(total, base+need))
            elif type(value) in plain:
                # The object exists: its own blocks, as it reports them.
                total = I.size(total+COUNT.own_bytes(value, G))
            elif type(value) in record_types:
                total = I.size(total+COUNT.block(sys.getsizeof(value)))
            if type(value) in (dict, list, tuple):
                if type(value) is dict:
                    for key, item in value.items():
                        visit(key, depth+1)
                        visit(item, depth+1)
                else:
                    for item in value:
                        visit(item, depth+1)
            elif type(value) in record_types:
                # An early instance of a class holds more than its dictionary reports.
                total = I.size(total+(COUNT.own_bytes(value.__dict__, G)+COUNT.record_instance(type(value), classes)
                                      if counted else sys.getsizeof(value.__dict__)))
                if not counted:
                    need += COUNT.refused_bytes(value.__dict__, G, padding)+COUNT.record_instance(type(value), classes)
                    total = I.size(max(total, base+need))
                for field in fields(value):
                    visit(field.name, depth+1)
                    visit(getattr(value, field.name), depth+1)
            elif counted and type(value) is G.mpq:
                pass
            elif counted and type(value) is Fraction:
                total = I.size(total+COUNT.own_bytes(value.numerator, G)+COUNT.own_bytes(value.denominator, G))
            elif type(value) in (G.mpq, Fraction):
                total = I.size(total+R.native_slot_allowance(R.RationalShape(
                    max(1, value.numerator.bit_length()), value.denominator.bit_length())))
                if type(value) is Fraction:
                    total = I.size(total+sys.getsizeof(value.numerator)+sys.getsizeof(value.denominator))
                    need += (COUNT.refused_bytes(value.numerator, G, padding)
                             +COUNT.refused_bytes(value.denominator, G, padding))
                total = I.size(max(total, base+need))        # only a refused count comes this way
            elif type(value) not in (str, int, bool, float, Decimal, type(None)):
                raise TypeError('Unsupported retained result object '+type(value).__name__)
        value = owner.value
        visit(value)
        # Count the actual owner/workspace/lease/ExitStack containers; budget
        # nodes and callable code already belong to the caller/runtime. Two
        # units prospectively cover the new OwnedSolve object and its dict.
        structures = (work, work.__dict__, work.stack, work.stack.__dict__,
            work.stack._exit_callbacks, work.lease, work.lease.__dict__,
            work.lease.budgets, work.lease.charged, work.lease.category)
        owner_bytes = 2*I.D.CONTAINER_UNIT+sum(map(sys.getsizeof, structures))
        for entry in work.stack._exit_callbacks:
            owner_bytes += sys.getsizeof(entry)+sys.getsizeof(entry[1])
        for entry in work.lease.charged:
            owner_bytes += sys.getsizeof(entry)
        retained = I.size(total+owner_bytes)
        # Preserve the walking lease until this local traversal frame drops.
        # Objects in value remain funded by both old and new owners at transfer.
        work.resize_before_allocation_or_after_drop(max(traversal_bytes, retained))
        # The complete producing frame is gone. The only escaped graph is
        # value, now independently funded BEFORE releasing its old owner.
        owner.close()
        # Recursive visit frames are gone; only this fixed-depth frame remains.
        # structures is a tiny pointer-only inspection tuple, not result data.
        structures = None
        work.resize_before_allocation_or_after_drop(retained)
        return P.OwnedSolve(value, work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


