"""H2 (coordinator D-k, 16 Oct 2026): fused interval dot in the heat certification kernel.

Two source transforms on helpers EMITTED by private_heat_bundle.construct_compact_successor
(..., live_memory=True). The output file names stay the same:
- transform(source): private_heat_certification_kernel_r1.py, the dot() below.
- repin(source, kernel_before, kernel_after): private_heat_certification_resources_r1.py,
  the ONLY helper that pins the kernel's sha256 (T/hs/pin_graph.py). Exactly one pin string
  is replaced, and nothing pins certification_resources_r1 itself.

The original Arithmetic.dot accumulates value = self.add(value, self.mul(x, y)). For each
pair of intervals x = (x0, x1), y = (y0, y1), that means:
  check('interval-product');
  lo = min of down.mul over (x0,y0), (x0,y1), (x1,y0), (x1,y1), via a generator;
  hi = max of up.mul over the same four, via a generator;
  check('interval-add'); down.add(value_lo, lo), up.add(value_hi, hi).
The fused loop does the same work in one frame, with no generator, tuple or method-call
overhead:
- The same check() calls in the same order, with the same phase strings.
- The same MPFR context methods (self.down / self.up, bound once per dot).
- The same products in the same order. min/max are written out with the comparison
  builtins.min and builtins.max make: an item replaces the running value only if it is
  strictly smaller (`t < lo`) or strictly larger (`t > hi`). So the same object is
  selected, and each comparison happens at the same point between the same products,
  exactly where the generator form makes it. An exception raised by a product or by a
  comparison is therefore raised at the same place.
- The same accumulation order and contexts for both bounds.
The fast path applies only to a plain Arithmetic instance (not a subclass) without
instance-level mul/add, and to 2-tuple intervals. Anything else runs the original loop
unchanged.

Record identity: numbers byte-identical. The kernel's digest and the pin in
certification_resources_r1 change, and with them the issuer's runtime private_sources
bindings: digest-only under D-b, proved by the same-call control.
"""
from hashlib import sha256
import re

KERNEL_INPUT_SHA256 = {
    '370b6ec1c579b8fbacd76f6880f70d39df1531567112c5008397283fe902f820':
        'private_heat_certification_kernel_r1.py emitted by construct_compact_successor (reviewed-inputs-r2)',
}
RESOURCES_INPUT_SHA256 = {
    'c9bcb788cffb702b66ab36de19111a3801f494cc62427b45a4cec6207bf5dbed':
        'private_heat_certification_resources_r1.py emitted by construct_compact_successor (reviewed-inputs-r2)',
}

OLD = '''\
    def dot(self, a, b):
        value = (self.zero, self.zero)
        for x, y in zip(a, b, strict=True):
            value = self.add(value, self.mul(x, y))
        return value
'''

NEW = '''\
    def dot(self, a, b):
        if type(self) is not Arithmetic or 'mul' in self.__dict__ or 'add' in self.__dict__:
            value = (self.zero, self.zero)
            for x, y in zip(a, b, strict=True):
                value = self.add(value, self.mul(x, y))
            return value
        # H2: mul() then add() of each pair fused, with the same checks, contexts,
        # products, comparisons and accumulation order (min/max written out).
        check, dmul, umul, dadd, uadd = self.check, self.down.mul, self.up.mul, self.down.add, self.up.add
        lo = hi = self.zero
        for x, y in zip(a, b, strict=True):
            if type(x) is not tuple or type(y) is not tuple or len(x) != 2 or len(y) != 2:
                lo, hi = self.add((lo, hi), self.mul(x, y))
                continue
            x0, x1 = x
            y0, y1 = y
            check('interval-product')
            plo = dmul(x0, y0)
            t = dmul(x0, y1)
            if t < plo:
                plo = t
            t = dmul(x1, y0)
            if t < plo:
                plo = t
            t = dmul(x1, y1)
            if t < plo:
                plo = t
            phi = umul(x0, y0)
            t = umul(x0, y1)
            if t > phi:
                phi = t
            t = umul(x1, y0)
            if t > phi:
                phi = t
            t = umul(x1, y1)
            if t > phi:
                phi = t
            check('interval-add')
            lo, hi = dadd(lo, plo), uadd(hi, phi)
        return lo, hi
'''


def transform(source, *, allow_unreviewed_input=False):
    if '# H2: mul() then add()' in source:
        raise ValueError('H2 fused-dot transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KERNEL_INPUT_SHA256:
        raise ValueError('certification kernel input is not the reviewed module; pass allow_unreviewed_input '
                         'and re-run the same-call control')
    if source.count(OLD) != 1 or source.count('\nclass Arithmetic:\n') != 1:
        raise ValueError('H2 dot anchor must occur exactly once')
    return source.replace(OLD, NEW)


def repin(source, kernel_before, kernel_after, *, allow_unreviewed_input=False):
    """Replace the kernel's pin in certification_resources_r1, exactly once."""
    for value in (kernel_before, kernel_after):
        if not re.fullmatch('[0-9a-f]{64}', value):
            raise ValueError('sha256 hex digests required')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in RESOURCES_INPUT_SHA256:
        raise ValueError('certification resources input is not the reviewed module')
    old = "    'private_heat_certification_kernel_r1.py': '%s',\n" % kernel_before
    if source.count(old) != 1 or source.count(kernel_before) != 1:
        raise ValueError('kernel pin must occur exactly once')
    return source.replace(old, "    'private_heat_certification_kernel_r1.py': '%s',\n" % kernel_after)


if __name__ == '__main__':
    import sys
    from pathlib import Path
    helpers = Path(sys.argv[1])          # a helpers folder holding the two reviewed inputs; rewritten in place
    kp, rp = helpers/'private_heat_certification_kernel_r1.py', helpers/'private_heat_certification_resources_r1.py'
    kin, rin = kp.read_bytes(), rp.read_bytes()
    kout = transform(kin.decode('utf8')).encode('utf8')
    rout = repin(rin.decode('utf8'), sha256(kin).hexdigest(), sha256(kout).hexdigest()).encode('utf8')
    kp.write_bytes(kout)
    rp.write_bytes(rout)
    for name, a, b in ((kp.name, kin, kout), (rp.name, rin, rout)):
        print(name, sha256(a).hexdigest(), '->', sha256(b).hexdigest())
