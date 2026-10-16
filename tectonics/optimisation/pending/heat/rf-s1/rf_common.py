"""Shared helpers for the S1 refuter. Read-only use of the layout; writes only under hs/rf-s1."""
import gc
import json
import random
import sys
from fractions import Fraction as F
from pathlib import Path

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
LAYOUT, S1 = T/'hs'/'lh', T/'hs'/'s1'
sys.path[:0] = [str(S1)] + json.loads((LAYOUT/'control.json').read_text(encoding='utf8'))['paths']
import gmpy2 as G  # noqa: E402
from atlas_tectonics.resources import WorkBudget  # noqa: E402
import private_heat_closed_owned_r4 as Q4  # noqa: E402
import private_heat_closed_owned_r5 as Q5  # noqa: E402
import private_heat_finish_arithmetic_r1 as A  # noqa: E402


def canon(value):
    if isinstance(value, dict):
        return ('d', tuple((k, canon(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(canon(v) for v in value))
    if type(value) is type(G.mpq(0)):
        return ('q', int(value.numerator), int(value.denominator))
    if type(value) is float:
        return ('f', value.hex())
    if value is None or type(value) in (bool, int, str):
        return (type(value).__name__, value)
    raise TypeError('uncanonical %r' % type(value))


def q(x):
    x = F(x)
    return G.mpq(x.numerator, x.denominator)


def build(old_e, caps, pairs, low_q, high_q, bounds):
    """old stocks, capacities, faces -> closed_guard argument tuple (6 cells chain style, generalised)."""
    def energies(qs):
        e = list(old_e)
        for (i, j), v in zip(pairs, qs, strict=True):
            e[i] -= v
            e[j] += v
        return e
    low, high = energies(low_q), energies(high_q)
    faces = lambda qs: [(i, j, q(v)) for (i, j), v in zip(pairs, qs, strict=True)] + [(0, None, G.mpq(0))]
    return ([q(v) for v in old_e], [q(c) for c in caps], [q(v) for v in low], [q(v) for v in high],
            faces(low_q), faces(high_q), [q(b) for b in bounds])


def call(module, args, budget_bytes=1 << 34, cancelled=None):
    """Return (outcome tuple, budget used after gc). Outcome compares by value."""
    budget = WorkBudget(budget_bytes)
    try:
        owner = module.closed_guard(*args, budget=budget, cancelled=cancelled)
    except A.SupplyGuardRefused as error:
        out = ('refused', type(error).__name__, str(error), canon(error.evidence))
    except Exception as error:  # noqa: BLE001 - classify everything
        out = ('exc', type(error).__name__, str(error))
    else:
        try:
            out = ('passed', canon(owner.value), tuple(sorted(owner.inventory.items())))
        finally:
            owner.close()
    error = None
    gc.collect()
    return out, budget._used
