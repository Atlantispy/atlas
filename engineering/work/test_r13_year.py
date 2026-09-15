"""Small calendar/checkpoint/persistence regressions, isolated from physics cost."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from work.generator_upgrade_r13 import year, storage


def fixture():
    return {'schema': year.SCHEMA, 'scenario_id': 'test', 'source_status': 'SYNTHETIC TEST',
            'evidence': 'Twelve explicitly one-second test months; not an Earth year.',
            'context': dict(zip(sorted(year.FRAME), ['test'] * len(year.FRAME))),
            'model': {'test': True}, 'initial': {'head_m': [0], 'temperature_k': [280], 'elapsed_seconds': 0},
            'calendar': {'calendar_id': 'test', 'month_durations_seconds': ['1'] * 12},
            'events': [{'event_id': f'm{i}', 'month_id': i, 'start_seconds_in_year': str(i-1),
                        'duration_seconds': '1', 'forcing': {'duration_s': 1.0},
                        'evidence': 'Explicit test interval', 'source_status': 'SYNTHETIC TEST'} for i in range(1, 13)],
            'controls': {}, 'joins': {'test': 'isolated orchestration, not a scientific model'}}


def advance(model, state, event, controls):
    final = {'elapsed_seconds': state['elapsed_seconds'] + event['duration_s'],
             'test_water_stock': state['test_water_stock'] + 1}
    return {'status': 'MODELLED', 'initial_state': deepcopy(state), 'final_state': final}


class SoilYearTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.patches = [patch.object(year.p, 'identity', return_value={'test_binding': True}),
                        patch.object(year.p, 'verify'),
                        patch.object(year.audit, 'event'),
                        patch.object(year.soil, 'initial_state', return_value={'elapsed_seconds': 0, 'test_water_stock': 1}),
                        patch.object(year.soil, 'advance', side_effect=advance)]
        self.mocks = [item.start() for item in self.patches]
        for item in self.patches:
            self.addCleanup(item.stop)

    def test_continuous_year_and_exact_saved_prefix_replay(self):
        full = year.run(self.spec)['scientific']
        stopped = year.run(self.spec, stop_after=4)['scientific']
        resumed = year.run(self.spec, resume=stopped['checkpoint'])['scientific']
        self.assertEqual(full, resumed)
        self.assertEqual(full['final_state']['test_water_stock'], 13)
        self.assertEqual(stopped['last_complete_event_state']['test_water_stock'], 5)
        self.assertIsNone(stopped['final_state'])
        self.assertFalse(full['held_initial_water'])
        self.assertFalse(full['whole_diadem_year_verified'])

    def cache(self, directory, *, max_bytes=256*1024*1024):
        from work.generator_runtime_r12.store import Store
        return Store(Path(directory)/'c', year.p.sha(year.p.identity()), max_bytes=max_bytes)

    def test_authenticated_prefix_skips_all_previously_completed_solves(self):
        with tempfile.TemporaryDirectory(prefix='r13-c-') as directory:
            cache = self.cache(directory)
            first = year.run(self.spec, stop_after=7, store=cache)
            self.mocks[-1].reset_mock()
            second = year.run(self.spec, resume=first['scientific']['checkpoint'], store=cache)
            self.assertEqual(self.mocks[-1].call_count, 5)
            self.assertEqual(second['execution']['reused_events'], 7)
            expected = year.run(self.spec)['scientific']
            self.assertEqual(second['scientific'], expected)
            self.mocks[-1].reset_mock()
            again = year.run(self.spec, resume=second['scientific']['checkpoint'], store=cache)
            self.mocks[-1].assert_not_called()
            self.assertEqual(again['scientific'], expected)

    def test_authentication_rejects_rehashed_history_without_replay(self):
        with tempfile.TemporaryDirectory(prefix='r13-c-') as directory:
            cache = self.cache(directory)
            cp = year.run(self.spec, stop_after=1, store=cache)['scientific']['checkpoint']
            cp['state']['accepted_events'][0]['result']['invented_diagnostic'] = 'not computed'
            cp['state_sha256'] = year.p.sha(cp['state'])
            self.mocks[-1].reset_mock()
            with self.assertRaisesRegex(ValueError, 'differs from authenticated result'):
                year.run(self.spec, resume=cp, store=cache)
            self.mocks[-1].assert_not_called()

    def test_missing_certificate_and_full_cache_are_explicit_replay_only(self):
        with tempfile.TemporaryDirectory(prefix='r13-c-') as directory:
            cache = self.cache(directory, max_bytes=33)
            stopped = year.run(self.spec, stop_after=1, store=cache)
            self.assertIn('full', stopped['execution']['cache_warnings'][0])
            cp = stopped['scientific']['checkpoint']
            self.mocks[-1].reset_mock()
            with self.assertRaisesRegex(ValueError, 'no authenticated certificate'):
                year.run(self.spec, resume=cp, store=cache)
            self.mocks[-1].assert_not_called()
            self.assertEqual(year.run(self.spec, resume=cp)['scientific']['completed_events'], 12)

    def test_changed_source_cache_namespace_rejected_before_solving(self):
        with tempfile.TemporaryDirectory(prefix='r13-c-') as directory:
            cache = self.cache(directory)
            self.mocks[0].return_value = {'test_binding': 'changed'}
            with self.assertRaisesRegex(ValueError, 'exact source/runtime namespace'):
                year.run(self.spec, store=cache)
            self.mocks[-1].assert_not_called()

    def test_checkpoint_precedes_progress_and_survives_later_solver_exception(self):
        saved = []
        def fail_on_third(model, state, event, controls):
            if state['elapsed_seconds'] == 2:
                raise RuntimeError('interruption')
            return advance(model, state, event, controls)
        self.mocks[-1].side_effect = fail_on_third
        with patch('builtins.print') as progress:
            def commit(value):
                self.assertEqual(progress.call_count, max(0, value['scientific']['completed_events']-1))
                saved.append(value)
            with self.assertRaisesRegex(RuntimeError, 'interruption'):
                year.run(self.spec, progress=True, on_checkpoint=commit)
        self.assertEqual([value['scientific']['completed_events'] for value in saved], [0, 1, 2])
        self.assertEqual(saved[-1]['scientific']['checkpoint']['state']['continuing_state']['test_water_stock'], 3)

    def test_failed_audit_never_certifies_result(self):
        with tempfile.TemporaryDirectory(prefix='r13-c-') as directory:
            cache = self.cache(directory)
            self.mocks[2].side_effect = ValueError('bad balance')
            result = year.run(self.spec, store=cache)
            self.assertEqual(result['scientific']['completed_events'], 0)
            self.assertEqual(cache.stats['writes'], 0)

    def test_real_journal_recovers_interrupted_prefix_without_recomputation(self):
        with tempfile.TemporaryDirectory(prefix='r13-j-') as directory:
            root = Path(directory)/'r'
            cache = self.cache(directory)
            journal = storage.Journal(root, self.spec)
            def interrupted(model, state, event, controls):
                if state['elapsed_seconds'] == 2:
                    raise RuntimeError('simulated process interruption')
                return advance(model, state, event, controls)
            self.mocks[-1].side_effect = interrupted
            with self.assertRaisesRegex(RuntimeError, 'interruption'):
                year.run(self.spec, store=cache, on_checkpoint=journal.commit)
            saved = storage.load(root)
            self.assertEqual(saved['scientific']['completed_events'], 2)
            self.mocks[-1].side_effect = advance
            self.mocks[-1].reset_mock()
            successor = storage.Journal(Path(directory)/'s', self.spec)
            actual = year.run(self.spec, store=cache, resume=saved['scientific']['checkpoint'],
                              on_checkpoint=successor.commit)
            self.assertEqual(self.mocks[-1].call_count, 10)
            self.assertEqual(storage.load(successor.root), {'recipe': self.spec, **actual})
            self.assertEqual(actual['scientific'], year.run(self.spec)['scientific'])

    def test_unknown_stops_affected_suffix(self):
        self.spec['events'][4]['forcing']['unknown_temperature'] = None
        result = year.run(self.spec)['scientific']
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(result['completed_events'], 4)
        self.assertIsNone(result['final_state'])
        self.assertEqual(self.mocks[-1].call_count, 4)

    def test_optional_progress_reports_verified_events_without_changing_science(self):
        expected = year.run(self.spec)['scientific']
        with patch('builtins.print') as report:
            actual = year.run(self.spec, progress=True)['scientific']
        self.assertEqual(actual, expected)
        self.assertEqual(report.call_count, 12)
        self.assertEqual(json.loads(report.call_args.args[0])['completed_events'], 12)
        self.mocks[2].side_effect = ValueError('rejected event')
        with patch('builtins.print') as report:
            self.assertEqual(year.run(self.spec, progress=True)['scientific']['completed_events'], 0)
            report.assert_not_called()

    def test_numerical_failure_does_not_commit_partial_event(self):
        self.mocks[-1].side_effect = [advance(None, {'elapsed_seconds': 0, 'test_water_stock': 1}, {'duration_s': 1}, {}),
                                    {'status': 'NUMERICAL_FAILURE', 'last_accepted_state': {'trial': True}}]
        result = year.run(self.spec)['scientific']
        self.assertEqual(result['completed_events'], 1)
        self.assertEqual(result['checkpoint']['state']['continuing_state']['test_water_stock'], 2)
        self.assertIsNone(result['final_state'])
        self.assertEqual(result['reason']['event_id'], 'm2')

    def test_rehashed_forged_state_is_not_restart_authority(self):
        checkpoint = year.run(self.spec, stop_after=2)['scientific']['checkpoint']
        checkpoint['state']['continuing_state']['test_water_stock'] = 99
        checkpoint['state_sha256'] = year.p.sha(checkpoint['state'])
        with self.assertRaisesRegex(ValueError, 'actual coupled event replay'):
            year.run(self.spec, resume=checkpoint)

    def test_independent_account_failure_preserves_only_verified_prefix(self):
        self.mocks[2].side_effect = [None, ValueError('independent balance differs')]
        result = year.run(self.spec)['scientific']
        self.assertEqual(result['status'], 'NUMERICAL_FAILURE')
        self.assertEqual(result['completed_events'], 1)
        self.assertEqual(result['checkpoint']['state']['continuing_state']['test_water_stock'], 2)
        self.assertIsNone(result['final_state'])
        self.assertEqual(result['reason']['failure']['status'], 'REJECTED_BY_INDEPENDENT_ACCOUNT')
        self.assertIn('independent balance differs', result['reason']['failure']['reason'])

    def test_wrong_producer_initial_state_cannot_break_lineage(self):
        def wrong(model, state, event, controls):
            result = advance(model, state, event, controls)
            result['initial_state']['test_water_stock'] = 99
            return result
        self.mocks[-1].side_effect = wrong
        with self.assertRaisesRegex(ValueError, 'initial state differs from accepted prefix'):
            year.run(self.spec)

    def test_calendar_gap_duplicate_and_binding_rejected(self):
        for kind in ('gap', 'duplicate', 'month', 'duration', 'frame'):
            spec = deepcopy(self.spec)
            if kind == 'gap': spec['events'][1]['start_seconds_in_year'] = 9
            elif kind == 'duplicate': spec['events'][1]['event_id'] = 'm1'
            elif kind == 'month': spec['events'][1]['month_id'] = 1
            elif kind == 'duration': spec['events'][1]['forcing']['duration_s'] = 2
            else: spec['context']['calendar_id'] = 'wrong'
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                year.run(spec)
        self.assertEqual(self.mocks[-1].call_count, 0)

    def test_partitioned_readback_and_source_hash_reject_tampering(self):
        result = year.run(self.spec)
        with tempfile.TemporaryDirectory(prefix='r13-year-') as directory:
            output = Path(directory) / 'r'
            storage.save(output, self.spec, result)
            self.assertEqual(storage.load(output), {'recipe': self.spec, **result})
            with self.assertRaisesRegex(ValueError, 'existing outputs preserved'):
                storage.save(output, self.spec, result)
            path = output / 'e0000.json'
            path.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'no silent rebind'):
                storage.load(output)

    def test_duplicate_nonfinite_and_relative_input_rejected(self):
        with tempfile.TemporaryDirectory(prefix='r13-json-') as directory:
            path = Path(directory) / 'input.json'
            for raw in ('{"a":1,"a":2}', '{"a":NaN}'):
                path.write_text(raw, encoding='utf-8')
                with self.assertRaises(ValueError):
                    storage.read_json(path)
        with self.assertRaises(ValueError):
            storage.read_json(Path('relative.json'))


class IndependentAccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from work.test_r13_soil import fixture as physics_fixture
        cls.model, cls.forcing, cls.controls = physics_fixture()
        cls.forcing['surface_water_flux_m_s'] = 1e-8
        cls.state = year.soil.initial_state(cls.model, [-1.0], [275.0])
        cls.result = year.soil.advance(cls.model, cls.state, cls.forcing, cls.controls)
        if cls.result['status'] != 'MODELLED':
            raise ValueError('real audit fixture did not complete')

    def test_actual_event_accounts_pass(self):
        result = year.audit.event(self.model, self.forcing, self.result, self.controls)
        self.assertLessEqual(abs(result['water_residual_m']), self.controls['water_atol_m'])

    def test_each_public_aggregate_rejects_tampering(self):
        keys = ('initial_storage_m', 'final_storage_m', 'storage_change_m',
                'initial_enthalpy_j_m2', 'final_enthalpy_j_m2', 'enthalpy_change_j_m2',
                'root_withdrawal_m', 'root_enthalpy_j_m2', 'water_residual_m',
                'energy_residual_j_m2', 'infiltration_m', 'surface_exfiltration_m',
                'bottom_downward_m', 'bottom_upward_m', 'rain_excess_runoff_m',
                'rain_excess_enthalpy_j_m2', 'surface_input_representation_residual_m')
        for key in keys:
            value = deepcopy(self.result)
            value['ledger'][key] += 1.0
            with self.subTest(key=key), self.assertRaises(ValueError):
                year.audit.event(self.model, self.forcing, value, self.controls)

    def test_layer_fields_reject_tampering(self):
        for key in ('thickness_m', 'water_change_m', 'enthalpy_change_j_m2'):
            value = deepcopy(self.result)
            value['ledger']['layers'][0][key] += 1.0
            with self.subTest(key=key), self.assertRaises(ValueError):
                year.audit.event(self.model, self.forcing, value, self.controls)

    def test_temperature_offset_rejects_inconsistent_readable_state(self):
        value = deepcopy(self.result)
        value['final_state']['temperature_offset_k'][0] += 1e-6
        with self.assertRaisesRegex(ValueError, 'retained offset'):
            year.audit.event(self.model, self.forcing, value, self.controls)


if __name__ == '__main__':
    unittest.main()
