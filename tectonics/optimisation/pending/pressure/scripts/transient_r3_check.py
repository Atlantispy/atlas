"""Fail-closed checks of ab_pressure_r3._transient on a stand-in module (T/ps, 16 Oct).

The stand-in stage calls _shared_inputs, then _transport_fits, then would start a worker. Checks:
  stops        the pass ends before the gate's body and the worker; peak, retained and transient recorded
  unbound      the stand-in's function objects and code objects are the same objects afterwards
  released     tool id 3 is free and tracemalloc is off afterwards (the pass can run again)
  traced       tracemalloc already tracing -> an error record, never a measurement
  busy         tool id 3 held by someone else -> an error record, the holder untouched
  no-build     a stage that never builds -> 'never reached'
Exit 0 only if every check holds.
"""
import contextlib
import sys
import tracemalloc
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ab_pressure_r3 as H  # noqa: E402

LOG = []


def _shared_inputs(n):
    scratch = [bytes(4096) for _ in range(n)]
    raw = b''.join(scratch)
    return {'a': raw}, ['a'], len(raw), 25*len(raw)


def _transport_fits(size, decoded, child):
    LOG.append('gate body ran')
    return True


def stage(build=True):
    if build:
        inputs, ids, size, decoded = W._shared_inputs(256)
        _transport_fits(size, decoded, 1)
    LOG.append('worker started')


W = SimpleNamespace(_shared_inputs=_shared_inputs, _transport_fits=_transport_fits,
                    parallel=lambda policy, context: contextlib.nullcontext())
S = SimpleNamespace(InterfaceParallelPolicy=lambda **kw: kw)
A = SimpleNamespace(reference_execution=None, case=None, current=None, partition=None,
                    owner=SimpleNamespace(initial_state=None))


def module(build=True):
    return SimpleNamespace(ACTUATED_CONTROL=None,
                           check_initial_pressure_force=lambda *args, **kw: stage(build))


def main():
    bad = []
    objects = (W._shared_inputs, W._transport_fits, W._shared_inputs.__code__, W._transport_fits.__code__)
    LOG.clear()
    seen = H._transient(W, S, module(), A, {})
    ok = (not LOG and seen.get('raw_bytes') == 256*4096 and seen['traced_peak'] >= 2*256*4096
          and 256*4096 <= seen['traced_retained'] < seen['traced_peak'] and seen['transient'] > 0)
    print('stops', ok, seen, LOG)
    bad += [] if ok else ['stops']
    ok = objects == (W._shared_inputs, W._transport_fits, W._shared_inputs.__code__, W._transport_fits.__code__)
    print('unbound', ok)
    bad += [] if ok else ['unbound']
    ok = sys.monitoring.get_tool(H._TOOL) is None and not tracemalloc.is_tracing()
    again = H._transient(W, S, module(), A, {})
    ok = ok and again.get('raw_bytes') == seen['raw_bytes']
    print('released', ok)
    bad += [] if ok else ['released']
    tracemalloc.start()
    try:
        LOG.clear()
        seen = H._transient(W, S, module(), A, {})
    finally:
        tracemalloc.stop()
    ok = seen.get('error') == 'tracemalloc was already tracing' and 'traced_peak' not in seen and not LOG
    print('traced', ok, seen)
    bad += [] if ok else ['traced']
    sys.monitoring.use_tool_id(H._TOOL, 'holder')
    try:
        seen = H._transient(W, S, module(), A, {})
        ok = 'unavailable' in seen.get('error', '') and sys.monitoring.get_tool(H._TOOL) == 'holder'
    finally:
        sys.monitoring.free_tool_id(H._TOOL)
    print('busy', ok, seen)
    bad += [] if ok else ['busy']
    LOG.clear()
    seen = H._transient(W, S, module(build=False), A, {})
    ok = seen == dict(error='the shared-input build was never reached') and LOG == ['worker started']
    print('no-build', ok, seen)
    bad += [] if ok else ['no-build']
    print('TRANSIENT CHECK PASS' if not bad else 'TRANSIENT CHECK FAIL %r' % bad)
    raise SystemExit(1 if bad else 0)


if __name__ == '__main__':
    main()
