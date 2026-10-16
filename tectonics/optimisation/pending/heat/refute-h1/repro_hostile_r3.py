"""Cases 1-9 (repro_hostile_r2.py) re-run against r3, plus r3-specific probes 10-12."""
import sys

import common_r3
sys.modules['common_r2'] = common_r3     # repro_hostile_r2 does `from common_r2 import ...`
import repro_hostile_r2 as P  # noqa: E402  (prints cases 1-9 on import)
from common_r3 import G, OLD, NEW, RES  # noqa: E402

show = P.show


# 10. Impure `slots` property (alternating values). The original reads slots twice per reserve;
#     r3's hit path reads it once and reuses a total computed from an earlier pair of reads.
def alternating(m):
    class Alt(m.Arithmetic):
        @property
        def slots(self):
            self._reads = getattr(self, '_reads', 0)+1
            return self._base if self._reads % 2 else self._base+500

        @slots.setter
        def slots(self, value):
            self._base = value
    return Alt


def three_reserves(a):
    for _ in range(3):
        a.reserve(a.peak_bits)
    return a._reads


show('10 impure slots property, three reserve(peak) calls', three_reserves, alternating)


# 11. Partial inline then fallback: a is mpq (inline reads its getters), b is int with an
#     overriding _integer (original body runs). Also a bad b after an int a with override.
def over_integer(m):
    class O(m.Arithmetic):
        def _integer(self, value):
            return super()._integer(value)+7
    return O


for op in ('add', 'divide', 'bogus'):
    show('11 mpq a, int b, _integer override, %s' % op, lambda a, op=op: a.rational(op, G.mpq(5, 7), 9),
         over_integer)
show('11 int a with override, bad b', lambda a: a.rational('add', 3, 1.5), over_integer)
show('11 q(int) with override', lambda a: a.q(12345), over_integer)


# 12. Route-state changes mid-life: G swapped to an equivalent namespace, R to a proxy,
#     sys.modules entry removed and restored.
class SameG:
    def __getattr__(self, name):
        return getattr(G, name)


class ProxyR:
    def __getattr__(self, name):
        return getattr(RES, name)


def churn(a):
    out = []
    for step in range(12):
        if step == 3:
            a.G = SameG()
        if step == 5:
            a.G = G
            a.R = ProxyR()
        if step == 7:
            a.R = RES
            saved = sys.modules.pop('private_heat_gmp_resources_r1')
        if step == 9:
            sys.modules['private_heat_gmp_resources_r1'] = saved
        for op in ('add', 'multiply', 'divide'):
            out.append(repr(a.rational(op, G.mpq(step+1, 3), G.mpz(step*1000+1))))
        out.append(repr(a.q(G.mpq(step, 7))))
        out.append(repr(a.q(step*10**20)))
        out.append((a.peak_bits, a.operations, a.workspace.lease.count))
    return out


show('12 G/R/sys.modules churn', churn)
print('NEW inline state:', NEW._inline_verified[0][0] is RES, len(NEW._inline_checked))
