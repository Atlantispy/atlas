from types import SimpleNamespace
import unittest
import verify_release


class ReleaseVerifierTests(unittest.TestCase):
    def test_empty_or_missing_tests_cannot_pass(self):
        for count in (0,1,233):
            with self.assertRaises(RuntimeError):
                verify_release.require_test_success(SimpleNamespace(testsRun=count,skipped=[],wasSuccessful=lambda:True),"")

    def test_failures_and_skips_cannot_pass(self):
        for success,skipped in ((False,[]),(True,["skip"])):
            with self.assertRaises(RuntimeError):
                verify_release.require_test_success(SimpleNamespace(testsRun=234,skipped=skipped,wasSuccessful=lambda:success),"")

    def test_complete_success_is_admitted(self):
        verify_release.require_test_success(SimpleNamespace(testsRun=234,skipped=[],wasSuccessful=lambda:True),"")

    def test_release_closure_includes_staged_registration_and_predecessor(self):
        names={p["name"] for p in verify_release.closure_pins()}
        self.assertIn("integration/Run-Generator.ps1",names)
        self.assertIn("integration/gate.py",names)
        self.assertIn("reference_versions/water_before_equal_saddles.py",names)


if __name__=="__main__":unittest.main()
