"""Pinned independent temporal oracle and recipe isolation, no old slow BE runs."""
from copy import deepcopy
from dataclasses import asdict
import json
import unittest
from unittest.mock import patch

from . import binding, experiments as e


class ExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = binding.load()
        cls.args = e.fixture_arguments(cls.bundle,'fixture005')
        cls.result = cls.bundle.solver.advance(**cls.args)
        cls.warm_args = e.fixture_arguments(cls.bundle,'fixture025')
        cls.warm_result = cls.bundle.solver.advance(**cls.warm_args)

    def test_default_is_exact_retained_reference(self):
        rows = e.verification_recipes(self.bundle)
        self.assertEqual(set(rows), {'default','strict-cap-120','strict-cap-60','strict-cap-30'})
        self.assertEqual(rows['default'],self.bundle.reference.recipe())

    def test_only_declared_strict_precision_and_method_changes(self):
        rows = e.verification_recipes(self.bundle)
        base = rows['default']
        for cap in (120,60,30):
            row = rows['strict-cap-'+str(cap)]
            expected = deepcopy(base)
            expected['physical_recipe']['coupling_controls'].update(initial_dt_seconds=cap,max_dt_seconds=cap,min_dt_seconds=1)
            expected['physical_recipe']['water_controls'].update(**e.STRICT_ACCURACY,
                integration_method='SDIRK2',min_dt_s=1e-14,max_steps=10000)
            self.assertEqual(row,expected)
            # The actual private scientific parser must consume the method.
            model = self.bundle.pipeline.parse(row,self.bundle.source_sha256)
            self.assertEqual(model.physical.water_controls.integration_method,'SDIRK2')

    def test_recipes_share_no_mutable_state(self):
        rows = e.verification_recipes(self.bundle)
        rows['strict-cap-120']['physical_recipe']['cells'].clear()
        self.assertTrue(rows['strict-cap-60']['physical_recipe']['cells'])
        self.assertEqual(rows['default'],self.bundle.reference.recipe())

    def test_external_evidence_pins_are_live_and_distinct(self):
        pins = e.test_data_bindings()
        self.assertGreaterEqual(len(pins),12)
        self.assertIn(str(e.TASK/e.DATA['multi'][0]),pins)
        self.assertIn(str(e.TASK/e.DATA['oracle_receipt'][0]),pins)
        self.assertTrue(all(len(s)==64 for s in pins.values()))

    def test_modified_external_pin_is_rejected(self):
        changed = deepcopy(e.DATA)
        changed['multi'] = (changed['multi'][0],'0'*64)
        with patch.object(e,'DATA',changed):
            with self.assertRaisesRegex(ValueError,'no silent repin'): e.load_fixture('fixture005')

    def test_fixture005_exact_multideposit_support_and_clock(self):
        actual = self.args
        frozen = e.load_fixture('fixture005')
        self.assertEqual(asdict(actual['column']),dict(frozen['column'],layers=tuple(frozen['column']['layers'])))
        self.assertEqual(actual['state'].head_m,tuple(frozen['state']['head_m']))
        self.assertEqual(actual['state'].elapsed_seconds,60)
        self.assertEqual(actual['forcing'].duration_seconds,60)
        self.assertEqual(len(actual['column'].layers),4)
        self.assertLess(actual['column'].layers[0].thickness_m,3e-8)
        self.assertLess(actual['column'].layers[1].thickness_m,3e-8)

    def test_single_fixture_retains_actual_thin_column_not_a_surrogate(self):
        actual = e.fixture_arguments(self.bundle,'standalone30')
        first = e._read('single')['first_actual_water_arguments']
        self.assertEqual(actual['state'].head_m,tuple(first['old']))
        self.assertEqual(actual['forcing'].duration_seconds,30)
        self.assertEqual(actual['state'].elapsed_seconds,0)
        self.assertEqual(len(actual['column'].layers),3)
        self.assertEqual(actual['column'].layers[0].thickness_m,first['column']['layers'][0]['thickness_m'])

    def test_fixture_and_floor_inputs_fail_closed(self):
        with self.assertRaises(ValueError): e.load_fixture('made-up')
        for value in (True,0,-1,1e-7,float('nan'),float('inf')):
            with self.assertRaises(ValueError): e.fixture_arguments(self.bundle,'fixture005',minimum_dt=value)

    def test_actual_multideposit_solver_completes_exact_interval(self):
        self.assertEqual(self.result['status'],'MODELLED',self.result.get('reason'))
        self.assertEqual(self.result['state'].elapsed_seconds,120)
        self.assertEqual(self.result['state'].column_sha256,self.args['state'].column_sha256)
        self.assertEqual(self.result['numerics']['controls']['integration_method'],'SDIRK2')
        self.assertEqual(self.result['numerics']['controls']['min_dt_s'],1e-14)
        self.assertLessEqual(self.result['numerics']['attempts'],10000)

    def test_actual_four_cell_endpoint_and_integrals_match_independent_radau(self):
        comparison = e.compare_fixture005_to_oracle(self.result,self.args['controls'])
        self.assertEqual(comparison['status'],'PASS',comparison)
        self.assertLess(comparison['paired_oracle_head_difference_m'],1e-12)
        self.assertLessEqual(comparison['maximum_cell_or_column_water_residual_m'],1e-10)
        json.dumps(comparison,allow_nan=False)

    def test_actual_warm_eleven_cell_solver_completes_without_flattening(self):
        self.assertEqual(self.warm_result['status'],'MODELLED',self.warm_result.get('reason'))
        self.assertEqual(len(self.warm_result['layers']),11)
        self.assertEqual(self.warm_result['state'].elapsed_seconds,150)
        self.assertEqual(self.warm_result['state'].column_sha256,self.warm_args['state'].column_sha256)
        self.assertEqual(self.warm_result['numerics']['controls']['integration_method'],'SDIRK2')

    def test_actual_warm_eleven_cell_matches_independent_gross_flow_oracle(self):
        comparison=e.compare_captured_to_oracle(self.warm_result,self.warm_args['controls'],fixture_name='fixture025')
        self.assertEqual(comparison['status'],'PASS',comparison)
        self.assertLess(comparison['paired_oracle_head_difference_m'],1e-12)
        self.assertLessEqual(comparison['maximum_cell_or_column_water_residual_m'],1e-10)

    def test_oracle_rejects_wrong_geometry_time_and_layer_support(self):
        for what in ('clock','geometry','layer'):
            wrong = e._plain(self.result)
            if what == 'clock': wrong['state']['elapsed_seconds'] += 1
            elif what == 'geometry': wrong['column_sha256'] = '0'*64
            else: wrong['layers'][0]['layer_id']='wrong'
            with self.assertRaisesRegex(ValueError,'exact captured'): e.compare_fixture005_to_oracle(wrong,self.args['controls'])

    def test_oracle_marks_failed_state_not_comparable(self):
        row = e.compare_fixture005_to_oracle({'status':'NUMERICAL_FAILURE','state':None,'ledger':None},self.args['controls'])
        self.assertEqual(row['status'],'NOT_COMPARABLE')

    def test_oracle_does_not_accept_inaccurate_or_nonfinite_candidate(self):
        wrong = e._plain(self.result); wrong['state']['head_m'][0] += .01
        self.assertEqual(e.compare_fixture005_to_oracle(wrong,self.args['controls'])['status'],'FAIL')
        wrong['state']['head_m'][0]=float('nan')
        with self.assertRaises(ValueError): e.compare_fixture005_to_oracle(wrong,self.args['controls'])

    def test_equal_opposing_spurious_transfers_cannot_hide_in_net_closure(self):
        wrong = e._plain(self.result)
        wrong['ledger']['face_downward_m'][1] += 1e-6
        wrong['ledger']['face_upward_m'][1] += 1e-6
        result = e.compare_fixture005_to_oracle(wrong,self.args['controls'])
        self.assertEqual(result['status'],'FAIL')
        self.assertLessEqual(result['components']['face_integrals_m']['maximum_error_ratio'],1)
        self.assertGreater(result['components']['face_downward_m']['maximum_error_ratio'],1)

    def test_failed_timing_is_not_a_speedup(self):
        old = dict(fixture='fixture005',inputs={'controls':{}},result={'status':'NUMERICAL_FAILURE'},elapsed_wall_seconds=1)
        new = deepcopy(old);new['result']['status']='MODELLED';new['elapsed_wall_seconds']=.01
        self.assertEqual(e.matched_timing(old,new)['status'],'NOT_COMPARABLE')

    def test_matched_time_formula_and_physical_input_guard(self):
        old = dict(fixture='fixture005',inputs={'controls':{}},result={'status':'MODELLED'},elapsed_wall_seconds=4)
        new = deepcopy(old);new['inputs']['controls']['integration_method']='SDIRK2';new['elapsed_wall_seconds']=1
        self.assertEqual(e.matched_timing(old,new)['percent_time_saved'],75)
        new['inputs']['controls']['relative_tolerance']=2
        with self.assertRaises(ValueError): e.matched_timing(old,new)


if __name__ == '__main__': unittest.main()
