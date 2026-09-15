"""Actual R6 CLI/receipt and explicit model-selection boundary checks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

import shoreline_workflow as w
from test_shoreline_workflow import recipe,endpoint_recipe


def physical_recipe():
    r=recipe();r['scenario_id']='r6_actual_mixed_physical_bridges'
    r['state'].update(shape=[2,2],cell_area_m2=[1.]*4,bedrock_m=[3.,2.,2.,1.],
        bed_solid_m3=[.2]*4,liquid_m3=[0.]*4,suspended_solid_m3=[0.]*4)
    r['forcing'].update(steps=1,dt_years=.001,external_outlets=[3],runoff_m_year=[.1,0.,.4,0.],
        incoming_liquid_m3_year=[.3,0.,0.,0.],incoming_solid_m3_year=[.01,0.,0.,0.],
        diffusivity_m2_year=[.001]*4,rock_k_per_year=[.001]*4,sediment_k_per_year=[.001]*4,
        settling_m_year=.001,critical_gradient=[3.]*4,erosion_reference_runoff_m_year=.1)
    return r


class R6WorkflowTests(unittest.TestCase):
    def test_old_schema_cannot_silently_select_new_physics(self):
        r=recipe();r['schema']='diadem.terrain.shoreline.recipe.r5'
        with self.assertRaisesRegex(ValueError,'explicit synthetic R7'):w.validate(r)

    def test_both_new_choices_are_required_even_when_legacy_none(self):
        for name in ('critical_gradient','erosion_reference_runoff_m_year'):
            r=recipe();r['forcing'].pop(name)
            with self.subTest(name=name),self.assertRaises(ValueError):w.validate(r)

    def test_invalid_choices_reject_before_driver_execution(self):
        for name,value in (('critical_gradient',[0.,1.]),('critical_gradient',[1.]),
                           ('erosion_reference_runoff_m_year',0.),('erosion_reference_runoff_m_year',True)):
            r=recipe();r['forcing'][name]=value
            with self.subTest(name=name,value=value),patch.object(w.driver,'advance',side_effect=AssertionError('must not generate')):
                with self.assertRaises(ValueError):w.validate(r)

    def test_actual_cli_commit_readback_reuse_and_uncertified_failure(self):
        # Public non-overwriting output retained as audit evidence; no test
        # patches output guards or numerical producers in this test.
        token=uuid.uuid4().hex
        output=w.OUTPUT_ROOT/('scientific-test-'+token)
        with tempfile.TemporaryDirectory(prefix='r6-cli-input-') as temporary:
            input_path=Path(temporary)/'recipe.json'
            r=physical_recipe();input_path.write_text(json.dumps(r),encoding='utf-8')
            def cli(destination,resume=False):
                args=[sys.executable,'-B',str(w.HERE/'shoreline_workflow.py'),
                      '--recipe',str(input_path),'--output',str(destination)]
                if resume:args.append('--resume')
                return subprocess.run(args,capture_output=True,text=True,timeout=120)
            first=cli(output);self.assertEqual(first.returncode,0,first.stderr)
            first_message=json.loads(first.stdout)
            self.assertEqual(first_message['status'],'COMMITTED_SHORELINE_REFERENCE')
            result=json.loads((output/'RESULT.json').read_text())
            selection=result['model_selection']
            self.assertEqual(selection['hillslope_law'],'ROERING_NONLINEAR')
            self.assertEqual(selection['erosion_reference_runoff_m_year'],.1)
            self.assertEqual(selection['critical_gradient'],[3.]*4)
            self.assertEqual(selection['erosion_forcing_model'],'DISCHARGE_NORMALISED_BY_EXPLICIT_REFERENCE_RUNOFF')
            checkpoint=json.loads((output/'CHECKPOINT-000001.json').read_text())
            actual=checkpoint['driver_diagnostics']['steps'][0]
            self.assertGreater(actual['hillslope']['internal_transferred_solid_m3'],0.)
            self.assertEqual(actual['channel']['water_discharge_m3_year'][0],.4)
            self.assertGreater(actual['channel']['rock_debit_solid_m3'][0],0.)
            self.assertGreater(actual['channel']['cover_debit_solid_m3'][0],0.)
            self.assertEqual(actual['channel']['erosion_forcing_model'],selection['erosion_forcing_model'])
            receipt=json.loads((output/'RECEIPT.json').read_text())
            self.assertEqual(receipt['schema'],'diadem.terrain.shoreline.receipt.r7')
            pins={p['name']:p for p in receipt['identity']['implementation']}
            for name in ('shoreline.py','shoreline_driver.py','event_bounds.py','hillslope_binding.py'):
                self.assertEqual(pins[name]['sha256'],hashlib.sha256((w.HERE/name).read_bytes()).hexdigest())
            self.assertIn('R5/RECEIPT.json',pins)
            self.assertIn('R7-corrected-hillslope/hillslope_kernel.py',pins)
            before={p.name:p.read_bytes() for p in output.iterdir()}
            repeat=cli(output,True);self.assertEqual(repeat.returncode,0,repeat.stderr)
            self.assertEqual(json.loads(repeat.stdout)['status'],'VERIFIED_SHORELINE_REUSE')
            self.assertEqual(before,{p.name:p.read_bytes() for p in output.iterdir()})
            self.assertFalse(result['physical_acceptance']);self.assertFalse(result['production_authorised'])
            r=endpoint_recipe();r['forcing']['dt_years']=1.
            input_path.write_text(json.dumps(r),encoding='utf-8')
            blocked_output=w.OUTPUT_ROOT/('scientific-blocked-'+token)
            failed=cli(blocked_output);self.assertEqual(failed.returncode,2)
            self.assertIn('BLOCKED_UNCERTIFIED_DRYING_EVENT',failed.stderr)
            self.assertFalse(blocked_output.exists())
            pending=list(w.OUTPUT_ROOT.glob(blocked_output.name+'.pending-*'))
            self.assertEqual(len(pending),1)
            self.assertEqual({p.name for p in pending[0].iterdir()},{'RECIPE.json'})


if __name__=='__main__':unittest.main()
