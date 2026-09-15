"""A release must execute its full reviewed inventory without any skips."""
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import verify_reference as v


class TestInventoryRepairTests(unittest.TestCase):
    def result(self,count=2,skips=(),success=True,expected_failures=(),unexpected_successes=()):
        return SimpleNamespace(testsRun=count,skipped=list(skips),wasSuccessful=lambda:success,
                               expectedFailures=list(expected_failures),
                               unexpectedSuccesses=list(unexpected_successes))

    def test_complete_success_is_accepted(self):
        with patch.object(v,"expected_test_inventory",return_value=["a","b"]):
            v.require_test_success(self.result(),["b","a"])

    def test_all_or_partial_skips_and_failures_reject(self):
        for result in (self.result(skips=["a","b"]),self.result(skips=["b"]),self.result(success=False),
                       self.result(expected_failures=["a"]),self.result(unexpected_successes=["a"])):
            with patch.object(v,"expected_test_inventory",return_value=["a","b"]):
                with self.assertRaisesRegex(ValueError,"failed, skipped or incomplete"):
                    v.require_test_success(result,["a","b"])

    def test_missing_duplicate_or_substituted_test_cannot_pass_by_count(self):
        for inventory in (["a"],["a","a"],["a","c"],[]):
            with patch.object(v,"expected_test_inventory",return_value=["a","b"]):
                with self.assertRaisesRegex(ValueError,"inventory"):
                    v.require_test_success(self.result(count=len(inventory)),inventory)

    def test_discovered_but_unexecuted_tests_are_rejected(self):
        with patch.object(v,"expected_test_inventory",return_value=["a","b"]):
            with self.assertRaisesRegex(ValueError,"incomplete"):
                v.require_test_success(self.result(count=1),["a","b"])

    def test_checked_in_inventory_matches_full_discovery(self):
        here=Path(__file__).parent
        suite=unittest.TestLoader().discover(str(here),pattern="test_*.py")
        self.assertEqual(sorted(v.test_ids(suite)),v.expected_test_inventory())

    def test_inventory_bytes_are_pinned(self):
        with patch.object(v,"TEST_INVENTORY_SHA256","0"*64):
            with self.assertRaisesRegex(ValueError,"identity changed"):
                v.expected_test_inventory()

    def test_actual_all_skipped_suite_cannot_reach_receipt_writer(self):
        class SyntheticSkip(unittest.TestCase):
            def runTest(self): self.skipTest("synthetic unavailable dependency")
        test=SyntheticSkip(); suite=unittest.TestSuite([test])
        with patch.object(v,"expected_test_inventory",return_value=[test.id()]), \
             patch.object(v.unittest.defaultTestLoader,"discover",return_value=suite), \
             patch.object(v,"collect",return_value=[]), \
             patch.object(v,"write_checkpoint") as checkpoint, \
             patch.object(v,"write_new_json") as writer, \
             patch("sys.stdout",new_callable=io.StringIO):
            with self.assertRaisesRegex(ValueError,"skipped"):
                v.verify("synthetic", "unused-output")
        checkpoint.assert_not_called(); writer.assert_not_called()


if __name__=="__main__": unittest.main()
