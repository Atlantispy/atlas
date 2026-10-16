"""fuzz_targeted.py's scenarios against the r2 transforms (OLD vs H1a r2 vs H1a r2 + H1c r2)."""
import sys

import common_r2
sys.modules['common'] = common_r2          # fuzz_targeted does `from common import ...`
import fuzz_targeted as F  # noqa: E402
from common_r2 import G, OLD, NEW, RES, make, outcome, state  # noqa: E402


class Proxy:
    """Same functions as gmp_resources_r1, different object: r2 must fall back, results equal."""
    def __getattr__(self, name):
        return getattr(RES, name)


def proxy_scenario(m):
    out = []
    a, w = make(m)
    for i in range(40):
        if i == 10:
            a.R = Proxy()
        if i == 25:
            a.R = RES
        x = G.mpq(i*7919+1, i+3) if i % 2 else G.mpz(i*104729)
        for op in ('add', 'subtract', 'multiply', 'divide', 'bad'):
            out.append(outcome(lambda: a.rational(op, x, G.mpq(-5, 3))))
        out.append(outcome(lambda: a.q(x)))
        out.append(outcome(lambda: a.reserve(a.peak_bits)))
        out.append(state(a, w))
    return out


F.main()
F.check('proxy', [proxy_scenario(m) for m in (OLD, F.MID, NEW)])
print('inline route verified for RES:', NEW._INLINE_RESOURCES[0] is RES, 'checked:', len(NEW._INLINE_CHECKED))
print('total failures:', len(F.FAIL))
