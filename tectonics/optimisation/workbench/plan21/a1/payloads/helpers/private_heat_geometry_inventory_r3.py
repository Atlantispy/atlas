"""Plan40B explicit new public source binding; historical receipts are unchanged.

Owned startup preparation with a derived inventory for its one record decode.

Successor facade of geometry inventory r1. Admission, source pins, the LOW
inventory, extraction order and the returned owner and plan classes are r1's:
the stage-lifetime helper recognises them unchanged. One component of the
plan differs, ``record_decode_text_objects_parser``, the inventory for the
``geometry.record()`` decode of the issued metric encoding.

r1 charged the installed 1024-byte container unit to every string, number,
container and separator of that encoding, the policy that sizes exact values,
and kept that one figure for the life of the stage. This module charges what
CPython 3.12 json.loads can allocate for those bytes, taken from issuer
resources r4. While the record is decoded the component is r4's peak figure:
the text copy, every object the decode can leave, the key memo and the one
container being resized, sized in advance from the bytes. Once
``geometry.record()`` has returned, the decoded record is counted and the
component falls to what it holds, as for any r4 view. The LOW containers,
rational generations and scalar workspace keep the r1 figures. Where the r4
runtime probe does not hold, the r1 figure is kept throughout.


r3 is r2 with one addition. ``geometry.record()`` is one json.loads with no safe
point inside it. Where the caller's forward call is metered (process meter r1),
that step keeps the plan's calculated figure for the decode reserved across it
as a declared single step; without a meter the statement does nothing. Plan,
admission, order and every figure are r2's.

Accounting policy, NOT an allocator, scratch or RSS proof, as r1 states. This
is a useful stage, not a whole-method resource certificate or native port.
"""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys

import private_heat_geometry_inventory_r1 as BASE
import heat_payload_indexed_patch as INDEXED_PAYLOAD
import private_heat_issuer_resources_r4 as JSON
import private_heat_process_meter_r1 as METER

HERE = Path(__file__).resolve().parent
_PINS = {
    'private_heat_geometry_inventory_r1.py': 'c91ad79da61f3e4bf1f5207e5949f6e05f8c3b028f6e0d7053ec97b0cace4c24',
    'private_heat_issuer_resources_r4.py': 'a936639437dbbe535d46cdd0f38463f3343e437ead5c68cbfe69ee318511a8c1',
}
for _name, _pin in _PINS.items():
    if sha256((HERE/_name).read_bytes()).hexdigest() != _pin:
        raise ValueError('Pinned startup inventory predecessor changed: '+_name)
if (Path(BASE.__file__).resolve() != HERE/'private_heat_geometry_inventory_r1.py'
        or Path(JSON.__file__).resolve() != HERE/'private_heat_issuer_resources_r4.py'):
    raise ValueError('Startup inventory predecessors were loaded from another source')
if Path(METER.__file__).resolve().parent != HERE:
    raise ValueError('Process meter was loaded from another source')
_SELF_SHA = sha256(Path(__file__).read_bytes()).hexdigest()

LOW, L, P, UNIT = BASE.LOW, BASE.L, BASE.P, BASE.UNIT
PreparationPlan, OwnedPreparation = BASE.PreparationPlan, BASE.OwnedPreparation
json_decode_inventory = BASE.json_decode_inventory
_check, _size, _verify_sources = BASE._check, BASE._size, BASE._verify_sources
DECODE = 'record_decode_text_objects_parser'


def _with_decode(plan, count):
    return replace(plan, components=tuple(
        (name, count if name == DECODE else value) for name, value in plan.components))


def admit(geometry, conductivity, boundary, *, budget, cancel=None):
    """r1's owned prospective plan with its record decode re-sized; no decode yet."""
    owner = BASE.admit(geometry, conductivity, boundary, budget=budget, cancel=cancel)
    try:
        plan = owner.value
        if [name for name, _ in plan.components].count(DECODE) != 1:
            raise ValueError('Startup plan lacks its one record-decode component')
        if not INDEXED_PAYLOAD.is_indexed(geometry) and JSON.select_policy() == JSON.DERIVED:
            # Still inside r1's metadata lease: a token scan that copies nothing.
            owner._value = _with_decode(plan, JSON.json_cost(geometry._encoded, cancel).decode_peak_bytes)
            owner.value.total_bytes
        return owner
    except BaseException:
        owner.__exit__(*sys.exc_info())
        raise


def prepare(geometry, conductivity, boundary, *, budget, cancel=None):
    """Return owner of {'prepared', 'payload', 'inventory'}; borrow while live.

    Startup order/numbers are unchanged: LOW extraction then geometry.record().
    No mathematical or numerical reconstruction work is called by this stage.
    """
    owner = admit(geometry, conductivity, boundary, budget=budget, cancel=cancel)
    work = owner._workspace
    try:
        plan = owner.value
        work.resize_before_allocation_or_after_drop(plan.total_bytes)
        _check(cancel)
        prepared = LOW.prepare_geometry(geometry, conductivity, boundary, cancel=cancel)
        _check(cancel)
        if INDEXED_PAYLOAD.is_indexed(geometry):
            payload_owner = work.stack.enter_context(INDEXED_PAYLOAD.materialise(geometry, budget=budget, cancel=cancel))
            payload = payload_owner.value
        else:
            # One json.loads, no safe point inside: a declared single step of a metered call.
            with METER.burst(budget, dict(plan.components)[DECODE]):
                payload = geometry.record()
            _check(cancel)
            if JSON.select_policy() == JSON.DERIVED:
                # geometry.record() is one json.loads of the issued encoding and
                # has returned: its text copy, key memo and growth transients are
                # dropped. The decoded record is counted under the plan's peak
                # figure, and only what it holds stays in the plan.
                cost = JSON.json_cost(geometry._encoded, cancel)
                if dict(plan.components)[DECODE] == cost.decode_peak_bytes:
                    held = min(cost.decode_retained_bytes, JSON.held_bytes(payload, cost, cancel))
                    plan = _with_decode(plan, held)
                    work.resize_before_allocation_or_after_drop(plan.total_bytes)
        owner._value = dict(prepared=prepared, payload=payload, inventory=plan)
        return owner
    except BaseException:
        owner._workspace = None
        owner._value = None
        work.__exit__(*sys.exc_info())
        raise
