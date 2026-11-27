"""Getter-safe fixed arithmetic with exact canonical-component equality.

GMP mpq values from the supported constructors and arithmetic are canonical:
coprime numerator/denominator, positive denominator and unique zero0/1.
Two such values are equal exactly when both integer components are equal.
No rational cross products are computed by this override. Getter copies are
funded before extraction, and the existing64 scalar slots and128*bits native
policy cover the four simultaneous mpz parts. No tolerance or ambient MPFR
precision participates; ordering comparisons retain their previous policy.

Inspect one part at a time under the getter envelope and drop each copy
before admitting the arithmetic workspace for the measured widths.

The proof is the GMP canonical-rational contract; no projection decoder,
saved-output acceptance or backend selection is imported here.
"""
from hashlib import sha256; import atlas_tectonics._identity as _atlas_identity
from pathlib import Path
import sys

from atlas_tectonics._private.integration.heat import correction_owned as C

_SOURCES = dict(C._SOURCES)
_SOURCES[_atlas_identity.relkey(__file__)] = sha256(Path(__file__).read_bytes()).hexdigest()


def getter_envelope(resources, reported_bytes):
    """Installed-backend copy/work policy; no rational arithmetic occurs here.

    Each sequential mpz copy is at most the original mpq's combined allocated
    payload. Headers and recycled blocks are separately covered by two native
    slots. Retain the original 128*bits policy for the getters' combined width,
    without incorrectly multiplying it by the arithmetic eight-expression
    envelope. The original mpq remains owned by the caller throughout.
    """
    if type(reported_bytes) is not int or reported_bytes <= 0:
        raise ValueError('A positive current GMP allocation is required')
    bits = 8*reported_bytes+64
    return (resources.native_workspace_allowance(bits, 2)
            + 2*resources.native_slot_allowance(resources.RationalShape(bits, 1)))


def _parts(value, resources):
    # Separate statements and explicit drops ensure at most one large getter
    # copy survives at once. This frame is gone before the lease shrinks.
    part = value.numerator
    numerator = max(1, part.bit_length())
    del part
    part = value.denominator
    denominator = part.bit_length()
    del part
    return resources.RationalShape(numerator, denominator)


class Arithmetic(C._Arithmetic):
    """Same fixed operations; part getters have their own transient owner."""
    def __init__(self, workspace, gmp, resources, n, f, initial_bits, check, *, extra_fixed_bytes=0):
        if initial_bits != 1:
            raise ValueError('Getter-safe entry begins with one-bit arithmetic capacity')
        self.getter_operations = self.getter_peak_bytes = self.inspected_peak_bits = 0
        super().__init__(workspace, gmp, resources, n, f, 1, check,
                         extra_fixed_bytes=extra_fixed_bytes)

    def shape(self, value):
        if type(value) is int:
            return self.R.RationalShape(max(1, value.bit_length()), 1)
        if type(value) is not self.G.mpq:
            raise TypeError('Owned exact GMP correction inputs required')
        self.check()
        before = self.workspace.lease.count
        extra = getter_envelope(self.R, sys.getsizeof(value))
        # Do not use finally to take release credit: an escaping getter frame
        # could still own a part. The ordinary failure-owner contract applies.
        self.workspace.resize_before_allocation_or_after_drop(before+extra)
        shape = _parts(value, self.R)
        self.getter_operations += 1
        self.getter_peak_bytes = max(self.getter_peak_bytes, extra)
        self.inspected_peak_bits = max(self.inspected_peak_bits,
                                       shape.numerator_bits, shape.denominator_bits)
        self.workspace.resize_before_allocation_or_after_drop(before)
        return shape

    def equal(self, left, right):
        if any(type(value) not in (int, self.G.mpq) for value in (left, right)):
            raise TypeError('Already owned canonical mpq or exact int equality operands required')
        # shape owns its transient getters and drops them before return.
        # Renew a full scalar envelope for the actual component widths before
        # the following four getter copies can coexist. Do not add opposite
        # denominator widths: no such products are executed here.
        a, b = self.shape(left), self.shape(right)
        parts = (a.numerator_bits, a.denominator_bits,
                 b.numerator_bits, b.denominator_bits)
        required_part_bits = max(parts)
        self.reserve(required_part_bits)
        self.equality_evidence = dict(part_bits=parts, required_part_bits=required_part_bits,
            unused_cross_product_bits=max(a.numerator_bits+b.denominator_bits,
                                          b.numerator_bits+a.denominator_bits))
        ln, ld = (left, 1) if type(left) is int else (left.numerator, left.denominator)
        rn, rd = (right, 1) if type(right) is int else (right.numerator, right.denominator)
        self.operations += 1
        return ln == rn and ld == rd
