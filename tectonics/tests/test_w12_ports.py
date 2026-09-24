"""W12 typed output boundary; small existing fixtures, no science campaign."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.workflow_ports import describe_workflow_output
from atlas_tectonics.w04_workflow import PreparedW04Support, W04SupportResult
from atlas_tectonics.w06_workflow import PreparedW06Workflow
from atlas_tectonics.extension_workflow import PreparedExtensionWorkflow
from atlas_tectonics.reuse import ExecutionContext
from test_w03_workflow import workflow_fixture, initialise
from test_w04_workflow import surface, POLICY as W04_POLICY
import test_w05_workflow as w05_fixture
from test_w07_workflow import make_workflow_fixture as w07_fixture
from test_w08_workflow import make_workflow_fixture as w08_fixture
from w06_workflow_case import route_fixture
from test_tectonic_history import make_history_fixture


class WorkflowPortTests(unittest.TestCase):
    def check_port(self, output, route):
        port = describe_workflow_output(output)
        self.assertEqual(port['route'], route)
        self.assertTrue(port['source_output_id'])
        self.assertFalse(port['dependencies']['export_is_restart'])
        self.assertTrue(port['dependencies']['native_ids'])
        self.assertEqual(set(port['fields']), set(port['field_specs']))
        self.assertTrue(port['fields'])
        json.dumps({k:v for k,v in port.items() if k != 'fields'}, allow_nan=False)
        for name, array in port['fields'].items():
            self.assertIs(type(array), np.ndarray)
            self.assertFalse(array.flags.writeable, name)
            self.assertTrue(np.isfinite(array).all(), name)
            spec = port['field_specs'][name]
            for key in ('units','support','owner','known'):
                self.assertIn(key,spec,name)
            self.assertEqual(list(array.shape),spec['shape'])
            if 'mask_field' in spec['known']:
                self.assertIn(spec['known']['mask_field'],port['fields'])
        return port

    def test_regional_and_columns_preserve_native_state_without_thermal_evaluation(self):
        regional = workflow_fixture(cells=2,length_m=2.)
        port = self.check_port(regional,'w01-w02-regional.v1')
        np.testing.assert_array_equal(port['fields']['material.thickness_m'],regional.material.thickness_m)
        self.assertEqual(port['descriptor']['native'],regional.descriptor())
        for name in regional.initial_samples.descriptor()['arrays']:
            np.testing.assert_array_equal(port['fields']['initial_samples.'+name],regional.initial_samples.array(name))
        columns = initialise(regional)
        with patch.object(type(columns),'thermal_diagnostics',side_effect=AssertionError('physics recomputed')):
            port = self.check_port(columns,'w03-columns.v1')
        np.testing.assert_array_equal(port['fields']['compaction.grain_volume_m3'],columns.compaction.grain_volume_m3)
        self.assertEqual(port['descriptor']['native']['transition'],columns.transition_record)

    def test_elastic_support_preserves_unknown_dry_surface_and_rejects_nonfinite(self):
        reference = initialise(workflow_fixture(cells=8))
        dry = surface(reference,volumes=np.r_[np.zeros(4),np.full(4,reference.reservoir_fluid_m3/4)])
        with PreparedW04Support(reference,dry,W04_POLICY) as plan:
            result = plan.solve(reference,dry)
        port = self.check_port(result,'w04-support.v1')
        np.testing.assert_array_equal(port['fields']['support.reservoir_surface_known'],[False]*4+[True]*4)
        last = port['field_specs']['support.values']['columns'][-1]
        self.assertEqual(last['known']['mask_field'],'support.reservoir_surface_known')
        np.testing.assert_array_equal(port['fields']['support.values'],result.values)
        corrupt = object.__new__(W04SupportResult)
        payload = result.values.copy();payload[0,0] = np.nan
        for name in ('result_id','_metadata','_wet'):
            object.__setattr__(corrupt,name,getattr(result,name))
        object.__setattr__(corrupt,'_payload',payload.tobytes())
        with self.assertRaisesRegex(TectonicsError,'nonfinite'):
            describe_workflow_output(corrupt)

    def test_extension_exports_material_exchanges_and_every_support_column(self):
        budget = WorkBudget(128<<20)
        helper = w05_fixture.W05WorkflowTests()
        with ExecutionContext('reference') as context:
            helper.context = context
            with helper.motion(budget) as motion:
                with PreparedExtensionWorkflow(motion,w05_fixture.POLICY,(0.,1.),budget=budget) as plan:
                    out = plan.run(through=0)
                    port = self.check_port(out,'w05-extension.v1')
                    np.testing.assert_array_equal(port['fields']['support.cell_means'],out.support.cell_means)
                    np.testing.assert_array_equal(port['fields']['state.exchange_m2'],out.state.exchange_m2)
                    self.assertEqual(len(port['field_specs']['support.cell_means']['columns']),10)

    def test_all_three_ocean_and_margin_output_forms(self):
        for route in ('constant','history','margin'):
            with self.subTest(route=route):
                budget = WorkBudget(128<<20)
                with route_fixture(route,budget=budget,cells=4) as (producer,policy,times):
                    with PreparedW06Workflow(producer,times,budget=budget,margin_policy=policy) as plan:
                        out = plan.run(through=0)
                        port = self.check_port(out,'w06-'+route+'.v1')
                if route == 'margin':
                    np.testing.assert_array_equal(port['fields']['state.thermal.mean_temperature_k'],out.state.thermal.mean_temperature_k)
                else:
                    np.testing.assert_array_equal(port['fields']['state.cell_values'],out.state.cell_values)
                    self.assertEqual(port['field_specs']['state.cell_values']['known']['mask_field'],'state.ocean_fraction')
                    self.assertEqual(port['field_specs']['state.heat_accounts_j']['units'][-1],'1')

    def test_all_three_regional_snapshot_routes_keep_all_native_fields(self):
        for route in ('steady','thermal','surface'):
            with self.subTest(route=route):
                with w07_fixture(route,nx=4,nz=4,thermal=route=='thermal') as plan:
                    out = plan.run(through=0)
                    port = self.check_port(out,'w07-'+route+'.v1')
                    expected = {'state.'+name for name in out.state.array_names}
                    expected.update('mechanics.'+name for name in out.mechanics.array_names)
                    self.assertEqual(set(port['fields']),expected)
                    for prefix,snapshot in (('state',out.state),('mechanics',out.mechanics)):
                        self.assertEqual(port['descriptor'][prefix]['native'],snapshot.descriptor())
                        for name in snapshot.array_names:
                            np.testing.assert_array_equal(port['fields'][prefix+'.'+name],snapshot.array(name))
                    if route == 'steady':
                        self.assertEqual(port['field_specs']['state.density_center_kg_m3']['units'],'kg/m3')
                        self.assertEqual(port['field_specs']['state.density_w_kg_m3']['units'],'kg/m3')
                        self.assertEqual(port['field_specs']['state.force_w_n_m3']['units'],'N/m3')
                        self.assertEqual(port['field_specs']['state.eta_center_pa_s']['units'],'Pa s')
                    elif route == 'surface':
                        self.assertEqual(port['field_specs']['mechanics.element_flux_m2_s']['units'],'m2/s')
                        self.assertEqual(port['field_specs']['mechanics.quadrature_weights_m2']['units'],'m2')
                        self.assertEqual(port['field_specs']['mechanics.strain_q_s_1']['units'],'1/s')

    def test_three_dated_history_routes_and_exact_standalone_results(self):
        for route,kind in (('underthrust','underthrust'),('w04','evolving-w04'),('regional','evolving-regional')):
            with self.subTest(route=route):
                with make_history_fixture(route,cells=4,regional_n=4) as history:
                    out = history.run(through=0)
                    port = self.check_port(out,'tectonic-history-'+kind+'.v1')
                    direct = self.check_port(out.result,'tectonic-'+kind+'.v1')
                    self.assertEqual(set(port['fields']),set(direct['fields']))
                    for name in direct['fields']:
                        np.testing.assert_array_equal(port['fields'][name],direct['fields'][name])
                    self.assertEqual(port['descriptor']['native'],out.descriptor())
                    if route == 'underthrust':
                        np.testing.assert_array_equal(port['fields']['result.enthalpy_known'],out.result.enthalpy_known)
                        self.assertEqual(port['field_specs']['result.enthalpy_j']['known']['mask_field'],'result.enthalpy_known')
                    elif route == 'w04':
                        self.assertEqual(port['field_specs']['result.absolute_values']['units'],['Pa','Pa','m','m'])

    def test_joined_regimes_keep_geometry_inventory_and_regional_view(self):
        with w08_fixture(parcels=2) as plan:
            out = plan.run(through=0)
            port = self.check_port(out,'w08-joined.v1')
            for i,polygon in enumerate(out.polygons):
                self.assertEqual(port['fields']['polygons.'+str(i)].tobytes(),polygon.wkb)
            np.testing.assert_array_equal(port['fields']['inventory.component_mass_kg'],out.inventory.component_mass_kg)
            np.testing.assert_array_equal(port['fields']['regional.enthalpy_j'],out.regional.enthalpy_j)
            self.assertEqual(port['descriptor']['native'],out.descriptor())

    def test_arbitrary_duck_types_and_unimplemented_results_refuse(self):
        for value in (None,{},SimpleNamespace(descriptor=lambda:{},result_id='made-up'),np.zeros(1)):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaisesRegex(TectonicsError,'unsupported exact'):
                    describe_workflow_output(value)


if __name__ == '__main__':
    unittest.main()
