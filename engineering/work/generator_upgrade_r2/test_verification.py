"""Failure injection for the new verifier, without re-running any old suite."""
import copy
import hashlib
import json
import os
import unittest
from unittest.mock import patch
from . import verify as v


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.ids=['oracle.a','oracle.b']
        self.digest=hashlib.sha256(json.dumps(self.ids,separators=(',',':')).encode()).hexdigest()
        self.before={'source.py':'sha'};self.prior={'old':'preserved'}
        r=dict(status='PASS',tests=2,failures=0,errors=0,skips=0,test_ids=self.ids,
            started=self.ids,stopped=self.ids,passed=self.ids,inventory_sha256=self.digest,
            source_snapshot=self.before,predecessor_readback=self.prior,
            executed_source_hashes={'source.py':'sha'},owner_bindings={'owner':'bound'},
            runtime={'runtime':'same'},reference={'mass':'exact'})
        self.records=[copy.deepcopy(r)|{'optimisation_flag':0},copy.deepcopy(r)|{'optimisation_flag':2}]

    def check(self):
        with patch.object(v,'EXPECTED_TEST_COUNT',2),patch.object(v,'INVENTORY_SHA256',self.digest):
            v.validate_workers(self.records,self.before,self.prior)

    def test_genuine_two_mode_pair_accepted(self):self.check()

    def test_inherited_optimisation_is_removed(self):
        with patch.dict(os.environ,{'PYTHONOPTIMIZE':'2','EXPLICIT_TEST_SENTINEL':'keep'}):
            e=v.child_environment();self.assertNotIn('PYTHONOPTIMIZE',e);self.assertEqual(e['EXPLICIT_TEST_SENTINEL'],'keep')
            self.assertEqual(os.environ['PYTHONOPTIMIZE'],'2')

    def test_two_optimised_runs_cannot_claim_normal_coverage(self):
        self.records[0]['optimisation_flag']=2
        with self.assertRaises(ValueError):self.check()

    def test_matching_transient_worker_sources_cannot_replace_parent_capture(self):
        for r in self.records:r['source_snapshot']={'source.py':'transient'}
        with self.assertRaises(ValueError):self.check()

    def test_executed_package_digest_must_match_parent(self):
        for r in self.records:r['executed_source_hashes']={'source.py':'transient'}
        with self.assertRaises(ValueError):self.check()

    def test_failure_cannot_hide_behind_equal_mode_receipts(self):
        for r in self.records:r['errors']=1
        with self.assertRaises(ValueError):self.check()

    def test_skipped_or_unexecuted_test_cannot_pass(self):
        self.records[0]['passed']=self.ids[:1]
        with self.assertRaises(ValueError):self.check()

    def test_reference_mode_disagreement_rejected(self):
        self.records[1]['reference']={'mass':'different'}
        with self.assertRaises(ValueError):self.check()


if __name__=='__main__':unittest.main()
