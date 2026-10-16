"""Unchanged prospective polygon moment, transferred to actual retained shape.

M1 already admits every expression before calculation. Once its numerical frame
returns, retain the exact moment and unchanged immutable plan using complete
object counts; do not keep M1's generic128KiB result-container allowance perface.

R3 retains through owned value r3: the moment that exists is charged at the
blocks it occupies. M1 and its plan are unchanged.

R4 retains through owned value r4, which counts by counted blocks r2 and adds
that module's allowance for the early instances of the plan's class.
"""
import sys

import private_heat_polygon_moment_inventory_r1 as M
import private_heat_owned_value_r4 as RETAIN


def second_moment(face, *, budget, cancel=None):
    owner = M.second_moment(face, budget=budget, cancel=cancel)
    try:
        return RETAIN.transfer(owner, budget=budget, cancelled=cancel,
            category='heat-retained-polygon-moment', record_types=(M.MomentPlan,))
    except BaseException:
        owner.__exit__(*sys.exc_info())
        raise
