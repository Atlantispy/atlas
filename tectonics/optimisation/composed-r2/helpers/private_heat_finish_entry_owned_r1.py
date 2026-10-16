"""Getter-only prospective admission before actual-width exact arithmetic.

The installed GMP convention, its operand ceiling, 128*bits workspace and
64 arithmetic slots are unchanged. A caller-owned mpq's reported allocation
bounds its combined limb payload; it is NOT a per-part arithmetic width.
Inspect one part at a time under an additional copy/native-getter envelope,
drop that copy, then return only two small bit counts. The fixed arithmetic
owner subsequently admits the unchanged expression growth from those counts.
No native origin, whole-method admission or allocator/RSS theorem is claimed.
"""
from hashlib import sha256
from pathlib import Path
import sys

import private_heat_correction_owned_r1 as C

_SOURCES = dict(C._SOURCES)
_SOURCES[str(Path(__file__).resolve())] = sha256(Path(__file__).read_bytes()).hexdigest()


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
