"""q01 (H4 heat worker sweep) fails closed: planted mutants, a stand-in parallel module, stand-in children; no heat run.

Run (PYTHONHASHSEED=0, through runq.py small): python -B test_h4_fail_closed.py

_verdict: a complete sweep exits 0; an arm missing, stopped, recorded with another count, not PASS, not
IDENTICAL (False, missing or not a bool), with differences or none recorded, without calls, with a call
unrecorded (report() keeps 16), set to another count, or a layout or reference changed or undigested,
exits 1; every arm IDENTICAL with a call that used fewer workers or fell back exits 3.
_read_arm: a missing or unreadable result, a missing field, a count field that is None or not an int, a
missing minimum_faces or totals is incomplete; the workers expected follow the module's own rule.
_gate: the unchanged 10 GiB rule, its wait and its refusal. The guards are the stated ones.
child: with a stand-in parallel module and control, the module is set through configure(); a None ID
(even when the reference has None too), reference arrays absent or different, or a control that does not
PASS is not IDENTICAL; an existing output or a module loaded from outside the layout refuses.
run (stand-in children through the real loop): exit 0 only when everything holds, with each arm's gate
decision recorded; exit 1 on a child that fails, writes nothing or leaves a field out, an arm not
IDENTICAL, a layout or reference changed during the run, a gate refusal (no child started), a count set
otherwise, a call unrecorded; exit 3 on reduced workers or a fallback; refusals before anything runs.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import h4_heat_workers as H4  # noqa: E402

sys.path.append(str(H4.C))
import step7_same_call_heat_control as CONTROL  # noqa: E402

GIB = 1 << 30
PAR_NAME = 'private_heat_functionals_parallel_r1'
H4_FILE = Path(H4.__file__).resolve()
HOOKS = dict(profile=False, trace=False, tracemalloc=False, monitoring_tools=[])


def call_fields(count, to_reconstruct=150, **changes):
    """One reconstruction call as the child records it (the fields _read_arm copies, and a few more)."""
    workers = min(count, to_reconstruct) if to_reconstruct >= 16 and min(count, to_reconstruct) >= 2 else 0
    row = dict(faces=to_reconstruct+20, to_reconstruct=to_reconstruct, configured=count, workers=workers,
               collected=to_reconstruct if workers else 0, in_caller=0 if workers else to_reconstruct,
               fallback=None if workers else 'the call is not metered or has fewer than two workers',
               ready_seconds=.1, seconds=1., worker_compute_seconds=5., parallel_efficiency=.8,
               worker_working_set_peak_max=1 << 26, worker_private_peak_max=1 << 25, restarted=False)
    row.update(changes)
    return row


def child_result(count, calls=None, **h4_changes):
    """A complete child result: the control's output with its h4 record."""
    calls = [call_fields(count), call_fields(count, 10)] if calls is None else calls
    h4 = dict(identical=True, differing_from_reference=[], minimum_faces=16, calls=calls,
              totals=dict(calls=len(calls), fallbacks=sum(call['fallback'] is not None for call in calls)),
              fallbacks=[], other_load_cpus=.5, module_sha256='0'*64, hooks_before=HOOKS, hooks_after=HOOKS)
    h4.update(h4_changes)
    return dict(status='PASS', legacy=dict(seconds=1.5), compact=dict(seconds=1.25), elapsed_seconds=10.,
                peak_working_set_bytes=1 << 28, h4=h4)


class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='h4t-')).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.files = 0

    def arm(self, count, k=0, result=None):
        """An arm record completed by _read_arm from a child result written to a temp file."""
        self.files += 1
        out = self.tmp/('result-%d.json' % self.files)
        out.write_text(json.dumps(child_result(count) if result is None else result), encoding='utf8')
        arm = {'arm': k, 'workers': count, 'exit_code': 0}
        return arm, H4._read_arm(arm, out)


class Verdict(Temp):
    def summary(self, counts=(6, 8, 6)):
        arms = []
        for k, count in enumerate(counts):
            arm, problem = self.arm(count, k)
            self.assertIsNone(problem)
            arms.append(arm)
        return dict(counts=list(counts), arms=arms, layout_sha256_before='a'*64, layout_sha256_after='a'*64,
                    reference_sha256='r'*64, reference_sha256_after='r'*64)

    def verdict(self, summary):
        return H4._verdict(summary)[0]

    def test_complete_sweep_passes(self):
        self.assertEqual(H4._verdict(self.summary()), (0, [], []))

    def test_arms_missing_or_stopped_or_recorded_otherwise_fail(self):
        for edit in (lambda s: s['counts'].clear(), lambda s: s['arms'].pop(),
                     lambda s: s['arms'][1].update(workers=7), lambda s: s['arms'][2].update(stopped='guard')):
            summary = self.summary()
            edit(summary)
            self.assertEqual(self.verdict(summary), 1)

    def test_an_arm_not_identical_fails(self):
        edits = (dict(status='DIFFERS'), dict(status=None), dict(identical=False), dict(identical='True'),
                 dict(identical=None), dict(differing=['arrays']), dict(differing=None))
        for edit in edits:
            summary = self.summary()
            summary['arms'][1].update(edit)
            self.assertEqual(self.verdict(summary), 1, edit)
        for name in ('status', 'identical', 'differing'):
            summary = self.summary()
            del summary['arms'][0][name]
            self.assertEqual(self.verdict(summary), 1, name)

    def test_calls_missing_unrecorded_or_set_otherwise_fail(self):
        for edit in (lambda arm: arm.update(calls=[]), lambda arm: arm.pop('calls'),
                     lambda arm: arm.update(total_calls=3), lambda arm: arm.pop('total_calls'),
                     lambda arm: arm['calls'][0].update(configured=8)):
            summary = self.summary()
            edit(summary['arms'][0])
            self.assertEqual(self.verdict(summary), 1)

    def test_reduced_workers_or_a_fallback_exit_3_unless_something_fails(self):
        summary = self.summary()
        summary['arms'][2]['calls'][0].update(as_configured=False)
        status, failures, reduced = H4._verdict(summary)
        self.assertEqual((status, failures, len(reduced)), (3, [], 1))
        summary['arms'][0].update(identical=False)
        self.assertEqual(self.verdict(summary), 1)

    def test_layout_or_reference_changed_or_undigested_fails(self):
        for edit in (dict(layout_sha256_after='b'*64), dict(layout_sha256_before=None, layout_sha256_after=None),
                     dict(reference_sha256_after='s'*64), dict(reference_sha256=None, reference_sha256_after=None)):
            summary = self.summary()
            summary.update(edit)
            self.assertEqual(self.verdict(summary), 1, edit)
        for name in ('layout_sha256_after', 'reference_sha256_after'):
            summary = self.summary()
            del summary[name]
            self.assertEqual(self.verdict(summary), 1, name)


class ReadArm(Temp):
    def test_complete_result_is_copied_with_the_expected_workers(self):
        arm, problem = self.arm(6)
        self.assertIsNone(problem)
        self.assertEqual((arm['status'], arm['identical'], arm['differing'], arm['total_calls']), ('PASS', True, [], 2))
        self.assertEqual([(c['configured'], c['workers'], c['expected_workers'], c['as_configured']) for c in arm['calls']],
                         [(6, 6, 6, True), (6, 0, 0, True)])

    def test_expected_workers_follow_the_module_rule(self):
        cases = (  # count, to_reconstruct, workers used, fallback -> expected, as configured
            (6, 150, 6, None, 6, True), (12, 16, 12, None, 12, True), (12, 15, 0, 'serial', 0, True),
            (12, 15, 12, None, 0, False), (1, 150, 0, 'serial', 0, True), (12, 150, 12, None, 12, True),
            (12, 7, 0, 'serial', 0, True), (6, 150, 4, None, 6, False), (6, 150, 6, 'a worker failed', 6, False),
            (6, 3, 0, 'serial', 0, True))
        for count, wanted, used, fallback, expected, as_configured in cases:
            result = child_result(count, calls=[call_fields(count, wanted, workers=used, fallback=fallback)])
            arm, problem = self.arm(count, result=result)
            self.assertIsNone(problem)
            self.assertEqual((arm['calls'][0]['expected_workers'], arm['calls'][0]['as_configured']),
                             (expected, as_configured), (count, wanted, used, fallback))
        result = child_result(6, calls=[call_fields(8)])
        self.assertFalse(self.arm(6, result=result)[0]['calls'][0]['as_configured'])

    def test_missing_or_unreadable_results_are_incomplete(self):
        arm = {'arm': 0, 'workers': 6}
        self.assertIn('FileNotFoundError', H4._read_arm(arm, self.tmp/'absent.json'))
        (self.tmp/'bad.json').write_text('{"status": "PASS"', encoding='utf8')
        self.assertIn('JSONDecodeError', H4._read_arm(arm, self.tmp/'bad.json'))

    def test_each_missing_field_is_incomplete(self):
        paths = [('h4',), ('status',), ('legacy',), ('legacy', 'seconds'), ('compact', 'seconds'), ('elapsed_seconds',),
                 ('peak_working_set_bytes',), ('h4', 'identical'), ('h4', 'differing_from_reference'),
                 ('h4', 'minimum_faces'), ('h4', 'calls'), ('h4', 'totals'), ('h4', 'fallbacks'),
                 ('h4', 'other_load_cpus'), ('h4', 'module_sha256'), ('h4', 'hooks_before')]
        paths += [('h4', 'calls', 0, name) for name in H4.CALL_FIELDS]
        for path in paths:
            result = child_result(6)
            node = result
            for part in path[:-1]:
                node = node[part]
            del node[path[-1]]
            arm, problem = self.arm(6, result=result)
            self.assertIsNotNone(problem, path)
            self.assertIn('incomplete', problem)

    def test_count_fields_that_are_not_integers_are_incomplete(self):
        for name in ('faces', 'to_reconstruct', 'configured', 'workers'):
            for value in (None, True, 6.0, '6'):
                call = call_fields(6)
                call[name] = value
                arm, problem = self.arm(6, result=child_result(6, calls=[call]))
                self.assertIsNotNone(problem, (name, value))
                self.assertIn('TypeError', problem)
        for value in (None, '16', 16.0):
            self.assertIsNotNone(self.arm(6, result=child_result(6, minimum_faces=value))[1], value)
        self.assertIsNotNone(self.arm(6, result=dict(child_result(6), legacy=dict(seconds=None)))[1])


class Gate(unittest.TestCase):
    def test_the_guards_are_the_stated_ones(self):
        self.assertEqual((H4.START_GATE, H4.GATE_WAIT_SECONDS, H4.RSS_GUARD, H4.FREE_FLOOR), (10*GIB, 600, 12*GIB, GIB))

    def gate(self, values):
        values = iter(values)
        with mock.patch.object(H4.psutil, 'virtual_memory', lambda: SimpleNamespace(available=next(values))), \
                mock.patch.object(H4, 'sleep') as slept:
            return H4._gate(), slept.call_count

    def test_passes_at_10_gib_waits_below_and_refuses_after_10_minutes(self):
        self.assertEqual(self.gate([10*GIB]), ((True, 0, 10*GIB), 0))
        self.assertEqual(self.gate([5*GIB, 10*GIB-1, 11*GIB]), ((True, 30, 11*GIB), 2))
        self.assertEqual(self.gate([10*GIB-1]*41), ((False, 600, 10*GIB-1), 40))


# --------------------------------------------------------------- child, with a stand-in module and control
FAKE_PAR = '''
MIN_FACES = 16
_state = dict(workers=6, calls=[])


def configure(*, workers=None):
    if workers is not None:
        _state['workers'] = workers
    return _state['workers']


def reconstruct(wanted):
    count = min(_state['workers'], wanted) if wanted >= MIN_FACES else 0
    count = count if count >= 2 else 0
    _state['calls'].append(dict(
        faces=wanted+20, to_reconstruct=wanted, configured=_state['workers'], workers=count,
        collected=wanted if count else 0, in_caller=0 if count else wanted,
        fallback=None if count else 'the call is not metered or has fewer than two workers', restarted=False,
        second_fallback=None, ready_seconds=.1, seconds=1., slowest_face_seconds=.1, shared_input_bytes=1,
        result_bytes=1, processes=[dict(compute_seconds=.5, ready_seconds=.1, busy_seconds=.6, faces=3,
                                        working_set_peak_bytes=1 << 26, private_peak_bytes=1 << 25)
                                   for _ in range(count)]))


def report():
    calls = _state['calls']
    return dict(workers=_state['workers'], minimum_faces=MIN_FACES, calls=[dict(call) for call in calls],
                totals=dict(calls=len(calls), fallbacks=sum(call['fallback'] is not None for call in calls)),
                fallbacks=[])
'''
SCENARIO = {}


def stand_in_control(directory, out):
    """Stands in for step7_same_call_heat_control.child: two reconstruction calls, then OUT."""
    module = sys.modules[PAR_NAME]
    module.reconstruct(150)
    module.reconstruct(10)
    identity = dict(result_id=SCENARIO.get('result_id', 'r'), metadata_sha256='m', metadata_bytes=1)
    Path(out).write_text(json.dumps(dict(
        status=SCENARIO.get('status', 'PASS'), legacy=dict(identity, seconds=1.5), compact=dict(identity, seconds=1.25),
        arrays=SCENARIO.get('arrays', {'enthalpy_j': 'e'*64}), elapsed_seconds=3., peak_working_set_bytes=1 << 28)),
        encoding='utf8')


class Child(Temp):
    def setUp(self):
        super().setUp()
        self.layout = self.tmp/'layout'
        helpers = self.layout/'helpers'
        helpers.mkdir(parents=True)
        (helpers/(PAR_NAME+'.py')).write_text(FAKE_PAR, encoding='utf8')
        (self.layout/'control.json').write_text(json.dumps(dict(paths=[str(helpers)])), encoding='utf8')
        self.reference = self.tmp/'reference.json'
        self.write_reference()
        sys.modules.pop(PAR_NAME, None)
        self.addCleanup(sys.modules.pop, PAR_NAME, None)
        self.addCleanup(SCENARIO.clear)
        patch = mock.patch.object(CONTROL, 'child', stand_in_control)
        patch.start()
        self.addCleanup(patch.stop)
        self.path = list(sys.path)
        self.addCleanup(self.restore_path)

    def restore_path(self):
        sys.path[:] = self.path

    def write_reference(self, result_id='r', arrays=True):
        identity = dict(result_id=result_id, metadata_sha256='m', metadata_bytes=1)
        reference = dict(status='PASS', legacy=identity, compact=identity)
        if arrays:
            reference['arrays'] = {'enthalpy_j': 'e'*64}
        self.reference.write_text(json.dumps(reference), encoding='utf8')

    def run_child(self, workers=8, name='arm-0.json', **scenario):
        SCENARIO.clear()
        SCENARIO.update(scenario)
        sys.modules.pop(PAR_NAME, None)
        out = self.tmp/name
        with contextlib.redirect_stdout(io.StringIO()):
            H4.child(self.layout, out, workers, self.reference)
        return out, json.loads(out.read_text(encoding='utf8'))['h4']

    def test_complete_arm_is_identical_and_passes_read_arm_and_verdict(self):
        out, h4 = self.run_child()
        self.assertEqual((h4['identical'], h4['differing_from_reference'], h4['workers_configured'],
                          h4['module_default_workers'], h4['minimum_faces']), (True, [], 8, 6, 16))
        self.assertEqual([(call['configured'], call['workers']) for call in h4['calls']], [(8, 8), (8, 0)])
        self.assertEqual((h4['hooks_before'], h4['hooks_after']), (HOOKS, HOOKS))
        self.assertEqual(h4['reference_sha256'], sha256(self.reference.read_bytes()).hexdigest())
        arm = {'arm': 0, 'workers': 8, 'exit_code': 0}
        self.assertIsNone(H4._read_arm(arm, out))
        summary = dict(counts=[8], arms=[arm], layout_sha256_before='a', layout_sha256_after='a',
                       reference_sha256='r', reference_sha256_after='r')
        self.assertEqual(H4._verdict(summary), (0, [], []))

    def test_a_none_identity_is_a_difference_even_when_the_reference_has_none(self):
        self.write_reference(result_id=None)
        out, h4 = self.run_child(result_id=None)
        self.assertEqual((h4['identical'], h4['differing_from_reference']), (False, ['legacy.result_id', 'compact.result_id']))

    def test_reference_arrays_absent_or_different_are_not_identical(self):
        self.assertEqual(self.run_child(arrays={'enthalpy_j': 'f'*64})[1]['differing_from_reference'], ['arrays'])
        self.write_reference(arrays=False)
        self.assertEqual(self.run_child(name='arm-1.json')[1]['differing_from_reference'], ['arrays'])

    def test_control_that_does_not_pass_is_not_identical(self):
        self.assertFalse(self.run_child(status='DIFFERS')[1]['identical'])

    def test_existing_output_or_a_module_from_elsewhere_refuses(self):
        (self.tmp/'arm-0.json').write_text('kept', encoding='utf8')
        with self.assertRaises(SystemExit):
            H4.child(self.layout, self.tmp/'arm-0.json', 8, self.reference)
        elsewhere = self.tmp/'elsewhere'
        elsewhere.mkdir()
        (elsewhere/(PAR_NAME+'.py')).write_text(FAKE_PAR, encoding='utf8')
        empty = self.tmp/'empty'
        empty.mkdir()
        (self.layout/'control.json').write_text(json.dumps(dict(paths=[str(empty)])), encoding='utf8')
        sys.path.insert(0, str(elsewhere))
        sys.modules.pop(PAR_NAME, None)
        with self.assertRaises(SystemExit) as refused:
            H4.child(self.layout, self.tmp/'arm-1.json', 8, self.reference)
        self.assertIn('did not load from the layout', str(refused.exception))


# --------------------------------------------------------------- run, through its real loop with stand-in children
FAKE_CHILD = '''import json, os, sys, time
from pathlib import Path
mode, layout, out, count, reference = sys.argv[1:6]
count, arm = int(count), int(Path(out).stem.split('-')[1])
scenario = json.loads(os.environ.get('H4_FAKE', '{}')).get(str(arm), {})
if scenario.get('mutate_layout'):
    (Path(layout)/'planted.txt').write_text('changed')
if scenario.get('mutate_reference'):
    Path(reference).write_text(Path(reference).read_text()+' ')
calls = [dict(faces=170, to_reconstruct=150, configured=count, workers=min(count, 150), collected=150, in_caller=0,
              fallback=None, ready_seconds=.1, seconds=1., worker_compute_seconds=5., parallel_efficiency=.8,
              worker_working_set_peak_max=1 << 26, worker_private_peak_max=1 << 25) for _ in range(2)]
calls[0].update(scenario.get('call', {}))
h4 = dict(identical=True, differing_from_reference=[], minimum_faces=16, calls=calls, totals=dict(calls=2, fallbacks=0),
          fallbacks=[], other_load_cpus=.5, module_sha256='0'*64, hooks_before={}, hooks_after={})
h4.update(scenario.get('h4', {}))
result = dict(status='PASS', legacy=dict(seconds=1.5), compact=dict(seconds=1.25), elapsed_seconds=10.,
              peak_working_set_bytes=1 << 28, h4=h4)
for path in scenario.get('drop', []):
    node, parts = result, path.split('.')
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    del node[parts[-1]]
if not scenario.get('no_out'):
    with open(out, 'x') as handle:
        json.dump(result, handle)
time.sleep(.3)
print('stand-in child', arm, count, flush=True)
sys.exit(scenario.get('exit', 0))
'''


class Run(Temp):
    def setUp(self):
        super().setUp()
        self.layout = self.tmp/'layout'
        (self.layout/'helpers').mkdir(parents=True)
        (self.layout/'control.json').write_text('{}', encoding='utf8')
        (self.layout/'helpers'/'module.py').write_text('x = 1\n', encoding='utf8')
        self.reference = self.tmp/'reference.json'
        self.reference.write_text('{"status": "PASS"}', encoding='utf8')
        self.fake = self.tmp/'fake_child.py'
        self.fake.write_text(FAKE_CHILD, encoding='utf8')
        self.started = []
        self.runs = 0

    def popen(self, command, **kwargs):
        self.assertEqual((Path(command[2]), command[3]), (H4_FILE, 'child'))      # the h4 child, replaced here
        self.started.append(command[4:])
        return subprocess.Popen([command[0], '-B', str(self.fake), *command[3:]], **kwargs)

    def sweep(self, counts=(6, 8), scenario=None, gate=(True, 0, 20*GIB)):
        self.runs += 1
        outdir = self.tmp/('out-%d' % self.runs)
        stand_in = SimpleNamespace(Popen=self.popen, STDOUT=subprocess.STDOUT)
        with mock.patch.object(H4, 'subprocess', stand_in), mock.patch.object(H4, '_gate', lambda: gate), \
                mock.patch.dict(os.environ, H4_FAKE=json.dumps(scenario or {})), \
                contextlib.redirect_stdout(io.StringIO()):
            status = H4.run(self.layout, outdir, self.reference, list(counts))
        summary = json.loads((outdir/'summary.json').read_text(encoding='utf8'))
        self.assertEqual((summary['exit_status'], summary['counts']), (status, list(counts)))
        return status, summary

    def test_complete_sweep_exits_0_and_records_each_gate_decision_and_call(self):
        status, summary = self.sweep((6, 8, 6))
        self.assertEqual((status, summary['verdict'], summary['failures'], summary['workers_reduced']), (0, 'PASS', [], []))
        self.assertEqual(len(summary['arms']), 3)
        for arm, count in zip(summary['arms'], (6, 8, 6), strict=True):
            self.assertEqual(arm['start_gate'], dict(passed=True, required_available_bytes=10*GIB,
                                                     available_bytes=20*GIB, waited_seconds=0))
            self.assertEqual(arm['exit_code'], 0)
            self.assertEqual({(c['configured'], c['workers'], c['expected_workers'], c['fallback'], c['as_configured'])
                              for c in arm['calls']}, {(count, count, count, None, True)})
            self.assertGreater(arm['tree_working_set_peak_sampled'], 0)
        self.assertEqual(summary['reference_sha256'], sha256(self.reference.read_bytes()).hexdigest())
        self.assertEqual(summary['reference_sha256'], summary['reference_sha256_after'])
        self.assertEqual(summary['layout_sha256_before'], summary['layout_sha256_after'])

    def test_a_failed_or_silent_child_stops_the_sweep_with_exit_1(self):
        status, summary = self.sweep((6, 8, 6), {'1': dict(exit=1)})
        self.assertEqual((status, len(summary['arms']), summary['arms'][1]['stopped']),
                         (1, 2, 'the arm did not complete; see its log'))
        self.assertIn('2 of 3 arms ran', summary['failures'])
        self.assertEqual(self.sweep((6,), {'0': dict(no_out=True)})[0], 1)

    def test_an_arm_not_identical_exits_1_after_every_arm(self):
        status, summary = self.sweep((6, 8), {'0': dict(h4=dict(identical=False, differing_from_reference=['arrays']))})
        self.assertEqual((status, len(summary['arms'])), (1, 2))

    def test_a_missing_or_none_summary_field_exits_1(self):
        for drop in ('h4.minimum_faces', 'elapsed_seconds', 'h4.calls.0.worker_private_peak_max', 'h4.totals',
                     'h4.differing_from_reference', 'legacy'):
            status, summary = self.sweep((6,), {'0': dict(drop=[drop])})
            self.assertEqual(status, 1, drop)
            self.assertIn('incomplete', summary['arms'][0]['stopped'])
        self.assertEqual(self.sweep((6,), {'0': dict(call=dict(workers=None))})[0], 1)

    def test_layout_or_reference_changed_during_the_run_exits_1(self):
        status, summary = self.sweep((6,), {'0': dict(mutate_layout=True)})
        self.assertEqual(status, 1)
        self.assertIn('the layout changed during the run (or was not digested)', summary['failures'])
        status, summary = self.sweep((6,), {'0': dict(mutate_reference=True)})
        self.assertEqual(status, 1)
        self.assertIn('the reference changed during the run (or was not digested)', summary['failures'])

    def test_count_set_otherwise_or_a_call_unrecorded_exits_1(self):
        self.assertEqual(self.sweep((6,), {'0': dict(call=dict(configured=8))})[0], 1)
        self.assertEqual(self.sweep((6,), {'0': dict(h4=dict(totals=dict(calls=17, fallbacks=0)))})[0], 1)

    def test_reduced_workers_or_a_fallback_exit_3(self):
        status, summary = self.sweep((6, 8), {'1': dict(call=dict(workers=4))})
        self.assertEqual((status, summary['verdict'], summary['failures']), (3, 'WORKERS_REDUCED', []))
        self.assertEqual(summary['workers_reduced'], ['arm 1 (8 workers) call 0: 4 workers used, 8 expected, fallback None'])
        self.assertEqual(self.sweep((6,), {'0': dict(call=dict(fallback='a worker failed'))})[0], 3)

    def test_gate_refusal_records_the_decision_starts_no_child_and_exits_1(self):
        status, summary = self.sweep((6, 8), gate=(False, 600, 9*GIB))
        self.assertEqual((status, len(summary['arms']), self.started), (1, 1, []))
        arm = summary['arms'][0]
        self.assertEqual(arm['start_gate'], dict(passed=False, required_available_bytes=10*GIB,
                                                 available_bytes=9*GIB, waited_seconds=600))
        self.assertEqual(arm['stopped'], 'start gate: under 10 GiB available for 10 minutes')

    def test_refusals_before_anything_runs(self):
        stand_in = SimpleNamespace(Popen=self.popen, STDOUT=subprocess.STDOUT)
        gates = []
        with mock.patch.object(H4, 'subprocess', stand_in), mock.patch.object(H4, '_gate', lambda: gates.append(1)):
            with self.assertRaises(SystemExit):
                H4.run(self.layout, self.tmp/'out-a', self.reference, [])
            with self.assertRaises(SystemExit):
                H4.run(self.tmp/'no-layout', self.tmp/'out-b', self.reference, [6])
            (self.tmp/'out-c').mkdir()
            with self.assertRaises(FileExistsError):
                H4.run(self.layout, self.tmp/'out-c', self.reference, [6])
        self.assertEqual((self.started, gates, list((self.tmp/'out-c').iterdir())), ([], [], []))
        self.assertFalse((self.tmp/'out-a').exists() or (self.tmp/'out-b').exists())


class CommandLine(Temp):
    def h4(self, *args, seed='0'):
        env = dict(os.environ)
        env.pop('PYTHONHASHSEED', None)
        if seed is not None:
            env['PYTHONHASHSEED'] = seed
        return subprocess.run([sys.executable, '-B', str(H4_FILE), *map(str, args)], capture_output=True, text=True,
                              env=env, timeout=120)

    def test_refuses_without_the_hash_seed_or_a_layout_before_any_child(self):
        out = self.tmp/'out'
        done = self.h4('run', self.tmp, out, self.tmp/'reference.json', 6, seed=None)
        self.assertEqual(done.returncode, 1)
        self.assertIn('set PYTHONHASHSEED=0', done.stderr)
        done = self.h4('run', self.tmp/'no-layout', out, self.tmp/'reference.json', 6)
        self.assertEqual(done.returncode, 1)
        self.assertIn('no layout', done.stderr)
        self.assertFalse(out.exists())

    def test_the_exit_status_is_the_verdict(self):
        for status in (0, 1, 3):
            argv = ['h4_heat_workers.py', 'run', str(self.tmp), str(self.tmp/'out'), str(self.tmp/'r.json'), '6', '8']
            with mock.patch.object(H4, 'run', return_value=status) as run, mock.patch.object(sys, 'argv', argv), \
                    mock.patch.object(sys, 'flags', SimpleNamespace(hash_randomization=0)):
                with self.assertRaises(SystemExit) as stop:
                    H4.main()
            self.assertEqual(stop.exception.code, status)
            self.assertEqual(run.call_args.args[3], [6, 8])


if __name__ == '__main__':
    unittest.main(verbosity=1)
