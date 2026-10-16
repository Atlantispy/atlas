import sys
from fractions import Fraction as Q
from pathlib import Path
T = Path(sys.argv[1])
sys.path.insert(0, str(T/'ps'/'scripts'))
import rc1_env
rc1_env.install('frozen:'+str(T/'ps'/'c'/'wr1'))
from atlas_tectonics import integration_differential_mesh as M
f = M._stored_deviation
bad = []
cases = [(Q(1, 3), Q(1)), (Q(1), Q(1)), (Q(2**70+1, 3**50), Q(10**30)), (Q(5, 7), Q(5, 7)), (Q(1, 2**200)+Q(1, 3**200), Q(1)),
         (Q(0), Q(0)), (Q(3*2**64+1, 2**64), Q(3*2**64+1, 2**64))]
for t, w in cases:
    s = f(t, w)
    ok = type(s) is Q and t <= s <= w and (t == 0 or (s-t)/t < Q(1, 2**64))
    if not ok: bad.append((t, w, s))
for t, w in ((Q(2), Q(1)), (Q(-1), Q(1)), (1, Q(1)), (Q(1), 1)):
    try:
        f(t, w); bad.append(('no raise', t, w))
    except M.V.VolumeError:
        pass
print('DEV', 'PASS' if not bad else bad)
