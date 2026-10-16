"""H1c (part of H1, coordinator D-k): inline exact growth accounting in Arithmetic.q()/rational().

Source transform of private_heat_exact_growth_r1.py AFTER H1a (h1_growth_reserve.py), so the
reviewed input is H1a's output 9aaf5b5e. The output keeps the same file name.

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
- Denominators: an mpq denominator is >= 1, so its bit_length is >= 1. An integer operand
  has denominator width 1.
- Every bit_length() is an exact int; checked for gmpy2 2.3.2 mpz and Python int.
- So RationalShape's _count checks and the zero-denominator check always pass. In
  operation_growth, divide's `c == 0` cannot hold (s >= 1), and divisor_is_nonzero is
  always True. The original route therefore never raises inside those constructions.
  The inline route has nothing to raise there either.

What stays identical:
- Exception order: a TypeError for a bad left operand, then for a bad right operand
  (same messages), then the ValueError for an unknown operation (same message), then
  whatever reserve() raises, then the arithmetic (for example ZeroDivisionError).
- Operand getters are read in the same order (numerator, then denominator).
  d.bit_count() is skipped: the original computes it only for the unused `dyadic` field,
  and it is pure.
- operation is compared with the same expressions, in the same order.
- reserve() receives an int of the same value. Then operations += 1, then the same
  arithmetic expression.

Route guard: the inline route runs only when the instance's class still has the base
_integer and _shape (true for Arithmetic and for private_heat_rank_resources_r1._Arithmetic).
A subclass overriding either keeps the original code verbatim. The widths replicate
private_heat_gmp_resources_r1 at 5ada7b86: operation_growth, RationalShape, _product_bits.
A later revision of that module must keep those definitions, or this transform must be
reviewed again.

Record identity: numbers byte-identical; digest-only (D-b), proved by the same-call control.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '9aaf5b5e1e1ef361b1cdbf33ece956046cbe5a9a40e990b71265a4ddeae7220f':
        'private_heat_exact_growth_r1.py after H1a (h1_growth_reserve.py) on the reviewed 94dfc016',
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
        cls = type(self)
        if cls._shape is not _BASE_SHAPE or cls._integer is not _BASE_INTEGER:
            shape = self._shape(value)
            self.reserve(max(shape.numerator, shape.denominator))
            self.operations += 1
            return self.G.mpq(value)
        # H1c: max(shape.numerator, shape.denominator) of _shape, without building the shape.
        G = self.G
        kind = type(value)
        if kind is int or kind is G.mpz:
            self.reserve(max(1, value.bit_length()))
        elif kind is G.mpq:
            self.reserve(max(1, value.numerator.bit_length(), value.denominator.bit_length()))
        else:
            raise TypeError('Already owned exact GMP rational required')
        self.operations += 1
        return G.mpq(value)
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
        cls = type(self)
        if cls._shape is not _BASE_SHAPE or cls._integer is not _BASE_INTEGER:
            R = self.R
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
            if kind is int or kind is G.mpz:
                p, r = max(1, a.bit_length()), 1
            elif kind is G.mpq:
                p, r = max(1, a.numerator.bit_length()), a.denominator.bit_length()
            else:
                raise TypeError('Already owned exact GMP rational required')
            kind = type(b)
            if kind is int or kind is G.mpz:
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
'''

TAIL = "        return a/b\n"
NEW_TAIL = (TAIL + '\n\n'
            '# H1c: the base methods whose results q() and rational() inline; a subclass that\n'
            '# overrides either keeps the original route.\n'
            '_BASE_INTEGER, _BASE_SHAPE = Arithmetic._integer, Arithmetic._shape\n')


def transform(source, *, allow_unreviewed_input=False):
    if '_BASE_SHAPE' in source:
        raise ValueError('H1c inline transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError("exact_growth input is not H1a's reviewed output; pass allow_unreviewed_input and re-run "
                         'the same-call control')
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
