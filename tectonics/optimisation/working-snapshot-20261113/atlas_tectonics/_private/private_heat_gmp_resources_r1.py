"""Private heat sizing and owned admission, not a complete heat memory budget.

Integer bit/limb and ASCII payload bounds below are mathematical bounds. GMP
``getsizeof`` reports retained allocation, including recycled capacity, NOT OS
RSS. The native workspace and recycled-slot allowances follow the installed
geometry backend's accounting convention; they are not allocator proofs.
No cache setting is changed, and no arithmetic callback is silently admitted.

A heat caller must inventory every live generation, container and simultaneous
codec buffer, reserve BEFORE allocating, and drop/transfer results BEFORE a
successful lease exits. Repeated references are charged repeatedly by default.
Failed frames retain the lease just as the native geometry/transport paths do.
GMP scratch, allocator arenas and abrupt native exits remain the supervisor's
concern. The per-expression bounds do not by themselves budget an entire solve.
"""
from concurrent.futures import CancelledError
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
import sys

import gmpy2 as G

HERE = Path(__file__).resolve().parent
# Runtime package selection belongs to the explicit source fence.
from atlas_tectonics.integration_spatial_transport import _preserve_workspace
from atlas_tectonics.resources import WorkBudget, _ResizableLease


def _count(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f'{name} must be a nonnegative integer')
    return value


def _integer(value):
    if type(value) not in (int, G.mpz):
        raise TypeError('expected an already owned exact int or mpz')
    return value


@dataclass(frozen=True)
class RationalShape:
    numerator_bits: int
    denominator_bits: int
    possibly_negative: bool = True

    def __post_init__(self):
        _count(self.numerator_bits, 'numerator_bits')
        if _count(self.denominator_bits, 'denominator_bits') == 0:
            raise ValueError('a positive denominator requires at least one bit')
        if type(self.possibly_negative) is not bool:
            raise TypeError('possibly_negative must be bool')

    @property
    def bits(self):
        return self.numerator_bits+self.denominator_bits


def shape_from_parts(numerator, denominator):
    """Inspect already owned parts; mpq getters may themselves allocate copies.

    Callers extracting mpq.numerator/denominator must already hold their native
    workspace lease. No absolute-value big integer or float is constructed here.
    Canonical reduction is unnecessary for a conservative size bound.
    """
    n, d = _integer(numerator), _integer(denominator)
    if d <= 0:
        raise ValueError('denominator must be positive')
    return RationalShape(n.bit_length(), d.bit_length(), n < 0)


def limb_payload_bytes(bits, *, limb_bits=64):
    """Bytes needed for this value's minimal limbs, excluding all headers/cache."""
    _count(bits, 'bits')
    if type(limb_bits) is not int or limb_bits <= 0 or limb_bits % 8:
        raise ValueError('limb_bits must be a positive byte-aligned integer')
    return ((bits+limb_bits-1)//limb_bits)*(limb_bits//8)


def rational_payload_bytes(shape):
    return limb_payload_bytes(shape.numerator_bits)+limb_payload_bytes(shape.denominator_bits)


def _product_bits(a, b):
    return 0 if a == 0 or b == 0 else a+b


@dataclass(frozen=True)
class Growth:
    result: RationalShape
    expression_integer_bits: tuple
    operand_bits: int

    @property
    def expression_limb_bytes(self):
        """All unreduced formula intermediates at once, NOT internal GMP scratch."""
        return sum(limb_payload_bytes(b) for b in self.expression_integer_bits)

    @property
    def total_expression_bits(self):
        return self.operand_bits+sum(self.expression_integer_bits)+self.result.bits


def operation_growth(operation, left, right, *, divisor_is_nonzero=False):
    """Advance exact growth for a/b +/- c/d, products, or nonzero divisors.

    A product of nonzero n- and m-bit integers has <=n+m bits; a sum has
    <=max(n,m)+1. Reduction cannot increase either part. All formula values,
    plus a separate reduced result, are counted without assuming slot reuse.
    These statements do NOT bound the implementation's gcd/multiply scratch.
    Shapes can be upper bounds, so a positive bit bound alone does not establish
    a nonzero divisor. Division requires the caller's separate nonzero check.
    """
    a, b = left.numerator_bits, left.denominator_bits
    c, d = right.numerator_bits, right.denominator_bits
    if operation in ('add', 'subtract'):
        ad, cb = _product_bits(a, d), _product_bits(c, b)
        n = max(ad, cb)+(1 if ad and cb else 0)
        denominator = b+d
        widths = (ad, cb, n, denominator)
    elif operation == 'multiply':
        n, denominator = _product_bits(a, c), b+d
        widths = (n, denominator)
    elif operation == 'divide':
        if c == 0:
            raise ZeroDivisionError('zero divisor refused before allocation')
        if divisor_is_nonzero is not True:
            raise ValueError('division requires a separately checked nonzero divisor')
        n, denominator = _product_bits(a, d), b+c
        widths = (n, denominator)
    else:
        raise ValueError('operation must be add, subtract, multiply or divide')
    return Growth(RationalShape(n, denominator), widths, left.bits+right.bits)


def reported_gmp_bytes(values):
    """Current object allocation; aliases deliberately counted per occurrence.

    Excludes the iterable/container, values outside it, module cache and heap
    fragmentation. A retained snapshot must be settled inside an ALREADY
    admitted transient envelope, not used as retroactive allocation permission.
    """
    total = 0
    for value in values:
        if type(value) not in (G.mpq, G.mpz):
            raise TypeError('reported GMP allocation requires mpq/mpz values')
        total += sys.getsizeof(value)
    return total


def _installed_policy():
    if (G.version(), G.mp_version(), G.mp_limbsize()) != ('2.3.2', 'GMP 6.3.0', 64):
        raise RuntimeError('GMP accounting policy requires the reviewed installed backend')


def native_slot_allowance(shape):
    """Geometry's measured recycled-block allowance, NOT a proved capacity cap.

    Existing oversized mpq allocations must be charged at their reported size.
    An expression may retain larger intermediates: use the corresponding growth
    shape rather than its reduced output shape, and settle in the admitted scope.
    """
    _installed_policy()
    limbs = sum(max(64, (b+63)//64+2) for b in
                (shape.numerator_bits, shape.denominator_bits))
    return 160+8*limbs


def native_workspace_allowance(bits, count, *, pairs=0):
    """Same explicit accounted envelope as integration_exact_gmp._work.

    Reusing the formula is not proof that a new heat algorithm has inventoried
    all live operands. No OS RSS or arbitrary-operation scratch guarantee.
    """
    _installed_policy()
    _count(bits, 'bits')
    _count(count, 'count')
    _count(pairs, 'pairs')
    if bits > 1 << 27:
        raise ValueError('exact operands exceed the existing GMP route ceiling')
    return 65536+128*bits+256*count+256*pairs


def hex_pair_char_bound(shape):
    """Canonical compact JSON [\"signedhex\",\"positivehex\"] character bound."""
    n = max(1, (shape.numerator_bits+3)//4)
    d = max(1, (shape.denominator_bits+3)//4)
    return 7+n+d+int(shape.possibly_negative and shape.numerator_bits != 0)


def hex_buffers_allowance(shape, *, ascii_copies, utf8_copies):
    """Full simultaneous flat string/bytes copies, including object headers.

    CPython compact ASCII str and immutable bytes only. This does not include
    the pair/list, separate component strings, JSON encoder chunks, compressor,
    bytearray over-allocation or file I/O buffers: inventory those separately.
    """
    _count(ascii_copies, 'ascii_copies')
    _count(utf8_copies, 'utf8_copies')
    if sys.implementation.name != 'cpython':
        raise RuntimeError('flat codec object accounting is CPython-specific')
    length = hex_pair_char_bound(shape)
    return ascii_copies*(sys.getsizeof('')+length)+utf8_copies*(sys.getsizeof(b'')+length)


def encode_parts(numerator, denominator):
    """Exact codec for already admitted canonical parts; no implicit lease.

    gcd, component strings, concatenation and returned storage must all be
    inventoried by the caller. Refuse noncanonical input rather than reduce it
    invisibly. No decimal-size limit, float conversion or loss of 1/3 occurs.
    """
    n, d = _integer(numerator), _integer(denominator)
    if d <= 0 or G.gcd(n, d) != 1:
        raise ValueError('codec requires a reduced numerator and positive denominator')
    return '["'+format(n, 'x')+'","'+format(d, 'x')+'"]'


class OwnedWorkspace:
    """A resizable accounting lease with native escaping-frame ownership.

    Not a general arithmetic wrapper. The caller supplies a complete inventory
    and owns result lifetime: successful exit is legal only after all charged
    objects are dropped or transferred to a separately charged result owner.
    On failure/cancellation, error AND separately retained traceback keep the
    charge until their owner dies. Never shrink while objects remain live.
    """
    def __init__(self, budget, count, *, category='heat-exact-private', cancelled=None):
        if not isinstance(budget, WorkBudget):
            raise TypeError('budget must be a native WorkBudget')
        _count(count, 'count')
        self.stack = ExitStack()
        self.lease = _ResizableLease(budget, category=category)
        self.count, self.cancelled = count, cancelled
        self.entered, self.finished = False, False

    def checkpoint(self):
        if self.cancelled is not None and self.cancelled():
            raise CancelledError('private heat resource scope cancelled')

    def __enter__(self):
        if self.entered or self.finished:
            raise RuntimeError('workspace cannot be entered twice')
        self.checkpoint()
        try:
            self.stack.enter_context(self.lease)
            self.lease.resize(self.count)
            self.checkpoint()
        except BaseException:
            # Body has not run, so there can be no admitted body allocation.
            self.stack.close()
            self.finished = True
            raise
        self.entered = True
        return self

    def resize_before_allocation_or_after_drop(self, count):
        if not self.entered or self.finished:
            raise RuntimeError('workspace is not active')
        self.checkpoint()
        self.lease.resize(count)

    def __exit__(self, kind, error, traceback):
        self.finished = True
        if error is None:
            self.stack.close()
            return False
        # The explicit raise retains this owner-bearing frame if a caller keeps
        # only the traceback. A generator context manager can trim that frame.
        self._failure_owner = _preserve_workspace(error, self.stack)
        raise error.with_traceback(traceback)
