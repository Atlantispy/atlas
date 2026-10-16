from fractions import Fraction as F
import rf_common as c


def author(kind):
    dyadic = kind in ('zero', 'refused')
    caps = [F(2)]*6 if dyadic else [F(3+i, 2) for i in range(6)]
    temps = [F(t) for t in (288, 296, 300, 304, 312, 320)] if dyadic else \
        [F(2881, 10), F(2963, 10), F(3007, 10), F(3041, 10), F(3119, 10), F(3203, 10)]
    old = [cc*t for cc, t in zip(caps, temps, strict=True)]
    pairs = [(i, i+1) for i in range(5)] + [(0, 2), (3, 5)]
    k = F(1, 4) if dyadic else F(1, 13)
    low_q = [k*(temps[i]-temps[j]) for i, j in pairs]
    scale = dict(full=F(3, 2), same=F(1), bisect=F(40), zero=F(-1), refused=F(-1))[kind]
    high_q = [scale*v for v in low_q]
    low_t = None
    def energies(qs):
        e = list(old)
        for (i, j), v in zip(pairs, qs, strict=True):
            e[i] -= v
            e[j] += v
        return e
    lowe = energies(low_q)
    low_t = [e/cc for e, cc in zip(lowe, caps, strict=True)]
    if kind == 'zero':
        bounds = (min(low_t), F(400))
    elif kind == 'refused':
        bounds = (min(low_t)+F(1, 8), F(400))
    else:
        bounds = (min(temps)-1, max(temps)+1)
    return c.build(old, caps, pairs, low_q, high_q, bounds)


def swap():
    cap = [F(3, 2)]*2
    a, b = F(300), F(200)
    old = [cap[0]*a, cap[1]*b]
    return c.build(old, cap, [(0, 1)], [F(7, 3)], [old[0]-old[1]], [F(150), F(350)])
