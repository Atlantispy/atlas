"""Refuter i19, R1: an interrupted session stop inside InitialParallel.close() cannot be retried.

No fixture, no worker launched, no atlas_tectonics callable patched. A real InitialParallel opens a
real InitialParallelSession (storage lease, strict context, registered RevocableOwner, directory) on
an empty partition. The interruption is injected the way the base contract models it: an object
whose close() raises KeyboardInterrupt is placed in the session's _read_ahead slot, which
ComponentParallelSession._stop closes first (a Ctrl-C landing inside the stop has the same effect:
RevocableOwner.state becomes INTERRUPTED and nothing is released).

Arms:
  initial   InitialParallel (candidate): first close raises; then retry close; then consequences.
  endpoint  EndpointBatchPass (base, same session class family): first close raises; retry close.
  serial    a fresh budget with no pass: the same mandatory reservation.
  reading   InitialParallel whose read-ahead close raises: session never closed.
Usage: python -B r1_close_retry.py   (PYTHONHASHSEED=0)
"""
import json
import sys
from fractions import Fraction as Q
from pathlib import Path
from types import SimpleNamespace

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
R = T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
sys.path[:0] = [str(T/'ck/ip8/src'), str(R/'composed-r2/helpers'),
                str(T/'fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests')]

import atlas_tectonics  # noqa: E402
assert Path(atlas_tectonics.__file__).resolve().is_relative_to(T/'ck/ip8/src')
from atlas_tectonics.resources import WorkBudget  # noqa: E402
from atlas_tectonics.reuse import ExecutionContext, require_strict_execution  # noqa: E402
from atlas_tectonics import integration_initial_parallel as IP  # noqa: E402
from atlas_tectonics.integration_component_volume_parallel import (  # noqa: E402
    ComponentParallelSession, EndpointBatchPass)

GIB = 1 << 30


class Interrupt:
    """Stands in for a Ctrl-C arriving while the session stops its read-ahead/children."""
    def __init__(self):
        self.armed = True

    def close(self):
        if self.armed:
            raise KeyboardInterrupt('simulated interrupt during the optional session stop')


def state(budget, base):
    revoker = budget._revoker
    return dict(reserved_over_base=budget.reserved_bytes-base,
                owner_registered=revoker is not None,
                owner_state=None if revoker is None else revoker.state)


def mandatory(budget):
    """A mandatory reservation that fits only once optional work is revoked."""
    try:
        with budget.reserve(GIB-(1 << 20), category='refuter-mandatory'):
            return 'admitted'
    except BaseException as error:  # noqa: BLE001 - record exactly what the caller would see
        return '%s: %s' % (type(error).__name__, error)


def initial_arm(context):
    budget = WorkBudget(GIB, max_predicate_work_units=1 << 40)
    base = budget.reserved_bytes
    out = {}
    stuck = Interrupt()
    p = IP.InitialParallel(workers=1, budget=budget, context=context)
    try:
        with p:
            started = p.start(SimpleNamespace(supports=[]), budget=budget, relative_error=Q(1, 100),
                              max_width_m3=Q(1), max_leaves=8)
            out['opened'] = started is p
            out['while_open'] = state(budget, base)
            p.session._read_ahead = stuck
        out['first_close'] = 'returned'
    except KeyboardInterrupt as error:
        out['first_close'] = 'KeyboardInterrupt: %s' % error
    out['after_first_close'] = dict(state(budget, base), pass_closed=p.closed,
                                    pass_session_is_none=p.session is None, active_is_none=IP.active() is None)
    stuck.armed = False            # the interrupt is over; an explicit close may now resume cleanup
    try:
        p.close()
        out['retry_close'] = 'returned'
    except BaseException as error:  # noqa: BLE001
        out['retry_close'] = '%s: %s' % (type(error).__name__, error)
    out['after_retry_close'] = state(budget, base)
    with IP.InitialParallel(workers=1, budget=budget, context=context) as q:
        again = q.start(SimpleNamespace(supports=[]), budget=budget, relative_error=Q(1, 100),
                        max_width_m3=Q(1), max_leaves=8)
        out['later_pass_opens'] = again is q
        out['later_pass_note'] = q.report['note']
    out['mandatory_reservation'] = mandatory(budget)
    out['after_mandatory'] = state(budget, base)
    return out


def endpoint_arm(context):
    budget = WorkBudget(GIB, max_predicate_work_units=1 << 40)
    base = budget.reserved_bytes
    out = {}
    stuck = Interrupt()
    session = ComponentParallelSession(budget=budget, max_width_m3=Q(1), max_leaves=8, workers=1)
    p = EndpointBatchPass(session=session, context=lambda: context)
    p.prepare([])
    out['opened'] = session.active()
    out['while_open'] = state(budget, base)
    session._read_ahead = stuck
    try:
        p.close()
        out['first_close'] = 'returned'
    except KeyboardInterrupt as error:
        out['first_close'] = 'KeyboardInterrupt: %s' % error
    out['after_first_close'] = dict(state(budget, base), pass_closed=p.closed)
    stuck.armed = False
    try:
        p.close()
        out['retry_close'] = 'returned'
    except BaseException as error:  # noqa: BLE001
        out['retry_close'] = '%s: %s' % (type(error).__name__, error)
    out['after_retry_close'] = state(budget, base)
    out['mandatory_reservation'] = mandatory(budget)
    return out


def serial_arm():
    budget = WorkBudget(GIB, max_predicate_work_units=1 << 40)
    return dict(mandatory_reservation=mandatory(budget))


def reading_arm(context):
    """_stop_reading() raises before session.close() is reached."""
    budget = WorkBudget(GIB, max_predicate_work_units=1 << 40)
    base = budget.reserved_bytes
    out = {}
    stuck = Interrupt()
    p = IP.InitialParallel(workers=1, budget=budget, context=context)
    try:
        with p:
            p.start(SimpleNamespace(supports=[]), budget=budget, relative_error=Q(1, 100),
                    max_width_m3=Q(1), max_leaves=8)
            p.jobs = stuck           # an interrupt while the read-ahead generator is being closed
        out['first_close'] = 'returned'
    except KeyboardInterrupt as error:
        out['first_close'] = 'KeyboardInterrupt: %s' % error
    stuck.armed = False
    session = budget._revoker.stop.__self__ if budget._revoker is not None else None
    out['after_first_close'] = dict(state(budget, base), pass_closed=p.closed,
                                    pass_session_is_none=p.session is None,
                                    session_closed=None if session is None else session.closed)
    p.close()
    out['after_retry_close'] = dict(state(budget, base),
                                    session_closed=None if session is None else session.closed)
    with IP.InitialParallel(workers=1, budget=budget, context=context) as q:
        out['later_pass_opens'] = q.start(SimpleNamespace(supports=[]), budget=budget, relative_error=Q(1, 100),
                                          max_width_m3=Q(1), max_leaves=8) is q
        out['later_pass_note'] = q.report['note']
    out['mandatory_reservation'] = mandatory(budget)
    out['after_mandatory'] = state(budget, base)
    with IP.InitialParallel(workers=1, budget=budget, context=context) as q:
        out['later_pass_opens_after_mandatory'] = q.start(
            SimpleNamespace(supports=[]), budget=budget, relative_error=Q(1, 100),
            max_width_m3=Q(1), max_leaves=8) is q
        out['later_pass_note_after_mandatory'] = q.report['note']
    return out


def main():
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    require_strict_execution()
    with ExecutionContext('reference') as context:
        report = dict(initial=initial_arm(context), endpoint=endpoint_arm(context), serial=serial_arm(),
                      reading=reading_arm(context))
    text = json.dumps(report, indent=1, default=str)
    (Path(__file__).parent/'ip8_r1_close_retry.json').write_text(text, encoding='utf8')
    print(text)


if __name__ == '__main__':
    main()
