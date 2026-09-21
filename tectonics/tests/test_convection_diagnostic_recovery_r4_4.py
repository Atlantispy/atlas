"""Missing endpoint diagnostics resume without rewriting physical receipts.
SPDX-License-Identifier: AGPL-3.0-only
"""
import contextlib
import inspect
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import run_convection_r4_4 as runner
import analyse_convection_r4_4 as audit


class DiagnosticReceiptTests(unittest.TestCase):
    def test_append_only_repair_preserves_chain_and_rejects_bad_attachments(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            base = dict(config_id='config', parent_receipt=None, state_id='state',
                        step=0, time=0., samples=[], stage_iteration_counts=[])
            runner.atomic_new(out/'receipt_000000000.json', base)
            raw = (out/'receipt_000000000.json').read_bytes()
            repair = dict(base, kind='endpoint-diagnostic', parent_receipt=runner.digest(raw),
                          samples=[dict(step=0, time=0., state_id='state')])
            path = out/'receipt_000000000_diagnostic.json'
            runner.atomic_new(path, repair)
            records, head = runner.read_receipts(out, 'config')
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['samples'], repair['samples'])
            self.assertEqual(head, runner.digest(path.read_bytes()))
            self.assertEqual((out/'receipt_000000000.json').read_bytes(), raw)
            for change in ({'state_id': 'other'}, {'stage_iteration_counts': [{}]},
                           {'samples': []}, {'parent_receipt': 'wrong'},
                           {'samples': [dict(step=1, time=0., state_id='state')]}):
                with self.subTest(change=change):
                    path.write_bytes(runner.encode(dict(repair, **change)))
                    with self.assertRaises(ValueError): runner.read_receipts(out, 'config')

    def test_repair_cannot_replace_existing_sample_or_hide_from_next_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            sample = dict(step=0, time=0., state_id='state')
            base = dict(config_id='config', parent_receipt=None, state_id='state',
                        step=0, time=0., samples=[sample], stage_iteration_counts=[])
            runner.atomic_new(out/'receipt_000000000.json', base)
            repair = dict(base, kind='endpoint-diagnostic',
                          parent_receipt=runner.digest(runner.encode(base)))
            runner.atomic_new(out/'receipt_000000000_diagnostic.json', repair)
            with self.assertRaisesRegex(ValueError, 'duplicate'): runner.read_receipts(out, 'config')
            base['samples'] = []
            (out/'receipt_000000000.json').write_bytes(runner.encode(base))
            repair['parent_receipt'] = runner.digest(runner.encode(base))
            (out/'receipt_000000000_diagnostic.json').write_bytes(runner.encode(repair))
            next_receipt = dict(base, step=1, time=1., state_id='next',
                                parent_receipt=runner.digest(runner.encode(repair)))
            runner.atomic_new(out/'receipt_000000001.json', next_receipt)
            self.assertEqual(len(runner.read_receipts(out, 'config')[0]), 2)
            (out/'receipt_000000000_diagnostic.json').unlink()
            with self.assertRaisesRegex(ValueError, 'chain changed'): runner.read_receipts(out, 'config')


class EndpointDiagnosticRecoveryTests(unittest.TestCase):
    def test_cancelled_initial_intermediate_and_final_diagnostics_resume_exactly(self):
        self._check_recovery([])

    def test_adaptive_inner_preserves_diagnostic_recovery(self):
        self._check_recovery(['--case','tosi-2','--dt','0.000001',
            '--nonlinear-solver','anderson','--nonlinear-start','previous-stage1',
            '--preconditioner-max-uses','4','--adaptive-inner'])

    def _check_recovery(self,extra_flags):
        def invoke(args):
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                code = runner.main(runner.parser().parse_args(args))
            self.assertEqual(code, 0, captured.getvalue())
            return json.loads(captured.getvalue().splitlines()[-1])

        with tempfile.TemporaryDirectory() as temp:
            args = ['--cells', '4', '--max-steps', '3', '--sample-every', '1',
                    '--save-every', '1', '--segment-steps', '3', *extra_flags]
            reference = Path(temp)/'reference'
            invoke(['--output', str(reference), *args])
            expected = audit.read_run(reference)
            for stop in (0, 1, 3):
                with self.subTest(cancelled_step=stop):
                    class EndpointCancellation(runner.Cancellation):
                        def is_set(self):
                            frame = inspect.currentframe().f_back
                            try:
                                while frame is not None:
                                    if (frame.f_code.co_name == 'mechanical_snapshot' and
                                            getattr(frame.f_locals.get('state'), 'step_index', None) == stop):
                                        return True
                                    frame = frame.f_back
                            finally:
                                del frame
                            return super().is_set()
                    out = Path(temp)/str(stop)
                    with mock.patch.object(runner, 'Cancellation', EndpointCancellation):
                        first = invoke(['--output', str(out), *args])
                    self.assertEqual(first['status'], 'CANCELLED_ACCEPTED_STATE_SAVED')
                    original = {p.name: p.read_bytes() for p in out.glob('receipt_*.json')}
                    resumed = invoke(['--output', str(out), '--resume', '--segment-steps', '3'])
                    self.assertEqual(resumed['status'], 'FINITE_SCHEDULE_COMPLETE')
                    for name, raw in original.items(): self.assertEqual((out/name).read_bytes(), raw)
                    actual = audit.read_run(out)
                    self.assertEqual(actual[2], expected[2])  # all samples, including step zero
                    self.assertEqual(actual[3], expected[3])  # no repeated physical steps
                    self.assertEqual(actual[1][-1]['state_id'], expected[1][-1]['state_id'])
                    self.assertEqual(len(actual[1]), len(expected[1]))
                    self.assertTrue(audit.analyse_run(out)['latest_sample_is_saved_endpoint'])
                    after = {p.name: p.read_bytes() for p in out.glob('receipt_*.json')}
                    invoke(['--output', str(out), '--resume', '--segment-steps', '1'])
                    self.assertEqual(after, {p.name: p.read_bytes() for p in out.glob('receipt_*.json')})
                    self.assertEqual(resumed['budget_after_close']['reserved_bytes'], 0)


if __name__ == '__main__': unittest.main()
