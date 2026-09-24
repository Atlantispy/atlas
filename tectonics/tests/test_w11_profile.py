"""Focused W11 assessment guards; no physical solves or benchmark replays."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import check_w11 as w11


class W11ProfileTests(unittest.TestCase):
    def test_exact_selection_resolves_without_discovery(self):
        suite,selection=w11.verifier()._acceptance_suite(w11.GATES,'W11')
        self.assertEqual(suite.countTestCases(),14)
        def leaves(suite):
            for test in suite:
                if isinstance(test,unittest.TestSuite): yield from leaves(test)
                else: yield test
        self.assertTrue(all(type(test).__name__!='_FailedTest' for test in leaves(suite)))
        self.assertEqual(set(selection),set(w11.GATES))

    def test_existing_destination_refuses_before_source_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'prior.json';path.write_text('prior',encoding='utf-8')
            with patch.object(w11,'verifier',side_effect=AssertionError('must refuse first')):
                with self.assertRaises(FileExistsError): w11.main(['--report',str(path)])
            self.assertEqual(path.read_text(), 'prior')

    def test_failed_evidence_cannot_be_reused(self):
        with patch.object(w11,'read_json',return_value=dict(schema='atlas.w10-assessment.v1',decision={'status':'FAIL'})):
            with self.assertRaises(ValueError): w11.retained_w10(Path('unused'),{})
        with patch.object(w11,'read_json',return_value=dict(schema='atlas.w11-scale-evidence.v1',status='FAIL')):
            with self.assertRaises(ValueError): w11.scale_evidence(Path('unused'))


if __name__=='__main__': unittest.main()
