"""Cheap harness checks; these never repeat the scientific benchmark."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'tools/check_w11_scale.py'
spec = importlib.util.spec_from_file_location('w11_scale_harness', TOOL)
scale = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scale)


class ScaleHarnessTests(unittest.TestCase):
    def test_deadline_and_manual_cancel(self):
        now = [10.0]
        deadline = scale.Deadline(2., clock=lambda: now[0])
        deadline.check()
        now[0] = 12.
        with self.assertRaises(scale.CancelledError):
            deadline.check()
        now[0] = 10.
        deadline.interrupted = True
        with self.assertRaises(scale.CancelledError):
            deadline.check()

    def test_exact_pair_coverage_and_output_parity(self):
        rows = []
        for order in scale.pair_order():
            for prepared in order:
                rows.append({'mode': 'prepared' if prepared else 'cold', 'status': 'PASS',
                    'complete_output_sha256': ['a', 'b', 'c'], 'elapsed_s': 1. if prepared else 2.,
                    'shared_accounting': {'peak_reserved_bytes': 100}})
        summary = scale.summarise_case({'trials': rows})
        self.assertEqual(summary['percent_saved'], 50.)
        self.assertFalse(summary['ranges_overlap'])
        with self.assertRaisesRegex(AssertionError, 'coverage'):
            scale.summarise_case({'trials': rows[:-1]})
        rows[-1]['complete_output_sha256'] = ['a', 'b', 'wrong']
        with self.assertRaisesRegex(AssertionError, 'parity'):
            scale.summarise_case({'trials': rows})

    def test_failure_evidence_is_immutable(self):
        with tempfile.TemporaryDirectory(prefix='atlas-w11-harness-') as folder:
            path = Path(folder) / 'failure.json'
            with scale.EvidenceWriter(path) as writer:
                self.assertEqual(json.loads(path.read_text())['status'], 'INCOMPLETE')
                writer.write({'status': 'FAIL', 'failure': 'retained'})
                with self.assertRaises(RuntimeError):
                    writer.write({'status': 'PASS'})
            with self.assertRaises(FileExistsError):
                scale.write_evidence(path, {'status': 'PASS'})
            self.assertEqual(json.loads(path.read_text())['status'], 'FAIL')
            incomplete = Path(folder) / 'interrupted.json'
            with self.assertRaisesRegex(RuntimeError, 'simulated interruption'):
                with scale.EvidenceWriter(incomplete):
                    raise RuntimeError('simulated interruption')
            self.assertEqual(json.loads(incomplete.read_text())['status'], 'INCOMPLETE')

    def test_unwritable_destination_refuses_before_backend_import(self):
        with tempfile.TemporaryDirectory(prefix='atlas-w11-harness-') as folder:
            target = Path(folder) / 'new.json'
            with patch.object(scale, 'EvidenceWriter', side_effect=PermissionError('denied')), \
                    patch.object(scale, 'load_backend') as backend, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(PermissionError):
                    scale.main(['--report', str(target)])
                backend.assert_not_called()
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
