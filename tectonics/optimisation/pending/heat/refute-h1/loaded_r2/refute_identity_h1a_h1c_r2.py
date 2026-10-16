"""Adaptive owned GMP expression growth, not an allocator/RSS guarantee.

The caller inventories a complete live scalar/container count for one reviewed
algorithm. Actual operand bit lengths bound each unreduced operation before it
runs. A high-water reservation covers every slot at the largest reached width,
plus native workspace and scalar intermediates. No old-generation release is
claimed. This is not a generic whole-solve admission or arbitrary callback API.
"""
from concurrent.futures import CancelledError
import sys

import private_heat_interval_inventory_r1 as I


class Arithmetic:
    # H1a r2: (peak, slots, containers, total, R) of the last envelope computed and
    # checked by reserve(); exact ints only, compared by identity. None: nothing cached.
    _envelope = None

    def __init__(self, workspace, gmp, *, scalar_slots, container_bytes, initial_bits, cancelled=None):
        import private_heat_gmp_resources_r1 as R
        if any(type(v) is not int or v <= 0 for v in (scalar_slots, container_bytes, initial_bits)):
            raise ValueError('Positive reviewed slot/container/initial-width inventory required')
        self.workspace, self.G, self.R = workspace, gmp, R
        self.slots, self.containers, self.cancelled = scalar_slots, container_bytes, cancelled
        self.peak_bits = 1
        self.operations = 0
        self.reserve(initial_bits)

    def reserve(self, bits):
        R = self.R
        if self.cancelled is not None and self.cancelled():
            raise CancelledError('Exact scalar growth admission cancelled')
        bits = max(1, bits)
        peak = max(self.peak_bits, bits)
        slots, containers, envelope = self.slots, self.containers, self._envelope
        if (envelope is not None and envelope[0] is peak and envelope[1] is slots
                and envelope[2] is containers and envelope[4] is R):
            # The same immutable ints and module whose envelope was fully computed and checked.
            total = envelope[3]
        else:
            slot = R.native_slot_allowance(R.RationalShape(peak, peak))
            # Each slot is charged as a full rational even for integer-only rows.
            # All unreduced scalar products, division parts and getter copies have
            # 64 additional slots; the workspace policy separately funds scratch.
            total = containers+(slots+64)*slot+R.native_workspace_allowance(8*peak, slots+64)
            if total > sys.maxsize:
                raise OverflowError('Exact scalar envelope exceeds addressable storage')
            self._envelope = ((peak, slots, containers, total, R)
                              if type(peak) is int and type(slots) is int and type(containers) is int else None)
        if total > self.workspace.lease.count:
            self.workspace.resize_before_allocation_or_after_drop(total)
        self.peak_bits = peak

    def _integer(self, value):
        if type(value) not in (int, self.G.mpz):
            raise TypeError('Already owned exact integer required')
        return max(1, value.bit_length())

    def _shape(self, value):
        if type(value) in (int, self.G.mpz):
            return I.Shape(self._integer(value), 1, True)
        if type(value) is not self.G.mpq:
            raise TypeError('Already owned exact GMP rational required')
        # Getter copies are already covered by the currently live high-water
        # scalar slots, before inspecting these parts for the NEXT operation.
        n, d = value.numerator, value.denominator
        return I.Shape(max(1, n.bit_length()), d.bit_length(), d.bit_count() == 1)

    def q(self, value):
        m, n = self._shape, self._integer
        if (type(m) is not _MethodType or m.__func__ is not _BASE_SHAPE or m.__self__ is not self
                or type(n) is not _MethodType or n.__func__ is not _BASE_INTEGER or n.__self__ is not self):
            shape = self._shape(value)
            self.reserve(max(shape.numerator, shape.denominator))
            self.operations += 1
            return self.G.mpq(value)
        # H1c: max(shape.numerator, shape.denominator) of _shape, without building the shape.
        G = self.G
        kind = type(value)
        if kind in (int, G.mpz):
            self.reserve(max(1, value.bit_length()))
        elif kind is G.mpq:
            self.reserve(max(1, value.numerator.bit_length(), value.denominator.bit_length()))
        else:
            raise TypeError('Already owned exact GMP rational required')
        self.operations += 1
        return self.G.mpq(value)

    def lcm(self, a, b):
        self.reserve(self._integer(a)+self._integer(b))
        self.operations += 1
        return self.G.lcm(a, b)

    def gcd(self, a, b):
        self.reserve(max(self._integer(a), self._integer(b)))
        self.operations += 1
        return self.G.gcd(a, b)

    def imul(self, a, b):
        self.reserve(self._integer(a)+self._integer(b))
        self.operations += 1
        return a*b

    def isub(self, a, b):
        self.reserve(max(self._integer(a), self._integer(b))+1)
        self.operations += 1
        return a-b

    def idiv(self, a, b):
        self.reserve(max(self._integer(a), self._integer(b)))
        self.operations += 1
        return a//b

    def divmod(self, a, b):
        self.reserve(max(self._integer(a), self._integer(b)))
        self.operations += 1
        return divmod(a, b)

    def rational(self, operation, a, b):
        R = self.R
        m, n = self._shape, self._integer
        if ((R is not _INLINE_RESOURCES[0] and not _inline_resources(R))
                or type(m) is not _MethodType or m.__func__ is not _BASE_SHAPE or m.__self__ is not self
                or type(n) is not _MethodType or n.__func__ is not _BASE_INTEGER or n.__self__ is not self):
            left, right = self._shape(a), self._shape(b)
            growth = R.operation_growth(operation,
                R.RationalShape(left.numerator, left.denominator),
                R.RationalShape(right.numerator, right.denominator), divisor_is_nonzero=True)
            self.reserve(max(growth.expression_integer_bits+(growth.result.numerator_bits,
                                                             growth.result.denominator_bits)))
        else:
            # H1c: R.operation_growth's reserved width from the operand widths (all >= 1).
            G = self.G
            kind = type(a)
            if kind in (int, G.mpz):
                p, r = max(1, a.bit_length()), 1
            elif kind is G.mpq:
                p, r = max(1, a.numerator.bit_length()), a.denominator.bit_length()
            else:
                raise TypeError('Already owned exact GMP rational required')
            kind = type(b)
            if kind in (int, G.mpz):
                s, t = max(1, b.bit_length()), 1
            elif kind is G.mpq:
                s, t = max(1, b.numerator.bit_length()), b.denominator.bit_length()
            else:
                raise TypeError('Already owned exact GMP rational required')
            if operation in ('add', 'subtract'):
                width = max(max(p+t, s+r)+1, r+t)
            elif operation == 'multiply':
                width = max(p+s, r+t)
            elif operation == 'divide':
                width = max(p+t, r+s)
            else:
                raise ValueError('operation must be add, subtract, multiply or divide')
            self.reserve(width)
        self.operations += 1
        if operation == 'add':
            return a+b
        if operation == 'subtract':
            return a-b
        if operation == 'multiply':
            return a*b
        return a/b


# H1c r2: the base methods whose results q() and rational() inline. The inline route runs only
# when self._shape and self._integer are these functions bound to the instance.
_BASE_INTEGER, _BASE_SHAPE = Arithmetic._integer, Arithmetic._shape
from hashlib import sha256 as _sha256  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
from types import MethodType as _MethodType  # noqa: E402

# H1c r2: rational() inlines R.operation_growth only for gmp_resources_r1 at exactly this content.
_INLINE_RESOURCES_SHA256 = '5ada7b86bc189393d74b20aad1f5eb312b0398f25dd74710f6209dfb94f2edca'
_INLINE_RESOURCES = [object()]   # a private placeholder until a module is verified; never None
_INLINE_CHECKED = []


def _inline_resources(resources):
    """True only for the loaded gmp_resources_r1 whose file has the reviewed content.

    The file is hashed once per module object per process. Any doubt (another object, missing or
    unreadable file, other content) gives False, so rational() runs its original body.
    """
    for module, verdict in _INLINE_CHECKED:
        if module is resources:
            return verdict
    verdict = False
    if resources is sys.modules.get('private_heat_gmp_resources_r1'):
        try:
            verdict = _sha256(_Path(resources.__file__).read_bytes()).hexdigest() == _INLINE_RESOURCES_SHA256
        except (AttributeError, TypeError, ValueError, OSError):
            verdict = False
    _INLINE_CHECKED.append((resources, verdict))
    if verdict:
        _INLINE_RESOURCES[0] = resources
    return verdict
