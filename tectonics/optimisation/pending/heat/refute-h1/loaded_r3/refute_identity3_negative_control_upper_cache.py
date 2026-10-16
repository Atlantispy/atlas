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
    # H1a r3: (peak, slots, containers, total, R) of the last envelope computed and
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
        width = None
        m = self._shape
        if type(m) is _MethodType and m.__func__ is _BASE_SHAPE and m.__self__ is self:
            G = self.G
            v = _inline_verified[0]
            if G is not v[1]:
                v = _inline_pair(sys.modules.get('private_heat_gmp_resources_r1'))
            if v is not None and G is v[1]:
                # H1c: max(shape.numerator, shape.denominator) of _shape, without building the shape.
                kind = type(value)
                if kind in (int, G.mpz):
                    n = self._integer
                    if type(n) is _MethodType and n.__func__ is _BASE_INTEGER and n.__self__ is self:
                        width = max(1, value.bit_length())
                elif kind is G.mpq:
                    width = max(1, value.numerator.bit_length(), value.denominator.bit_length())
                else:
                    raise TypeError('Already owned exact GMP rational required')
        if width is None:
            shape = self._shape(value)
            width = max(shape.numerator, shape.denominator)
        self.reserve(width)
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
        width = None
        m = self._shape
        if type(m) is _MethodType and m.__func__ is _BASE_SHAPE and m.__self__ is self:
            v = _inline_verified[0]
            if R is not v[0]:
                v = _inline_pair(R)
            G = self.G
            if v is not None and G is v[1]:
                # H1c: R.operation_growth's reserved width from the operand widths (all >= 1).
                p = s = None
                kind = type(a)
                if kind in (int, G.mpz):
                    n = self._integer
                    if type(n) is _MethodType and n.__func__ is _BASE_INTEGER and n.__self__ is self:
                        p, r = max(1, a.bit_length()), 1
                elif kind is G.mpq:
                    p, r = max(1, a.numerator.bit_length()), a.denominator.bit_length()
                else:
                    raise TypeError('Already owned exact GMP rational required')
                if p is not None:
                    kind = type(b)
                    if kind in (int, G.mpz):
                        n = self._integer
                        if type(n) is _MethodType and n.__func__ is _BASE_INTEGER and n.__self__ is self:
                            s, t = max(1, b.bit_length()), 1
                    elif kind is G.mpq:
                        s, t = max(1, b.numerator.bit_length()), b.denominator.bit_length()
                    else:
                        raise TypeError('Already owned exact GMP rational required')
                if s is not None:
                    if operation in ('add', 'subtract'):
                        width = max(max(p+t, s+r)+1, r+t)
                    elif operation == 'multiply':
                        width = max(p+s, r+t)
                    elif operation == 'divide':
                        width = max(p+t, r+s)
                    else:
                        raise ValueError('operation must be add, subtract, multiply or divide')
        if width is None:
            left, right = self._shape(a), self._shape(b)
            growth = R.operation_growth(operation,
                R.RationalShape(left.numerator, left.denominator),
                R.RationalShape(right.numerator, right.denominator), divisor_is_nonzero=True)
            width = max(growth.expression_integer_bits+(growth.result.numerator_bits, growth.result.denominator_bits))
        self.reserve(width)
        self.operations += 1
        if operation == 'add':
            return a+b
        if operation == 'subtract':
            return a-b
        if operation == 'multiply':
            return a*b
        return a/b


# H1c r3: the base methods whose results q() and rational() inline. The inline route runs only
# when self._shape (and, for an integer operand, self._integer) is the base function bound to
# the instance.
_BASE_INTEGER, _BASE_SHAPE = Arithmetic._integer, Arithmetic._shape
from hashlib import sha256 as _sha256  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
from types import MethodType as _MethodType  # noqa: E402

# H1c r3: the inline route runs only for gmp_resources_r1 at exactly this content, and its G.
_INLINE_RESOURCES_SHA256 = '5ada7b86bc189393d74b20aad1f5eb312b0398f25dd74710f6209dfb94f2edca'
# Mutable route state is lower case on purpose: the loaded-implementation identity records
# upper-case module values as constants, and this state changes on first use.
# _inline_verified[0] is (module, module.G) of the last verified module; private placeholders
# until then, so it never matches a real R or G.
_inline_verified = [(object(), object())]
_INLINE_CHECKED = []   # (module, (module, G) or None); only sys.modules' own entry is cached


def _inline_pair(resources):
    """(module, module.G) for the loaded gmp_resources_r1 whose file has the reviewed content.

    Anything else gives None, so the caller runs its original body. Only the object registered
    as sys.modules['private_heat_gmp_resources_r1'] is hashed and cached, once per module
    object per process; any doubt (missing or unreadable file, other content, no G) is None.
    """
    for module, pair in _INLINE_CHECKED:
        if module is resources:
            if pair is not None:
                _inline_verified[0] = pair
            return pair
    loaded = sys.modules.get('private_heat_gmp_resources_r1')
    if resources is None or resources is not loaded:
        return None
    try:
        pair = ((resources, resources.G)
                if _sha256(_Path(resources.__file__).read_bytes()).hexdigest() == _INLINE_RESOURCES_SHA256
                else None)
    except (AttributeError, TypeError, ValueError, OSError):
        pair = None
    _INLINE_CHECKED.append((resources, pair))
    if pair is not None:
        _inline_verified[0] = pair
    return pair
