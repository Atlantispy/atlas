"""L1 r4: inline exact growth accounting in RationalGrowth.op()/slot().

Status: approved for measurement (coordinator, 16 Oct) on conditions; r2 adds the content binding
asked for by the file owner (Runner pipeline and final integration), which also integrates it.
r3 closes the L1 refuter's findings (T/hs/refute-l1): 'no inline' is a private sentinel, so
resources=None can no longer match it; slot() reads value and self.resources in exactly the
original order and number.
r4 (after the H1 refuter's r2 re-check found it in H1c): the per-process verification cache is a
lower-case module list. The loaded-implementation identity (private_heat_loaded_identity_r1)
records every UPPER-CASE module value of a captured type, lists included, as a constant; an
upper-case cache filled on first use would change the identity and make the issuer's next
_verify_implementation() refuse. The new upper-case names (_FRACTION_ZERO_SIZE, the digest
string, the _NO_INLINE object) never change after import. r4 also returns _NO_INLINE for
resources=None without caching it, and keeps r3b's guard (`or R is _NO_INLINE`) for the
sentinel itself passed in as resources.

Source transform of private_heat_low_ledger_inventory_r1.py (reviewed input 42054fb2). The output
keeps the same file name. The module belongs to the Steps 8-9 heat chain, so L1 needs the
coordinator's agreement and the owner's integration.

Why it is worth doing: on the genuine W4 call (G/evidence/heat-w4-p4w, 525.7 s worker self
time), RationalGrowth.op runs 7.73M times for 109.3 s cumulative, and slot 2.03M times for
23.2 s. Each op() call:
- builds two R.RationalShape objects; __post_init__ runs _count twice plus a bool check;
- calls R.operation_growth, which builds a third RationalShape, a widths tuple and a Growth;
- reads Growth.total_expression_bits, a property that sums the tuple and reads .bits three times.
Each slot() call builds a Fraction(0) only to measure it, defines a lambda, builds a
RationalShape and calls R.native_slot_allowance.

What changes: op() and slot() compute the same integers directly when self.resources is the
reviewed gmp module. RationalGrowth.__init__ sets self._inline = _inline_resources(resources):
the module object only if it is sys.modules['private_heat_gmp_resources_r1'] AND its file's
SHA-256 is 5ada7b86 (hashed once per module object per process); otherwise the private
sentinel _NO_INLINE, which no resources value can be. op()/slot()
inline only when `self.resources is self._inline` and that is not the sentinel itself; a class default `_inline = _NO_INLINE` covers
subclasses that skip __init__, and a later reassignment of self.resources also falls back.
- op: the same operand validation as RationalShape.__post_init__, with the same exceptions,
  messages and order: left numerator, left denominator, then the right ones. Then the same
  operation dispatch as operation_growth, using its expressions literally (_product_bits as
  `0 if x == 0 or y == 0 else x+y`), the same ZeroDivisionError for a zero divisor width, and
  the same ValueError for an unknown operation. total = (a+b)+(c+d) + sum(widths) +
  (numerator+denominator); that is Growth.total_expression_bits. Integer addition is exact
  and associative, so the grouping does not matter. The result RationalShape and Growth
  constructions cannot fail: numerator >= 0, denominator >= 2. The returned shape is built by
  the original tail; only `growth.result.*_bits` became the identical local ints.
- slot: reads value.numerator, value.denominator, self.resources, self.resources,
  value.numerator, value.denominator in the original order and number. Python's part uses the
  same py_int formula (defined once, not per call) and a Fraction(0) size measured once per
  process (a fixed __slots__ instance size; D-k). When both re-read widths are exact
  non-negative ints with a denominator width >= 1, so RationalShape cannot refuse, it calls
  R._installed_policy() and then evaluates the native_slot_allowance formula literally (that
  pure function and the RationalShape constructor are the only calls skipped). Any other input
  calls R.native_slot_allowance(RationalShape(...)) as the original does.
- The original op/slot bodies are kept verbatim for any other resources object, for a module
  whose file content differs (a later revision such as H1b), and when the file cannot be read.

Kept identical: the cancellation check first; the attribute read order; the expression_bits
update; every returned Shape; every exception type and message; slot's byte count. The
polygon_moment_inventory_r1 subclass (_Growth) calls super().op and self.slot, so it takes the
inline route unchanged.

Dependencies: the inline formulas replicate private_heat_gmp_resources_r1 at 5ada7b86:
RationalShape.__post_init__, _count, _product_bits, operation_growth, Growth.total_expression_bits
and native_slot_allowance. The content binding makes a later revision of that module (H1b, say)
fall back to the original bodies automatically: L1 can lose speed there, never diverge.
The check hashes the module's FILE, not its loaded code: a module loaded from other code under
a file with the reviewed content (custom loader, stale .pyc, reload after the check) would still
inline. In production the issuer's loaded-implementation guard refuses exactly that.

Pin cascade (pin_graph.py): certification_resources_r1, finish_inventory_r1,
geometry_inventory_r1 pin this file. geometry_inventory_r3 pins geometry_inventory_r1 and
finish_inventory_r2 pins finish_inventory_r1: 5 pin rewrites, by repin_cascade() below.
certification_resources_r1 is also re-pinned by H2; apply L1's repin after H2's.

Record identity: numbers byte-identical; digest-only (D-b), to be proved by the same-call control.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '42054fb2b67ed4237901389962e23e3c1f93ffbdacfd17645ee1127efe999307':
        'private_heat_low_ledger_inventory_r1.py as emitted by construct_compact_successor (reviewed-inputs-r2)',
}

OLD_OP = '''\
    def op(self, operation, left, right, *, divisor_power_two=False):
        _check(self.cancel)
        R = self.resources
        growth = R.operation_growth(operation,
            R.RationalShape(left.numerator, left.denominator),
            R.RationalShape(right.numerator, right.denominator), divisor_is_nonzero=True)
        self.expression_bits = max(self.expression_bits, growth.total_expression_bits)
        if operation in ('add', 'subtract'):
            return I.add_shape(left, right)
        if operation == 'multiply':
            return I.multiply_shape(left, right)
        if left.dyadic and divisor_power_two:
            # right is an ACTUAL positive power of two, not a numerator upper bound.
            exponent = left.denominator-1+right.numerator-right.denominator
            return I.Shape(left.numerator+max(0, -exponent), max(0, exponent)+1, True)
        return I.Shape(growth.result.numerator_bits, growth.result.denominator_bits, False)
'''

NEW_OP = '''\
    def op(self, operation, left, right, *, divisor_power_two=False):
        _check(self.cancel)
        R = self.resources
        if R is not self._inline or R is _NO_INLINE:
            growth = R.operation_growth(operation,
                R.RationalShape(left.numerator, left.denominator),
                R.RationalShape(right.numerator, right.denominator), divisor_is_nonzero=True)
            total = growth.total_expression_bits
            numerator, denominator = growth.result.numerator_bits, growth.result.denominator_bits
        else:
            # L1: R.RationalShape validation and R.operation_growth, written out (gmp_resources_r1 5ada7b86).
            a, b = left.numerator, left.denominator
            if type(a) is not int or a < 0:
                raise ValueError('numerator_bits must be a nonnegative integer')
            if type(b) is not int or b < 0:
                raise ValueError('denominator_bits must be a nonnegative integer')
            if b == 0:
                raise ValueError('a positive denominator requires at least one bit')
            c, d = right.numerator, right.denominator
            if type(c) is not int or c < 0:
                raise ValueError('numerator_bits must be a nonnegative integer')
            if type(d) is not int or d < 0:
                raise ValueError('denominator_bits must be a nonnegative integer')
            if d == 0:
                raise ValueError('a positive denominator requires at least one bit')
            if operation in ('add', 'subtract'):
                ad = 0 if a == 0 or d == 0 else a+d
                cb = 0 if c == 0 or b == 0 else c+b
                numerator = max(ad, cb)+(1 if ad and cb else 0)
                denominator = b+d
                widths = ad+cb+numerator+denominator
            elif operation == 'multiply':
                numerator, denominator = (0 if a == 0 or c == 0 else a+c), b+d
                widths = numerator+denominator
            elif operation == 'divide':
                if c == 0:
                    raise ZeroDivisionError('zero divisor refused before allocation')
                numerator, denominator = (0 if a == 0 or d == 0 else a+d), b+c
                widths = numerator+denominator
            else:
                raise ValueError('operation must be add, subtract, multiply or divide')
            total = (a+b)+(c+d)+widths+(numerator+denominator)
        self.expression_bits = max(self.expression_bits, total)
        if operation in ('add', 'subtract'):
            return I.add_shape(left, right)
        if operation == 'multiply':
            return I.multiply_shape(left, right)
        if left.dyadic and divisor_power_two:
            # right is an ACTUAL positive power of two, not a numerator upper bound.
            exponent = left.denominator-1+right.numerator-right.denominator
            return I.Shape(left.numerator+max(0, -exponent), max(0, exponent)+1, True)
        return I.Shape(numerator, denominator, False)
'''

OLD_INIT = '''\
    def __init__(self, gmp, resources, cancel):
        self.gmp, self.resources, self.cancel = gmp, resources, cancel
        self.expression_bits = 1
'''

NEW_INIT = '''\
    # L1: the reviewed resources module this object may inline, or _NO_INLINE (original route).
    _inline = _NO_INLINE

    def __init__(self, gmp, resources, cancel):
        self.gmp, self.resources, self.cancel = gmp, resources, cancel
        self.expression_bits = 1
        self._inline = _inline_resources(resources)
'''

OLD_SLOT = '''\
    def slot(self, value):
        # All possible Fraction and mpq generations charged, not alias-deduced.
        py_int = lambda bits: sys.getsizeof(0)+sys.int_info.sizeof_digit*((bits+sys.int_info.bits_per_digit-1)//sys.int_info.bits_per_digit)
        python = sys.getsizeof(Fraction(0))+py_int(value.numerator)+py_int(value.denominator)
        native = self.resources.native_slot_allowance(
            self.resources.RationalShape(value.numerator, value.denominator))
        return _size(python+native)
'''

NEW_SLOT = '''\
    def slot(self, value):
        # All possible Fraction and mpq generations charged, not alias-deduced.
        # L1: the same reads of value and self.resources, in the same order and number, as the
        # original; Fraction(0)'s size is a process constant and py_int is defined once.
        python = _FRACTION_ZERO_SIZE+_py_int(value.numerator)+_py_int(value.denominator)
        R = self.resources
        if R is not self._inline or R is _NO_INLINE:
            native = R.native_slot_allowance(self.resources.RationalShape(value.numerator, value.denominator))
            return _size(python+native)
        S = self.resources
        n, d = value.numerator, value.denominator
        if S is R and type(n) is int and type(d) is int and n >= 0 and d >= 1:
            # RationalShape(n, d) cannot refuse these widths. The policy check still runs on
            # every call; then native_slot_allowance's formula, literally.
            R._installed_policy()
            native = 160+8*(max(64, (n+63)//64+2)+max(64, (d+63)//64+2))
        else:
            native = R.native_slot_allowance(S.RationalShape(n, d))
        return _size(python+native)
'''

ANCHOR_CONST = "PUBLIC_BINARY64 = I.Shape(2098, 1075, True)\n"
NEW_CONST = ANCHOR_CONST + '''\
# L1: a Fraction's fixed __slots__ instance size, which slot() used to measure on every call.
_FRACTION_ZERO_SIZE = sys.getsizeof(Fraction(0))
# L1: op()/slot() inline formulas copied from private_heat_gmp_resources_r1 at exactly this content.
_INLINE_RESOURCES_SHA256 = '5ada7b86bc189393d74b20aad1f5eb312b0398f25dd74710f6209dfb94f2edca'
# Lower case on purpose: the loaded-implementation identity records upper-case module values as
# constants, and this cache is filled on first use. Only sys.modules' own entry is cached.
_inline_checked = []
# L1 r3: the 'do not inline' marker. A private object, so no resources value (None included)
# can ever be identical to it.
_NO_INLINE = object()


def _py_int(bits):
    # L1: slot()'s per-call lambda, unchanged, defined once.
    return sys.getsizeof(0)+sys.int_info.sizeof_digit*((bits+sys.int_info.bits_per_digit-1)//sys.int_info.bits_per_digit)


def _inline_resources(resources):
    """resources if it is the loaded gmp_resources_r1 with the reviewed file content, else _NO_INLINE.

    The file is hashed once per module object per process. Any doubt (another object, missing or
    unreadable file, other content) returns _NO_INLINE, so op()/slot() run their original bodies: L1
    can only lose speed, never diverge from a later gmp_resources revision.
    """
    loaded = sys.modules.get('private_heat_gmp_resources_r1')
    if resources is None or resources is not loaded:
        return _NO_INLINE
    for module, verdict in _inline_checked:
        if module is resources:
            return verdict
    try:
        same = sha256(Path(resources.__file__).read_bytes()).hexdigest() == _INLINE_RESOURCES_SHA256
    except (AttributeError, TypeError, ValueError, OSError):
        same = False
    verdict = resources if same else _NO_INLINE
    _inline_checked.append((resources, verdict))
    return verdict
'''

# Files that pin private_heat_low_ledger_inventory_r1.py, directly or through another pinned file.
CASCADE = (
    ('private_heat_certification_resources_r1.py', 'private_heat_low_ledger_inventory_r1.py'),
    ('private_heat_finish_inventory_r1.py', 'private_heat_low_ledger_inventory_r1.py'),
    ('private_heat_geometry_inventory_r1.py', 'private_heat_low_ledger_inventory_r1.py'),
    ('private_heat_geometry_inventory_r3.py', 'private_heat_geometry_inventory_r1.py'),
    ('private_heat_finish_inventory_r2.py', 'private_heat_finish_inventory_r1.py'),
)


def transform(source, *, allow_unreviewed_input=False):
    if '_FRACTION_ZERO_SIZE' in source:
        raise ValueError('L1 transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('low_ledger input is not the reviewed 42054fb2; pass allow_unreviewed_input and re-run '
                         'the same-call control')
    for anchor, name in ((OLD_INIT, '__init__'), (OLD_OP, 'op'), (OLD_SLOT, 'slot'), (ANCHOR_CONST, 'constant')):
        if source.count(anchor) != 1:
            raise ValueError('L1 %s anchor must occur exactly once' % name)
    return (source.replace(OLD_INIT, NEW_INIT).replace(OLD_OP, NEW_OP).replace(OLD_SLOT, NEW_SLOT)
            .replace(ANCHOR_CONST, NEW_CONST))


def repin(source, name, before, after):
    """Replace exactly one occurrence of `'name': 'before'` with the new digest; nothing else."""
    old, new = "'%s': '%s'" % (name, before), "'%s': '%s'" % (name, after)
    if source.count(old) != 1 or source.count(before) != 1:
        raise ValueError('pin for %s must occur exactly once' % name)
    return source.replace(old, new)


def repin_cascade(read, write):
    """read(name) -> text and write(name, text) on one helpers directory, low_ledger already transformed.

    Rewrites each pinner in CASCADE order, so every pin names the digest of the file as it now is.
    Returns [(file, old sha, new sha)].
    """
    log = []
    for pinner, pinned in CASCADE:
        target = sha256(read(pinned).encode()).hexdigest()
        text = read(pinner)
        current = [line for line in text.splitlines() if "'%s': '" % pinned in line]
        if len(current) != 1:
            raise ValueError('%s must pin %s exactly once' % (pinner, pinned))
        before = current[0].split("'%s': '" % pinned)[1][:64]
        out = repin(text, pinned, before, target)
        write(pinner, out)
        log.append((pinner, sha256(text.encode()).hexdigest(), sha256(out.encode()).hexdigest()))
    return log


if __name__ == '__main__':
    import sys
    from pathlib import Path
    helpers = Path(sys.argv[1])
    path = helpers/'private_heat_low_ledger_inventory_r1.py'
    src = path.read_bytes().decode('utf8')
    out = transform(src)
    path.write_bytes(out.encode('utf8'))
    print('low_ledger', sha256(src.encode()).hexdigest(), '->', sha256(out.encode()).hexdigest())
    for row in repin_cascade(lambda n: (helpers/n).read_bytes().decode('utf8'),
                             lambda n, t: (helpers/n).write_bytes(t.encode('utf8'))):
        print(*row)
