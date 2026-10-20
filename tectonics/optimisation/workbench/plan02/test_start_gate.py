"""Tests for start_gate: the by-need start gate and the one source of the guarded runner's memory limits."""
import argparse
import json
import tempfile
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import start_gate as G

HERE = Path(__file__).resolve().parent

GIB = 1 << 30
KEY = {'step': 'runner', 'stage': 'root', 'interval': 1}
SEED_ZERO, SEED_RANDOM = SimpleNamespace(hash_randomization=0), SimpleNamespace(hash_randomization=1)


def decision(peak=4 * GIB):
    return G.decide(KEY, measured=[('stage-root.json sha256 aa', peak)])


class StartGateTests(unittest.TestCase):
    def test_in_run_guards_are_unchanged_and_there_is_no_blanket_start_gate(self):
        self.assertEqual((G.RSS_BYTES, G.FREE_BYTES, G.LOGICAL_BYTES, G.ALLOWANCE_BYTES),
                         (12 * GIB, 1 * GIB, 16 * GIB, 1 * GIB))
        self.assertFalse(hasattr(G, 'START_BYTES'))

    def test_gate_is_runq_mem_need_in_exact_bytes(self):
        # runq mem_need(gib) = round(gib*1.2 + 1.0 + 1.0, 1) GiB; in bytes the fifth is rounded up, never down.
        self.assertEqual(G.gate_bytes(5 * GIB), 8 * GIB)
        self.assertEqual(G.gate_bytes(10 * GIB), 14 * GIB)
        for peak, fifth in ((1, 1), (4, 1), (5, 1), (6, 2), (11, 3)):
            self.assertEqual(G.gate_bytes(peak), peak + fifth + 2 * GIB)

    def test_gate_needs_a_positive_integer_peak(self):
        for bad in (0, -GIB, 4.0 * GIB, True, None, '4'):
            with self.subTest(bad=bad), self.assertRaises(G.StartGateRefused):
                G.gate_bytes(bad)

    def test_no_record_and_no_booking_refuses(self):
        with self.assertRaisesRegex(G.StartGateRefused, 'no completed PASS record'):
            G.decide(KEY)
        with self.assertRaisesRegex(G.StartGateRefused, 'no completed PASS record'):
            G.decide(KEY, measured=[], booking=None)

    def test_the_largest_measured_peak_is_the_prediction(self):
        made = G.decide(KEY, measured=[('a', 3 * GIB), ('b', 7 * GIB), ('c', 5 * GIB)])
        self.assertEqual((made['predicted_peak_bytes'], made['basis'], made['gate_bytes']),
                         (7 * GIB, G.MEASURED, G.gate_bytes(7 * GIB)))
        self.assertEqual(made['measured'], [{'record': 'a', 'peak_bytes': 3 * GIB},
                                            {'record': 'b', 'peak_bytes': 7 * GIB},
                                            {'record': 'c', 'peak_bytes': 5 * GIB}])
        self.assertIsNone(made['booking'])

    def test_a_booking_below_the_measured_peak_uses_the_measured_one(self):
        made = G.decide(KEY, measured=[('a', 6 * GIB)], booking=(4 * GIB, 'declared'))
        self.assertEqual((made['predicted_peak_bytes'], made['basis']), (6 * GIB, G.MEASURED))
        self.assertEqual(made['booking'], {'bytes': 4 * GIB, 'basis': 'declared', 'used': False})

    def test_a_record_wins_over_a_higher_booking_as_in_runq(self):
        made = G.decide(KEY, measured=[('a', 6 * GIB)], booking=(9 * GIB, 'declared'))
        self.assertEqual((made['predicted_peak_bytes'], made['basis'], made['gate_bytes']),
                         (6 * GIB, G.MEASURED, G.gate_bytes(6 * GIB)))
        self.assertFalse(made['booking']['used'])

    def test_with_no_record_the_declared_booking_stands_in(self):
        made = G.decide(KEY, booking=(9 * GIB, 'IV1 runner smoke, doubled'))
        self.assertEqual((made['predicted_peak_bytes'], made['basis'], made['gate_bytes']),
                         (9 * GIB, G.BOOKING, G.gate_bytes(9 * GIB)))
        self.assertEqual(made['booking'], {'bytes': 9 * GIB, 'basis': 'IV1 runner smoke, doubled', 'used': True})
        self.assertEqual(made['measured'], [])

    def test_the_decision_records_its_rule_and_a_copy_of_its_key(self):
        key = dict(KEY)
        made = G.decide(key, measured=[('a', GIB)])
        key['interval'] = 2
        self.assertEqual(made['key'], KEY)
        self.assertEqual((made['schema'], made['margin'], made['free_floor_bytes'], made['allowance_bytes']),
                         (G.SCHEMA, '1/5', GIB, GIB))
        self.assertEqual(set(made), {'schema', 'key', 'predicted_peak_bytes', 'basis', 'measured', 'booking',
                                     'gate_bytes', 'margin', 'free_floor_bytes', 'allowance_bytes'})

    def test_malformed_inputs_refuse(self):
        calls = [dict(key={}, measured=[('a', GIB)]), dict(key=None, measured=[('a', GIB)]),
                 dict(key={1: 'x'}, measured=[('a', GIB)]), dict(key=KEY, measured=[('a', GIB), ('a', 2 * GIB)]),
                 dict(key=KEY, measured=[('', GIB)]), dict(key=KEY, measured=[('a', 0)]),
                 dict(key=KEY, measured=[('a', 1.0 * GIB)]), dict(key=KEY, measured=[('a', True)]),
                 dict(key=KEY, measured=[['a', GIB]]), dict(key=KEY, measured=[('a', GIB, 'x')]),
                 dict(key=KEY, booking=(0, 'x')), dict(key=KEY, booking=(GIB, '')),
                 dict(key=KEY, booking=(GIB, '   ')), dict(key=KEY, booking=[GIB, 'x']),
                 dict(key=KEY, booking=(GIB,)), dict(key=KEY, booking=(True, 'x')),
                 dict(key=KEY, measured=[('a', GIB)], booking=(GIB, ''))]
        for call in calls:
            arguments = dict(call)
            key = arguments.pop('key')
            with self.subTest(call=call), self.assertRaises(G.StartGateRefused):
                G.decide(key, **arguments)

    def test_admit_at_and_above_the_gate_records_the_start(self):
        made = decision()
        for available in (made['gate_bytes'], made['gate_bytes'] + 1, 64 * GIB):
            with self.subTest(available=available):
                self.assertEqual(G.admit(made, available, SEED_ZERO),
                                 dict(made, available_bytes=available, hash_randomization=0))
        self.assertNotIn('available_bytes', made)

    def test_a_gate_above_the_available_memory_refuses(self):
        made = decision()
        with self.assertRaisesRegex(G.StartGateRefused, 'start gate refused'):
            G.admit(made, made['gate_bytes'] - 1, SEED_ZERO)
        for bad in (None, float(made['gate_bytes']), True, str(made['gate_bytes'])):
            with self.subTest(bad=bad), self.assertRaises(G.StartGateRefused):
                G.admit(made, bad, SEED_ZERO)

    def test_admit_refuses_a_decision_that_differs_from_its_prediction(self):
        made = decision()
        for change in ({'gate_bytes': made['gate_bytes'] - 1}, {'gate_bytes': float(made['gate_bytes'])},
                       {'predicted_peak_bytes': made['predicted_peak_bytes'] - 1}, {'schema': 'x'},
                       {'basis': 'guess'}):
            with self.subTest(change=change), self.assertRaisesRegex(G.StartGateRefused, 'differs'):
                G.admit(dict(made, **change), 64 * GIB, SEED_ZERO)
        for bad in (None, [], 'x'):
            with self.subTest(bad=bad), self.assertRaises(G.StartGateRefused):
                G.admit(bad, 64 * GIB, SEED_ZERO)

    def test_admit_refuses_a_random_seed(self):
        made = decision()
        for flags in (SEED_RANDOM, SimpleNamespace()):
            with self.subTest(flags=flags), self.assertRaisesRegex(G.StartGateRefused, 'seed 0'):
                G.admit(made, 64 * GIB, flags)

    def test_admit_reads_the_interpreters_flags_by_default(self):
        made = decision()
        with mock.patch.object(G, 'sys', SimpleNamespace(flags=SEED_RANDOM)):
            with self.assertRaisesRegex(G.StartGateRefused, 'seed 0'):
                G.admit(made, 64 * GIB)
        with mock.patch.object(G, 'sys', SimpleNamespace(flags=SEED_ZERO)):
            self.assertEqual(G.admit(made, 64 * GIB)['hash_randomization'], 0)


def stage_record(stage='root', interval=0, status='ADOPTED', runner: object = 3 * GIB, reader: object = 2 * GIB,
                 **changes):
    """A launch_fresh_interval stage record, as written after its four steps (only the fields the gate reads).

    The peaks are typed as object because the refusal cases pass None, floats and text on purpose.
    """
    # As the guard samples them (private_heat_continuation_guard_r3): the parent's and the process tree's RSS.
    steps = [{'name': 'runner', 'ok': True, 'resources': {'sampled_peak_bytes': {'parent_rss': 1, 'process_tree_rss': runner}}},
             {'name': 'reader', 'ok': True, 'resources': {'sampled_peak_bytes': {'parent_rss': 1, 'process_tree_rss': reader}}},
             {'name': 'finalise', 'ok': True}, {'name': 'adopt', 'ok': True}]
    return dict({'schema': G.STAGE_SCHEMA, 'stage': stage, 'interval': interval, 'status': status, 'steps': steps},
                **changes)


def with_step(change):
    record = stage_record()
    change(record['steps'])
    return record


class StageRecordTests(unittest.TestCase):
    """Route (1): the launcher's stage records, the decision handed to each guarded child, the receipts' limits."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sg-', dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.folder, self.key = Path(self.temp.name), G.stage_key('root', 0)

    def write(self, name, value):
        path = self.folder/name
        path.write_bytes(value if type(value) is bytes else json.dumps(value).encode())
        return path

    def test_stage_key(self):
        self.assertEqual(G.stage_key('interval', 1), {'route': 'fresh-interval', 'stage': 'interval', 'interval': 1})
        for stage, interval in (('', 0), (None, 0), ('root', -1), ('root', True), ('root', 0.0), ('root', '0')):
            with self.assertRaises(G.StartGateRefused):
                G.stage_key(stage, interval)

    def test_a_completed_pass_gives_its_larger_guarded_peak_and_names_its_bytes(self):
        reader_larger = self.write('a.json', stage_record(runner=3 * GIB, reader=5 * GIB))
        runner_larger = self.write('b.json', stage_record(runner=7 * GIB, reader=2 * GIB))
        found = G.stage_peaks([reader_larger, runner_larger], self.key)
        self.assertEqual([peak for _, peak in found], [5 * GIB, 7 * GIB])
        self.assertEqual(found[0][0], '%s sha256=%s' % (reader_larger.resolve(),
                                                        sha256(reader_larger.read_bytes()).hexdigest()))
        self.assertEqual(G.stage_peaks([], self.key), [])

    def test_the_width_gate_stop_is_a_completed_pass(self):
        path = self.write('w.json', stage_record('interval', 1, status='ADOPTED_WIDTH_GATE_STOP_BEFORE_INTERVAL_2'))
        self.assertEqual(G.stage_peaks([path], G.stage_key('interval', 1))[0][1], 3 * GIB)

    def test_a_record_that_does_not_qualify_refuses_and_is_never_skipped(self):
        good = self.write('good.json', stage_record())
        cases = {
            'schema': stage_record(schema='atlas.private.fresh-interval-stage.r0'),
            'stage': stage_record(stage='interval'), 'interval': stage_record(interval=1),
            'interval_bool': stage_record(interval=False), 'preflight': stage_record(status='PREFLIGHT_PASSED'),
            'failed': stage_record(status='FAILED'), 'stopped': stage_record(status='STOPPED_BEFORE_ADVANCE_ROOT_PUBLISHED'),
            'runner_peak_missing': stage_record(runner=None), 'reader_peak_zero': stage_record(reader=0),
            'peak_bool': stage_record(runner=True), 'peak_float': stage_record(reader=2.0 * GIB),
            'peak_text': stage_record(reader='2147483648'),
            'step_not_ok': with_step(lambda steps: steps[2].update(ok=False)),
            'step_ok_truthy': with_step(lambda steps: steps[1].update(ok=1)),
            'step_missing': with_step(lambda steps: steps.pop(2)),
            'steps_reordered': with_step(lambda steps: steps.reverse()),
            'step_added': with_step(lambda steps: steps.append({'name': 'adopt', 'ok': True})),
            'resources_not_dict': with_step(lambda steps: steps[0].update(resources=[3 * GIB])),
            'resources_missing': with_step(lambda steps: steps[1].pop('resources')),
            'peak_not_a_tree_sample': with_step(lambda steps: steps[0]['resources'].update(sampled_peak_bytes=3 * GIB)),
            'tree_peak_missing': with_step(lambda steps: steps[1]['resources']['sampled_peak_bytes'].pop('process_tree_rss')),
            'steps_not_list': stage_record(steps={}), 'step_not_dict': with_step(lambda steps: steps.append(None)),
            'not_a_dict': [stage_record()], 'invalid_json': b'{', 'not_utf8': b'\xff\xfe{',
        }
        for name, value in cases.items():
            with self.subTest(name):
                with self.assertRaisesRegex(G.StartGateRefused, 'not a completed PASS record'):
                    G.stage_peaks([good, self.write(name+'.json', value)], self.key)
        with self.assertRaisesRegex(G.StartGateRefused, 'list of paths'):
            G.stage_peaks(str(good), self.key)
        with self.assertRaises(FileNotFoundError):
            G.stage_peaks([good, self.folder/'missing.json'], self.key)

    def test_records_win_a_booking_stands_in_and_neither_refuses(self):
        path = self.write('r.json', stage_record(runner=4 * GIB, reader=1 * GIB))
        made = G.stage_decision(self.key, records=[path], booking_bytes=9 * GIB, booking_basis='declared')
        self.assertEqual((made['predicted_peak_bytes'], made['basis'], made['booking']['used'], made['key']),
                         (4 * GIB, G.MEASURED, False, self.key))
        made = G.stage_decision(self.key, booking_bytes=3 * GIB, booking_basis='IV1 replay estimate')
        self.assertEqual((made['predicted_peak_bytes'], made['basis'], made['gate_bytes']),
                         (3 * GIB, G.BOOKING, G.gate_bytes(3 * GIB)))
        with self.assertRaisesRegex(G.StartGateRefused, 'no completed PASS record'):
            G.stage_decision(self.key)
        for booking_bytes, booking_basis in ((3 * GIB, None), (None, 'why')):
            with self.assertRaisesRegex(G.StartGateRefused, 'both'):
                G.stage_decision(self.key, booking_bytes=booking_bytes, booking_basis=booking_basis)
        with self.assertRaisesRegex(G.StartGateRefused, 'twice'):
            G.stage_decision(self.key, records=[path, path])

    def test_launch_options(self):
        parser = argparse.ArgumentParser()
        G.add_arguments(parser)
        args = parser.parse_args(['--peak-record', 'a.json', '--peak-record', 'b.json', '--booking-bytes', '5',
                                  '--booking-basis', 'why'])
        self.assertEqual((args.peak_records, args.booking_bytes, args.booking_basis),
                         ([Path('a.json'), Path('b.json')], 5, 'why'))
        args = parser.parse_args([])
        self.assertEqual((args.peak_records, args.booking_bytes, args.booking_basis), ([], None, None))

    def test_a_child_admits_its_launchers_decision_again(self):
        made = G.stage_decision(self.key, booking_bytes=2 * GIB, booking_basis='declared booking')
        text = G.encode(made)
        self.assertEqual(json.loads(text), made)
        self.assertEqual(G.child_admit(text, made['gate_bytes'], SEED_ZERO), G.admit(made, made['gate_bytes'], SEED_ZERO))
        with self.assertRaisesRegex(G.StartGateRefused, 'start gate refused'):
            G.child_admit(text, made['gate_bytes'] - 1, SEED_ZERO)
        with self.assertRaisesRegex(G.StartGateRefused, 'seed 0'):
            G.child_admit(text, 64 * GIB, SEED_RANDOM)
        for field, value in (('gate_bytes', made['gate_bytes'] - 1), ('predicted_peak_bytes', 1)):
            with self.assertRaisesRegex(G.StartGateRefused, 'differs'):
                G.child_admit(json.dumps(dict(made, **{field: value})), 64 * GIB, SEED_ZERO)
        for bad in (None, b'{}', '', '{', '[]', 'null'):
            with self.assertRaises(G.StartGateRefused):
                G.child_admit(bad, 64 * GIB, SEED_ZERO)

    def test_receipt_guard_limits_keep_their_fields_with_this_starts_gate(self):
        admitted = G.admit(G.stage_decision(self.key, booking_bytes=2 * GIB, booking_basis='b'), 64 * GIB, SEED_ZERO)
        self.assertEqual(G.guard_limits(admitted), {'rss_bytes': 12 * GIB, 'free_floor_bytes': GIB,
                                                    'start_available_bytes': G.gate_bytes(2 * GIB),
                                                    'logical_budget_bytes': 16 * GIB})


if __name__ == '__main__':
    unittest.main()
