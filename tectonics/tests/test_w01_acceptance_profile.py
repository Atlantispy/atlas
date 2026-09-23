"""Stage-8 status logic must not turn software tests into scientific acceptance."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('w01_verification_profile',
    Path(__file__).resolve().parents[1] / 'verify.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class AcceptanceStatus(unittest.TestCase):
    def test_technical_pass_keeps_scientific_gates_open(self):
        result = profile.w01_acceptance_record(True)
        self.assertEqual(result['technical_status'], 'PASS_SUPPORTED_WORKFLOW')
        self.assertEqual(result['whole_W01_status'], 'INCOMPLETE')
        self.assertIs(result['whole_W01_complete'], False)
        self.assertEqual(result['S3C_scientific_status'], 'REOPENED')
        self.assertEqual(result['R4_4_status'], 'HELD_INCOMPLETE')
        self.assertEqual(result['described_initialisation_status'], 'PASS_SUPPORTED_WORKFLOW')
        self.assertIn('unimplemented', result['future_formation_work'])
        self.assertTrue(result['remaining_scientific_gates'])
        self.assertTrue(result['unsupported_not_passed'])

    def test_failed_or_incomplete_checks_cannot_pass_engineering(self):
        result = profile.w01_acceptance_record(False)
        self.assertEqual(result['technical_status'], 'FAIL_OR_INCOMPLETE')
        self.assertEqual(result['described_initialisation_status'], 'FAIL_OR_INCOMPLETE')
        self.assertIs(result['whole_W01_complete'], False)

    def test_profile_remains_explicit_bounded_and_covers_original_gates(self):
        names = tuple(n for group in profile.W01_GATES.values() for n in group)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(profile.W01_GATES['original_representation_and_thermal_limits']), 20)
        self.assertIn('test_w01_acceptance', names)
        self.assertIn('test_w01_workflow', names)
        self.assertIn('test_execution_reuse.IdentityTests', names)
        self.assertTrue(all('*' not in name and 'convection' not in name for name in names))
