"""Cheap W10 selection and status checks; no repeated physical simulations."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import check_w10 as w10


class W10ProfileTests(unittest.TestCase):
    def test_exact_method_selection_loads_without_discovery(self):
        data=w10.profile();verify=w10.verifier()
        suite,selection=verify._acceptance_suite(data['gates'],'W10')
        self.assertEqual(suite.countTestCases(),26)
        self.assertEqual(set(selection),set(data['gates']))
        def tests(suite):
            for entry in suite:
                if isinstance(entry,unittest.TestSuite): yield from tests(entry)
                else: yield entry
        self.assertTrue(all(type(t).__name__!='_FailedTest' for t in tests(suite)))

    def test_missing_duplicate_and_broad_selectors_refuse(self):
        original=w10.profile()
        for mutation in ('missing','duplicate','broad','raised_cap','policy','empty_policy'):
            data=copy.deepcopy(original)
            group=data['gates']['T01_rigid_rotation']
            if mutation=='missing': group.pop()
            elif mutation=='duplicate': group[1]=group[0]
            elif mutation=='broad': group[0]='test_foundations'
            elif mutation=='raised_cap': data['max_selected_methods']=10000
            elif mutation=='policy': data['status_policy']['production_ready']=True
            else: data['status_policy']={}
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                w10.validate_profile(data)

    def test_negative_physical_result_is_completed_assessment_not_acceptance(self):
        observation=dict(status='NOT_CONSISTENT_WITH_OBSERVED_DISPERSION',all_numerical_checks_passed=True,
                         calibration_performed=False,calibrated_confidence=False,whole_tectonics_acceptance=False)
        result=w10.decide(True,True,[],observation)
        self.assertTrue(result['assessment_completed'])
        self.assertFalse(result['whole_tectonics_field_validated'])
        self.assertFalse(result['production_ready'])
        self.assertEqual(result['R4_4_status'],'HELD_INCOMPLETE')
        for passed,unchanged,errors,obs in ((False,True,[],observation),(True,False,[],observation),
                (True,True,['stale'],observation),(True,True,[],None),
                (True,True,[],dict(observation,all_numerical_checks_passed=False)),
                (True,True,[],dict(observation,status='UNRESOLVED'))):
            self.assertFalse(w10.decide(passed,unchanged,errors,obs)['assessment_completed'])
        skipped=unittest.TestResult();skipped.testsRun=1;skipped.skipped=[('required','unavailable')]
        self.assertFalse(w10.verifier()._checks_passed(skipped,True))

    def test_json_duplicate_nonfinite_and_unsafe_paths_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.json'
            for payload in ('{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}'):
                path.write_text(payload,encoding='utf-8')
                with self.assertRaises(ValueError): w10.read_json(path)
        for path in ('../outside.json','missing-w10-file.json',str(ROOT/'verify.py')):
            with self.assertRaises(ValueError): w10.local(path)

    def test_surface_failed_missing_or_stale_receipts_refuse_without_solving(self):
        path=ROOT/'evidence/w10-free-surface-r1.json'
        original=w10.read_json(path)
        for mutation in ('fail','missing','stale','resources'):
            data=copy.deepcopy(original)
            if mutation=='fail': data['checks'][0]['status']='FAIL'
            elif mutation=='missing': data['checks'].pop()
            elif mutation=='stale': data['source_sha256']['src/atlas_tectonics/free_surface.py']='0'*64
            else: data['budget']['reserved_bytes']=1
            with self.subTest(mutation=mutation),patch.object(w10,'read_json',return_value=data):
                with self.assertRaises(ValueError): w10.check_surface(path)


if __name__=='__main__': unittest.main()
