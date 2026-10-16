"""Fail-closed checks of ab_pressure_r4._transient on a stand-in module (T/ps, 16 Oct).

The stand-in stage calls _shared_inputs, then _transport_fits, then would start a worker. The stand-in
reference context's verify_boundary counts its calls and can be made to fail on the Nth call. Checks:
  clean        the pass ends before the gate's body and the worker; peak/retained/transient recorded;
               3 inventory checks passed; tool released; local events cleared; no failures
  unbound      the stand-in's function and code objects are the same objects afterwards
  again        get_tool is None and tracemalloc off afterwards; a second pass measures the same
  fail-live    the check with the events live fails -> recorded, the stage never runs, failures listed
  fail-gate    the check at the gate fails -> recorded (not swallowed into a serial run), no gate body,
               no worker, failures listed
  fail-after   the check after release fails -> recorded, failures listed
  traced       tracemalloc already tracing -> an error record and failures, never a measurement
  busy         tool id held by someone else -> an error record, the holder untouched
  no-build     a stage that never builds -> 'never reached', failures listed
Exit 0 only if every check holds.
"""
import contextlib
import sys
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ab_pressure_r4 as H  # noqa: E402

LOG = []


def _shared_inputs(n):
    scratch = [bytes(4096) for _ in range(n)]
    raw = b''.join(scratch)
    return {'a': raw}, ['a'], len(raw), 25*len(raw)


def _transport_fits(size, decoded, child):
    LOG.append('gate body ran')
    return True


def stage(build=True):
    LOG.append('stage ran')
    if build:
        inputs, ids, size, decoded = W._shared_inputs(256)
        _transport_fits(size, decoded, 1)
    LOG.append('worker started')


class Context:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = 0, fail_on

    def verify_boundary(self):
        self.calls += 1
        if self.calls == self.fail_on:
            raise RuntimeError('loaded implementation changed (stand-in)')


W = SimpleNamespace(_shared_inputs=_shared_inputs, _transport_fits=_transport_fits,
                    parallel=lambda policy, context: contextlib.nullcontext())
S = SimpleNamespace(InterfaceParallelPolicy=lambda **kw: kw)


def args(fail_on=None):
    return SimpleNamespace(reference_execution=Context(fail_on), case=None, current=None, partition=None,
                           owner=SimpleNamespace(initial_state=None))


def module(build=True):
    return SimpleNamespace(ACTUATED_CONTROL=None, check_initial_pressure_force=lambda *a, **kw: stage(build))


def run(fail_on=None, build=True):
    LOG.clear()
    a = args(fail_on)
    seen = H._transient(W, S, module(build), a, {})
    return seen, H._transient_failures(seen), list(LOG), a.reference_execution.calls


def main():
    bad = []

    def verdict(name, ok, *show):
        print(name, ok, *show)
        if not ok:
            bad.append(name)

    objects = (W._shared_inputs, W._transport_fits, W._shared_inputs.__code__, W._transport_fits.__code__)
    seen, fails, log, calls = run()
    verdict('clean', not fails and log == ['stage ran'] and calls == 3
            and seen['inventory_checks'] == dict(events_live='passed', at_gate='passed', after_release='passed')
            and seen['raw_bytes'] == 256*4096 and seen['traced_peak'] >= 2*256*4096
            and 256*4096 <= seen['traced_retained'] < seen['traced_peak'] and seen['transient'] > 0
            and seen['tool_released'] is True and seen['local_events_cleared'] is True, seen, log)
    verdict('unbound', objects == (W._shared_inputs, W._transport_fits, W._shared_inputs.__code__,
                                   W._transport_fits.__code__))
    again, fails2, _, _ = run()
    verdict('again', sys.monitoring.get_tool(H._TOOL) is None and not tracemalloc.is_tracing() and not fails2
            and again['raw_bytes'] == seen['raw_bytes'])
    seen, fails, log, calls = run(fail_on=1)
    verdict('fail-live', seen['inventory_checks']['events_live'].startswith('FAILED') and not log and fails
            and 'traced_peak' not in seen and seen['tool_released'] is True, fails)
    seen, fails, log, calls = run(fail_on=2)
    verdict('fail-gate', seen['inventory_checks']['at_gate'].startswith('FAILED') and log == ['stage ran']
            and any('at_gate' in f for f in fails) and seen['tool_released'] is True, fails)
    seen, fails, log, calls = run(fail_on=3)
    verdict('fail-after', seen['inventory_checks']['after_release'].startswith('FAILED')
            and any('after_release' in f for f in fails), fails)
    tracemalloc.start()
    try:
        seen, fails, log, calls = run()
    finally:
        tracemalloc.stop()
    verdict('traced', seen.get('error') == 'tracemalloc was already tracing' and 'traced_peak' not in seen
            and 'gate body ran' not in log and 'worker started' not in log and fails, fails)
    sys.monitoring.use_tool_id(H._TOOL, 'holder')
    try:
        seen, fails, log, calls = run()
        verdict('busy', 'unavailable' in seen.get('error', '') and sys.monitoring.get_tool(H._TOOL) == 'holder'
                and fails and not log, fails)
    finally:
        sys.monitoring.free_tool_id(H._TOOL)
    seen, fails, log, calls = run(build=False)
    verdict('no-build', seen.get('error') == 'the shared-input build was never reached' and fails
            and log == ['stage ran', 'worker started'], fails)
    print('TRANSIENT CHECK PASS' if not bad else 'TRANSIENT CHECK FAIL %r' % bad)
    raise SystemExit(1 if bad else 0)


if __name__ == '__main__':
    main()
