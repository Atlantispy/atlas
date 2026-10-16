"""Like common.py, but MID/NEW are the r2 transforms (h1a_growth_reserve_r2, h1c_growth_inline_r2)."""
import common as _c
from common import G, OLD, RES, SOURCE, Work, load, make, outcome, state  # noqa: F401
import h1a_growth_reserve_r2 as H1A2
import h1c_growth_inline_r2 as H1C2

AFTER_A = H1A2.transform(SOURCE)
AFTER_C = H1C2.transform(AFTER_A)
MID = load('refute_mid2_growth', AFTER_A)
NEW = load('refute_new2_growth', AFTER_C)
del _c
