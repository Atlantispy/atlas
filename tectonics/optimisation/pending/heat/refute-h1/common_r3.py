"""Like common.py, but MID/NEW are the r3 transforms (h1a_growth_reserve_r3, h1c_growth_inline_r3)."""
from common import G, OLD, RES, SOURCE, Work, load, make, outcome, state  # noqa: F401
import h1a_growth_reserve_r3 as H1A3
import h1c_growth_inline_r3 as H1C3

AFTER_A = H1A3.transform(SOURCE)
AFTER_C = H1C3.transform(AFTER_A)
MID = load('refute_mid3_growth', AFTER_A)
NEW = load('refute_new3_growth', AFTER_C)
