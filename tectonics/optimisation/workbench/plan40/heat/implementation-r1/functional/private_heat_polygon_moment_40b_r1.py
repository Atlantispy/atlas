"""C13 polygon successor under the unchanged native prospective/retained owners.

The old plan charges every generated scalar cumulatively, including repeated
norms, edges and both matrix triangles. Retaining an earlier norm/edge and
aliasing immutable symmetric result scalars stays within that same inventory.
No optional cache lease, relaxed admission, plan reduction or new owner type.
"""
from hashlib import sha256
from fractions import Fraction
from pathlib import Path
import sys

import private_heat_polygon_moment_inventory_r1 as M
import private_heat_owned_value_r4 as RETAIN
import private_heat_polygon_numerics_40b_r1 as NUMERICS


MOMENT_SOURCE_SHA256 = "3702ff5135b841929eb06d83204292531d10ff6b7dcbc2717f2c24f9660137fc"
# Bound by the generated successor's actual bytes before receiving it.
NUMERICS_SHA256 = "5991aca3ed26e65e2290be6c1ee4052f15b74a1e770b9606849263e25b12f00c"
SOURCE_BUFFER_LIMIT = 65536
_NUMERICAL_BINDINGS = tuple((name, getattr(NUMERICS, name), getattr(NUMERICS, name).__code__)
    for name in ("decode", "vector", "dot", "sub", "cross", "face_second_moment"))


def _verify_component_sources():
    # Admission has already funded the predecessor's fixed source-read buffers.
    # Read one small helper at a time; never read geometry or unbounded files.
    for module, expected in ((M, MOMENT_SOURCE_SHA256), (NUMERICS, NUMERICS_SHA256)):
        path = Path(module.__file__)
        if path.stat().st_size > SOURCE_BUFFER_LIMIT:
            raise ValueError("Polygon component source exceeds admitted source buffer")
        if sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Reviewed polygon component source changed")
    if NUMERICS.Q is not Fraction or any(getattr(NUMERICS, name) is not function or function.__code__ is not code
                                       for name, function, code in _NUMERICAL_BINDINGS):
        raise ValueError("Reviewed polygon callable binding changed")


def _prospective_second_moment(face, *, budget, cancel=None):
    owner = M.admit(face, budget=budget, cancel=cancel)
    work = owner._workspace
    try:
        _verify_component_sources()
        plan = owner.value
        work.resize_before_allocation_or_after_drop(plan.total_bytes)
        M._check(cancel)
        moment = NUMERICS.face_second_moment(face)
        M._check(cancel)
        owner._value = dict(moment=moment, inventory=plan)
        work.resize_before_allocation_or_after_drop(plan.retained_bytes)
        return owner
    except BaseException:
        owner._workspace = None
        owner._value = None
        work.__exit__(*sys.exc_info())
        raise


def second_moment(face, *, budget, cancel=None):
    owner = _prospective_second_moment(face, budget=budget, cancel=cancel)
    try:
        return RETAIN.transfer(owner, budget=budget, cancelled=cancel,
            category="heat-retained-polygon-moment", record_types=(M.MomentPlan,))
    except BaseException:
        owner.__exit__(*sys.exc_info())
        raise
