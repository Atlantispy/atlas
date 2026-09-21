"""Focused benchmark-harness checks, NOT a numerical solver test receipt.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.dont_write_bytecode = True
PATH = Path(__file__).resolve().parents[1] / 'tools/benchmark_combined_start_r4_4.py'
SPEC = importlib.util.spec_from_file_location('combined_benchmark_under_test', PATH)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


class ProtocolTests(unittest.TestCase):
    def test_fixed_exact_base(self):
        self.assertEqual(bench.BASE, '49c6603fad2ed9a92f6f2a302037dd425f154c3c')

    def test_alternating_three_pair_order(self):
        self.assertEqual([bench.order(i) for i in range(3)],
                         [bench.MODES, bench.MODES[::-1], bench.MODES])

    def test_summary_raw_medians_and_negative_savings(self):
        data = [dict(zip(bench.MODES, p)) for p in ((10., 9.), (14., 10.), (12., 15.))]
        got = bench.summary(data)
        self.assertEqual(got['baseline_median_s'], 12.)
        self.assertEqual(got['candidate_median_s'], 10.)
        self.assertEqual(got['seconds_saved'], 2.)
        self.assertAlmostEqual(got['percentage_saved'], 100. / 6.)
        self.assertFalse(got['all_pairs_faster'])
        slower = bench.summary([dict(zip(bench.MODES, (4., 5.)))])
        self.assertEqual(slower['seconds_saved'], -1.)
        self.assertEqual(slower['percentage_saved'], -25.)

    def test_summary_refuses_partial_pairs(self):
        with self.assertRaises(bench.Refused):
            bench.summary([{'zero-rate': 1.}])
        with self.assertRaises(bench.Refused):
            bench.summary([])

    def test_summary_refuses_zero_nan_and_infinity(self):
        for value in (0., -1., float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(bench.Refused):
                bench.summary([dict(zip(bench.MODES, (1., value)))])

    def test_only_start_switch_differs(self):
        a, b = [bench.profile_argv('/same/output', 128, mode, 1e-7, 120.) for mode in bench.MODES]
        self.assertEqual([(x, y) for x, y in zip(a, b) if x != y], [bench.MODES])
        self.assertEqual(a[a.index('--velocity-preconditioner') + 1], 'gmg')
        self.assertIn('--adaptive-inner', a)
        self.assertEqual(a[a.index('--preconditioner-max-uses') + 1], '4')
        self.assertEqual(a[a.index('--nonlinear-solver') + 1], 'anderson')

    def test_resume_does_not_resupply_frozen_policy(self):
        a = bench.profile_argv('/same/output', 128, 'previous-stage1', 1e-7, 120., resume=True)
        self.assertIn('--resume', a)
        for field in ('--nonlinear-start', '--case', '--adaptive-inner', '--max-steps', '--cells'):
            self.assertNotIn(field, a)

    def test_parser_bounded_defaults(self):
        a = bench.arguments(['--output', '/unused', '--preflight-only'])
        self.assertEqual(a.repeats, 3)
        self.assertEqual(a.dt, 1e-7)
        self.assertEqual(a.seconds, 120.)

    def test_parser_requires_exclusive_host_for_numerics(self):
        with self.assertRaises(bench.Refused):
            bench.arguments(['--output', '/unused'])

    def test_parser_refuses_bad_dt(self):
        for dt in ('0', '-1', 'nan', 'inf', '.1'):
            with self.subTest(dt=dt), self.assertRaises(bench.Refused):
                bench.arguments(['--output', '/unused', '--preflight-only', '--dt', dt])

    def test_parser_refuses_unbounded_allowance(self):
        for seconds in ('0', 'nan', '301'):
            with self.subTest(seconds=seconds), self.assertRaises(bench.Refused):
                bench.arguments(['--output', '/unused', '--preflight-only', '--seconds', seconds])

    def test_manifest_required_with_fixture(self):
        with self.assertRaises(bench.Refused):
            bench.arguments(['--output', '/unused', '--preflight-only', '--fixture', 'field.npz'])

    def test_exclusive_evidence_write(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'record.json'
            bench.write_json(p, {'a': 1})
            with self.assertRaises(FileExistsError):
                bench.write_json(p, {'a': 2})
            self.assertEqual(json.loads(p.read_text()), {'a': 1})

    def test_no_nonfinite_json(self):
        with self.assertRaises(ValueError):
            bench.encode({'a': float('nan')})

    def test_child_wait_and_capture(self):
        p, interrupted = bench.run_child_cooperatively([sys.executable, '-c', 'print("child-complete")'])
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(), 'child-complete')
        self.assertFalse(interrupted)

    def test_no_solver_work_after_source_refusal(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(bench, 'source_audit',
                side_effect=bench.Refused('exact source absent')), mock.patch.object(bench, 'load_runner') as load:
            out = Path(td) / 'result'
            self.assertEqual(bench.main(['--output', str(out), '--preflight-only']), 2)
            load.assert_not_called()
            evidence = json.loads((out / 'result.json').read_text())
            self.assertEqual(evidence['numerical_trials_completed'], 0)
            self.assertIn('exact source absent', evidence['error'])

    def test_preflight_has_no_numerical_import(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(bench, 'source_audit',
                return_value={'base': bench.BASE}), mock.patch.object(bench, 'load_runner') as load:
            self.assertEqual(bench.main(['--output', str(Path(td) / 'result'), '--preflight-only']), 0)
            load.assert_not_called()


class SourceAuditTests(unittest.TestCase):
    """Temporary synthetic Git repositories; never touch an existing checkout."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.root = self.repo / 'tectonics'
        for name in ('src/__init__.py', 'tools/run_convection_r4_4.py',
                     'cases/convection_r4_4.json', 'pyproject.toml', 'docs/OPTIMISATION_REFERENCE.md'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'# test fixture\n')
        def git(*args):
            return subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                                  capture_output=True, text=True).stdout.strip()
        git('init', '-q')
        git('config', 'user.name', 'Synthetic harness test')
        git('config', 'user.email', 'synthetic@example.invalid')
        git('add', '.')
        git('commit', '-qm', 'Synthetic test input, not Atlas')
        self.commit = git('rev-parse', 'HEAD')
        git('checkout', '--detach', '-q', self.commit)
        self.git = git

    def tearDown(self):
        self.temp.cleanup()

    def audit(self):
        return bench.source_audit(self.root, self.commit)

    def test_exact_bytes_pass(self):
        record = self.audit()
        self.assertEqual(record['base'], self.commit)
        self.assertEqual(len(record['inventory']), 5)

    def test_changed_source_refused(self):
        (self.root / 'src/__init__.py').write_text('# edited\n')
        with self.assertRaisesRegex(bench.Refused, 'differs'):
            self.audit()

    def test_untracked_or_ignored_source_member_refused(self):
        (self.root / 'src/untracked.py').write_text('# extra\n')
        with self.assertRaisesRegex(bench.Refused, 'membership'):
            self.audit()

    def test_bytecode_refused(self):
        (self.root / 'src/__init__.pyc').write_bytes(b'not-real-bytecode')
        with self.assertRaisesRegex(bench.Refused, 'membership'):
            self.audit()

    def test_wrong_commit_refused(self):
        with self.assertRaisesRegex(bench.Refused, 'Expected exact base'):
            bench.source_audit(self.root)

    def test_attached_branch_refused(self):
        self.git('checkout', '-qb', 'do-not-benchmark-production')
        with self.assertRaisesRegex(bench.Refused, 'detached'):
            self.audit()

    def test_tooling_addition_outside_source_is_allowed(self):
        (self.root / 'tools/new_benchmark.py').write_text('# allowed\n')
        self.audit()

    def test_runner_modification_refused(self):
        (self.root / 'tools/run_convection_r4_4.py').write_text('# changed runner\n')
        with self.assertRaisesRegex(bench.Refused, 'differs'):
            self.audit()

    @unittest.skipIf(sys.platform == 'win32', 'Symlink creation may need an elevated Windows privilege.')
    def test_symlink_refused(self):
        p = self.root / 'src/__init__.py'
        p.unlink()
        p.symlink_to(self.root / 'pyproject.toml')
        with self.assertRaisesRegex(bench.Refused, 'Symlink'):
            self.audit()


class SeedChainTests(unittest.TestCase):
    def states(self):
        items = []
        for i in (1, 2):
            stage0, stage1 = f'{i}-stage0', f'{i}-stage1'
            seed = SimpleNamespace(guess_id=f'{i}-guess', descriptor=lambda s=stage1: {'source_result_id': s})
            cross = {'output_guess_id': seed.guess_id,
                     'input_guess_id': None if i == 1 else '1-guess',
                     'input_stage1_result_id': None if i == 1 else '1-stage1',
                     'input_state_id': 'initial' if i == 1 else 'state1'}
            stages = [{'result_id': stage0, 'initial_guess_id': cross['input_guess_id'],
                       'initial_guess_result_id': cross['input_stage1_result_id']},
                      {'result_id': stage1, 'initial_guess_result_id': stage0}]
            meta = {'step_record': {'nonlinear_mechanics': {'stages': stages, 'cross_step_start': cross}}}
            items.append(SimpleNamespace(state_id=f'state{i}', next_initial_guess=seed,
                                         descriptor=lambda m=meta: m))
        return items

    def test_correct_two_step_chain(self):
        bench.validate_seed_chain(self.states(), 'previous-stage1')

    def test_wrong_previous_result_refused(self):
        states = self.states()
        states[1].descriptor()['step_record']['nonlinear_mechanics']['cross_step_start']['input_stage1_result_id'] = 'wrong'
        with self.assertRaises(bench.Refused):
            bench.validate_seed_chain(states, 'previous-stage1')

    def test_cold_second_step_refused(self):
        states = self.states()
        stages = states[1].descriptor()['step_record']['nonlinear_mechanics']['stages']
        stages[0]['initial_guess_id'] = None
        with self.assertRaises(bench.Refused):
            bench.validate_seed_chain(states, 'previous-stage1')

    def test_fake_first_seed_refused(self):
        states = self.states()
        stages = states[0].descriptor()['step_record']['nonlinear_mechanics']['stages']
        stages[0]['initial_guess_result_id'] = 'fake'
        with self.assertRaises(bench.Refused):
            bench.validate_seed_chain(states, 'previous-stage1')

    def test_zero_rate_cannot_publish_a_seed(self):
        with self.assertRaises(bench.Refused):
            bench.validate_seed_chain(self.states(), 'zero-rate')



class FieldEvidenceTests(unittest.TestCase):
    """Tiny NumPy utility checks, not solver benchmarks or physics evidence."""
    def test_reports_cross_mode_differences_without_acceptance_claim(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / 'a.npz', Path(td) / 'b.npz'
            np.savez(a, common=np.array([1., 2.]), zeros=np.zeros(2))
            np.savez(b, common=np.array([1., 3.]), zeros=np.zeros(2), seed=np.ones(2))
            result = bench.compare_arrays(a, b)
            self.assertEqual(result['fields']['common']['max_abs'], 1.)
            self.assertEqual(result['fields']['common']['relative_linf'], .5)
            self.assertIsNone(result['fields']['zeros']['relative_linf'])
            self.assertEqual(result['only_candidate'], ['seed'])
            self.assertFalse(result['cross_mode_equivalence_accepted'])

    def test_refuses_nonfinite_output(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / 'a.npz', Path(td) / 'b.npz'
            np.savez(a, x=np.array([1.]))
            np.savez(b, x=np.array([float('nan')]))
            with self.assertRaises(bench.Refused):
                bench.compare_arrays(a, b)

    def make_fixture(self, td, shape=(128, 128), dtype='float64'):
        import numpy as np
        path = Path(td) / 'fields.npz'
        np.savez(path, temperature_k=np.ones(shape, dtype=dtype), composition=np.zeros(shape, dtype=dtype))
        meta = {'schema': 'atlas.r44.raw-field-fixture.v1',
                'kind': 'new-source-derived-developed-input', 'case': 'tosi-2', 'cells': 128,
                'npz_sha256': bench.sha(path.read_bytes()), 'origin': 'Synthetic unit-test only',
                'transformation': 'None: deliberately fabricated utility-test data',
                'original_source_identity': 'synthetic-test-not-an-Atlas-checkpoint'}
        manifest = Path(td) / 'manifest.json'
        manifest.write_bytes(bench.encode(meta))
        out = Path(td) / 'output'
        out.mkdir()
        args = SimpleNamespace(fixture=path, fixture_manifest=manifest)
        return args, out, meta

    def test_fixture_provenance_is_not_promoted_to_historical_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            args, out, _ = self.make_fixture(td)
            t, c, meta = bench.fixture(None, 128, args, out)
            self.assertFalse(t.flags.writeable)
            self.assertFalse(c.flags.writeable)
            self.assertFalse(meta['provenance']['historical_restart'])
            self.assertFalse(meta['provenance']['fine_grid_evolved_evidence'])
            self.assertIn('caller-declared', meta['provenance']['provenance_status'])

    def test_fixture_hash_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as td:
            args, out, meta = self.make_fixture(td)
            meta['npz_sha256'] = '0' * 64
            args.fixture_manifest.write_bytes(bench.encode(meta))
            with self.assertRaisesRegex(bench.Refused, 'hash mismatch'):
                bench.fixture(None, 128, args, out)

    def test_wrong_shape_refused_before_field_capture(self):
        with tempfile.TemporaryDirectory() as td:
            args, out, _ = self.make_fixture(td, shape=(2, 2))
            with self.assertRaisesRegex(bench.Refused, '128-square'):
                bench.fixture(None, 128, args, out)

    def test_no_implicit_dtype_conversion(self):
        with tempfile.TemporaryDirectory() as td:
            args, out, _ = self.make_fixture(td, dtype='float32')
            with self.assertRaisesRegex(bench.Refused, 'float64'):
                bench.fixture(None, 128, args, out)


if __name__ == '__main__':
    unittest.main(verbosity=2)
