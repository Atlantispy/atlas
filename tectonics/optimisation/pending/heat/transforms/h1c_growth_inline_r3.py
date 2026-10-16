"""H1c r3 (part of H1, coordinator D-k): inline exact growth accounting in Arithmetic.q()/rational().

r3 supersedes h1c_growth_inline_r2.py (never measured). It applies after H1a r3
(h1a_growth_reserve_r3.py), so the reviewed input is H1a r3's output 750d24ab. The H1
refuter's r2 re-check (T/hs/refute-h1) found:
- REFUTING: r2 kept its mutable route state in UPPER-CASE module lists. The
  loaded-implementation guard (private_heat_loaded_identity_r1) records every upper-case module
  value of a captured type (lists included) as an identity constant. So the first inlined
  rational() changed the identity, and the issuer's next _verify_implementation() refused
  (repro_identity_drift.py). r3 keeps all mutable state under lower-case names
  (`_inline_verified`, `_inline_checked`). The only new upper-case names are immutable: the
  reviewed digest string, and the two base functions (functions are not captured types).
- Case 7: a replaced arena.G (a non-gmpy2 namespace) still took the inline route. r3 binds G
  as well: both q() and rational() inline only when self.G is the `G` (gmpy2) of the verified
  gmp_resources_r1 module.
- Case 8: r2's guard read self._integer up front. The original reads it only for an integer
  operand, so a subclass whose _integer raises gave a different result for mpq operands. r3
  reads self._integer only where the original would, at an int/mpz operand.
- Weaker concern: r2 cached a strong reference to every R object it was shown. r3 caches only
  the module registered as sys.modules['private_heat_gmp_resources_r1']; anything else is
  answered "no" without caching.
- Case 6 stays as an accepted residual: a type whose metaclass __eq__ answers differently on
  repeated calls. The original evaluates `type(v) in (int, G.mpz)` twice for an integer
  operand, r3 once. Python int and gmpy2 types use `type` as their metaclass, so no reviewed
  operand can do this.

Route guard (every condition must hold, otherwise the original body runs verbatim):
- self._shape is the base Arithmetic._shape bound to this instance (a MethodType whose
  __func__ is the base function and whose __self__ is self). The original reads self._shape
  first in q() (after R in rational()), so a raising or overridden _shape behaves the same.
- rational(): R (read first, as in the original) is the loaded private_heat_gmp_resources_r1
  whose file hashes to 5ada7b86 (hashed once per module object per process).
  q(): the same module is looked up in sys.modules; q() never reads self.R, as before.
- self.G is that verified module's `G`.
- For each int/mpz operand: self._integer is the base Arithmetic._integer bound to this
  instance. If not, the whole call takes the original body (operand getters are pure on int
  and gmpy2 values, so reading them again changes nothing).
The check hashes the module's file, not its loaded code; in production the issuer's
loaded-implementation guard refuses a module loaded from other code. The one file read happens
inside the first q()/rational() call of the process.

Why it is worth doing: on the genuine W4 call, rational() runs 4.15M times and q() 2.33M
times across the reconstruction workers (G/evidence/heat-w4-p4w). Every rational() call:
- builds two I.Shape objects;
- builds two RationalShape objects, whose __post_init__ validation runs _count each time;
- runs R.operation_growth, which builds a third RationalShape and a Growth object;
- concatenates tuples, only to take one max() for the reserve() width.
In the base profile, RationalShape.__post_init__ alone runs 46.8M times.

What changes: q() and rational() compute the same reserve width directly from the operand
bit lengths, without building those objects.
- q: an int or mpz operand reserves max(1, bit_length). An mpq operand reserves
  max(1, numerator bits, denominator bits). That is max(shape.numerator, shape.denominator)
  of the original _shape.
- rational: with p, r the left numerator/denominator widths and s, t the right ones, all of
  them >= 1 (see below), R.operation_growth's widths are:
    add/subtract: ad = p+t, cb = s+r, n = max(ad, cb)+1, den = r+t;
                  reserved max(ad, cb, n, den, n, den) = max(n, den), because n > ad, cb
    multiply:     n = p+s, den = r+t, reserved max(n, den)
    divide:       n = p+t, den = r+s, reserved max(n, den)
  _product_bits(x, y) is x+y whenever both are nonzero, and the carry bit
  `1 if ad and cb else 0` is 1.

Why the widths are always >= 1 (so the original validations cannot fail):
- Numerators: the original takes max(1, bit_length).
- Denominators: a gmpy2 mpq denominator is >= 1, so its bit_length is >= 1 (this is why G
  must be the verified gmpy2). An integer operand has denominator width 1.
- Every bit_length() is an exact int; checked for gmpy2 2.3.2 mpz and Python int.
- So RationalShape's _count checks and the zero-denominator check always pass. In
  operation_growth, divide's `c == 0` cannot hold (s >= 1), and divisor_is_nonzero is
  always True. The original route therefore never raises inside those constructions.

What stays identical:
- Exception order: an AttributeError for a missing R (rational), whatever reading _shape
  raises, a TypeError for a bad left operand, then for a bad right operand (same messages),
  then the ValueError for an unknown operation (same message), then whatever reserve()
  raises, then the arithmetic (for example ZeroDivisionError).
- Operand getters are read in the same order (numerator, then denominator).
  d.bit_count() is skipped: the original computes it only for the unused `dyadic` field,
  and it is pure.
- operation is compared with the same expressions, in the same order.
- reserve() receives an int of the same value. Then operations += 1, then the same
  arithmetic expression.
- Read counts of self.G and self._shape are lower on the inline route (one read each where
  the original has two or three). That is visible only to attribute access with side effects.

Record identity: numbers byte-identical; digest-only (D-b), proved by the same-call control.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '750d24ab47c524db0c2a3c3113506df1edcb85fb177205d0db29bd79c713a669':
        'private_heat_exact_growth_r1.py after H1a r3 (h1a_growth_reserve_r3.py) on the reviewed 94dfc016',
}

OLD_Q = '''\
    def q(self, value):
        shape = self._shape(value)
        self.reserve(max(shape.numerator, shape.denominator))
        self.operations += 1
        return self.G.mpq(value)
'''

NEW_Q = '''\
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
'''

OLD_RATIONAL = '''\
    def rational(self, operation, a, b):
        R = self.R
        left, right = self._shape(a), self._shape(b)
        growth = R.operation_growth(operation,
            R.RationalShape(left.numerator, left.denominator),
            R.RationalShape(right.numerator, right.denominator), divisor_is_nonzero=True)
        self.reserve(max(growth.expression_integer_bits+(growth.result.numerator_bits, growth.result.denominator_bits)))
        self.operations += 1
'''

NEW_RATIONAL = '''\
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
'''

TAIL = "        return a/b\n"
NEW_TAIL = TAIL + '''

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
_inline_checked = []   # (module, (module, G) or None); only sys.modules' own entry is cached


def _inline_pair(resources):
    """(module, module.G) for the loaded gmp_resources_r1 whose file has the reviewed content.

    Anything else gives None, so the caller runs its original body. Only the object registered
    as sys.modules['private_heat_gmp_resources_r1'] is hashed and cached, once per module
    object per process; any doubt (missing or unreadable file, other content, no G) is None.
    """
    for module, pair in _inline_checked:
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
    _inline_checked.append((resources, pair))
    if pair is not None:
        _inline_verified[0] = pair
    return pair
'''


def transform(source, *, allow_unreviewed_input=False):
    if '_BASE_SHAPE' in source:
        raise ValueError('H1c inline transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError("exact_growth input is not H1a r3's reviewed output; pass allow_unreviewed_input and "
                         're-run the same-call control')
    for anchor, name in ((OLD_Q, 'q'), (OLD_RATIONAL, 'rational')):
        if source.count(anchor) != 1:
            raise ValueError('H1c %s anchor must occur exactly once' % name)
    if not source.endswith(TAIL) or source.count(TAIL) != 1:
        raise ValueError('H1c end-of-module anchor must be the final line, exactly once')
    out = source.replace(OLD_Q, NEW_Q).replace(OLD_RATIONAL, NEW_RATIONAL)
    return out[:-len(TAIL)] + NEW_TAIL


if __name__ == '__main__':
    import sys
    from pathlib import Path
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    out = transform(src.read_bytes().decode('utf8'))
    dst.write_bytes(out.encode('utf8'))
    print(sha256(src.read_bytes()).hexdigest(), '->', sha256(out.encode()).hexdigest())
