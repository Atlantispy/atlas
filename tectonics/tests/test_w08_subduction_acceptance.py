"""Source adjudication and retained evidence, not another coupled campaign."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


class SubductionAcceptanceTests(unittest.TestCase):
    def test_source_resolution_preserves_physics_and_historical_limits(self):
        old=read(ROOT/'cases/w08_subduction_r2.json')
        new=read(ROOT/'cases/w08_subduction_r3.json')
        self.assertEqual(new['predecessor_sha256'],sha(ROOT/'cases/w08_subduction_r2.json'))
        self.assertEqual(new['parent_design_sha256'],sha(ROOT/'docs/W08_REGIMES.md'))
        metadata={'schema','adapter_id','predecessor_fixture','predecessor_sha256',
            'original_2008_operator_binding','thermal_operator_source','interpretation'}
        for key,value in old.items():
            if key not in metadata:
                self.assertEqual(new[key],value,key)
        self.assertEqual(new['original_2008_operator_binding'],'RESOLVED_INDEPENDENT_WEAK_FORM')
        self.assertTrue(new['published_problem_comparison_permitted'])
        self.assertFalse(new['original_2008_acceptance_permitted'])
        self.assertEqual(new['historical_contributor_code_equivalence'],'NOT_VERIFIED')
        self.assertFalse(new['source_resolution']['scientific_operator_changed'])
        self.assertFalse(new['source_resolution']['numerical_gates_changed'])

    def test_retained_five_case_evidence_is_bound_and_passes_unchanged_gates(self):
        acceptance=read(ROOT/'evidence/w08-subduction-acceptance.json')
        fixture=read(ROOT/'cases/w08_subduction_r3.json')
        self.assertEqual(acceptance['adapter_sha256'],sha(ROOT/'cases/w08_subduction_r3.json'))
        self.assertEqual(set(acceptance['accepted_cases']),set(fixture['reference_rows']))
        self.assertEqual(acceptance['historical_contributor_code_equivalence'],'NOT_VERIFIED')
        self.assertFalse(acceptance['new_coupled_campaign'])
        reports={}
        for name,digest in acceptance['report_sha256'].items():
            path=ROOT/'evidence'/name
            self.assertEqual(sha(path),digest)
            reports[name]=read(path)
        for case,summary in acceptance['accepted_cases'].items():
            rows=summary['rows']
            self.assertEqual([r['spacing_km'] for r in rows],[6.,3.,1.5])
            for row in rows:
                raw=[r for r in reports[row['report']]['rows']
                     if r['case']==case and r['spacing_km']==row['spacing_km']]
                self.assertEqual(len(raw),1)
                self.assertEqual(raw[0]['status'],'COMPUTED')
                self.assertEqual(raw[0]['identity'],row['result_identity'])
                self.assertEqual(raw[0]['diagnostics_C'],row['diagnostics_C'])
            error=max(abs(a-b) for a,b in zip(rows[-1]['diagnostics_C'],fixture['reference_rows'][case]))
            change=max(abs(a-b) for a,b in zip(rows[-1]['diagnostics_C'],rows[-2]['diagnostics_C']))
            self.assertEqual(error,summary['finest_error_max_C'])
            self.assertEqual(change,summary['finest_change_max_C'])
            self.assertLessEqual(error,fixture['diagnostic_comparison_error_max_C'])
            self.assertLessEqual(change,fixture['finest_comparison_change_max_C'])

    def test_new_driver_binds_resolved_adapter_without_claiming_historical_replay(self):
        spec=importlib.util.spec_from_file_location('subduction_comparison_driver',ROOT/'tools/check_w08_subduction.py')
        driver=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
        with tempfile.TemporaryDirectory() as folder:
            report=Path(folder)/'report.json'
            args=['check_w08_subduction','--cases','1a','--spacing','24','--report',str(report)]
            with patch('sys.argv',args),redirect_stdout(io.StringIO()): driver.main()
            result=read(report)
        self.assertEqual(result['run_status'],'FINISHED')
        self.assertEqual(result['rows'][0]['status'],'COMPUTED')
        self.assertEqual(result['operator_binding'],'RESOLVED_INDEPENDENT_WEAK_FORM')
        self.assertTrue(result['published_problem_comparison_permitted'])
        self.assertEqual(result['fixture_sha256'],sha(ROOT/'cases/w08_subduction_r3.json'))
        self.assertEqual(result['original2008_acceptance'],'NOT_CLAIMED_HISTORICAL_IMPLEMENTATION')
        self.assertFalse(result['rows'][0]['statistics']['original2008_source_exact'])
        self.assertEqual(result['refinement'],{})  # one grid cannot certify convergence


if __name__=='__main__': unittest.main()
