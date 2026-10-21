"""Disposable synthetic evidence only; imports no Atlas runtime or scientific input.

Run through the separately admitted small lane. Temporary files stay below this
owned folder, and exact fixture containment is checked before automatic cleanup.
"""
import copy
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import numpy as np

OWN = Path(__file__).resolve().parent
FIXTURES = OWN/'fixtures'
SPEC = importlib.util.spec_from_file_location('plan13_q25_check_r1', OWN/'q25_check_r1.py')
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf8')


class Q25Fixtures(unittest.TestCase):
    def setUp(self):
        FIXTURES.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='q25-', dir=FIXTURES)
        self.root = Path(self.temp.name).resolve()
        C.need(self.root.parent == FIXTURES.resolve(), 'unsafe fixture cleanup root')
        self.addCleanup(self.temp.cleanup)
        self.ck = self.root/'ck'
        self.ck.mkdir()
        self.archive = self.ck/'q25-waiter-held.log'
        self.old_log = b'historical synthetic held waiter\n'
        self.archive.write_bytes(self.old_log)
        self.old_patch = patch.object(C, 'OLD_LOG_SHA', hashlib.sha256(self.old_log).hexdigest())
        self.old_patch.start()
        self.addCleanup(self.old_patch.stop)
        source = self.ck/'h3'/'job_h3r3.sh'
        source.parent.mkdir()
        source.write_bytes(b'synthetic source only\n')
        self.pin_patch = patch.object(C, 'SOURCE_PINS', {'ck/h3/job_h3r3.sh': C.digest(source)})
        self.pin_patch.start()
        self.addCleanup(self.pin_patch.stop)
        harness = self.root/'hs'/'scripts'/'ab_heat_r5.py'
        harness.parent.mkdir(parents=True)
        harness.write_bytes(b'synthetic harness only\n')
        self.harness_patch = patch.object(C, 'HARNESS_PINS', {'ab_heat_r5.py': C.digest(harness)})
        self.harness_patch.start()
        self.addCleanup(self.harness_patch.stop)
        self.external_input = self.root/'external-capture-control.py'
        self.external_input.write_bytes(b'external input fixture')
        self.input_manifest = self.root/'input-manifest.json'
        write_json(self.input_manifest, dict(schema='plan13.q25-inputs.r1',
                   files=[dict(path=str(self.external_input), sha256=C.digest(self.external_input))]))
        for name in ('l2', 'l3r3'):
            (self.ck/name/'helpers').mkdir(parents=True)
            (self.ck/name/'helpers'/'private_heat_certification_kernel_r1.py').write_bytes(b'fixture kernel\n')
        self.out = self.ck/'ab3'
        self.out.mkdir()
        self.arms = []
        for k, (mode, label, layout) in enumerate((('proof', 'h2', 'l2'), ('proof', 'h3', 'l3r3'),
                                                  ('time', 'h3', 'l3r3'), ('time', 'h2', 'l2'))):
            arm = dict(arm=k, mode=mode, label=label, layout=str((self.ck/layout).resolve()), input=C.INPUT,
                       status='PASS', exit_code=0, leaks=0, used=[6, 6], fallback=[None, None],
                       arm_wall_seconds=100+k, tree_peak_mib=1500, available_low_mib=5000,
                       predicted_peak_gib=2.0, prediction_basis='fallback RUNQ_PRED_PEAK_GIB',
                       start_gate_gib=4.4, free_gib_at_start=8.0, parent_peak_mib=300,
                       worker_peak_mib=150, other_load_cpus=0.1, arrays={'temperature_k': 'a'*64})
            self.arms.append(arm)
            write_json(self.out/f'arm-{k}.json', dict(status='PASS', arrays=arm['arrays'],
                       ab=dict(mode=mode, layout=arm['layout'], leaks=[], fallbacks=[], workers_configured=6,
                               calls=[dict(workers=6, fallback=None), dict(workers=6, fallback=None)])))
            (self.out/f'arm-{k}.log').write_text('synthetic\n', encoding='utf8')
        self.save_arms()
        for k in (0, 1):
            capture = self.out/f'arm-{k}'
            write_json(capture/'arrays.json', {'temperature_k': [2]})
            np.save(capture/'temperature_k.npy', np.array([1.0, -0.0], dtype=np.float64))
            write_json(capture/'legacy_metadata.json', {'result_id': 'a'*64})
        (self.out/'check-arms.txt').write_text('ARMS PASS\n', encoding='utf8')
        (self.out/'compare-h2-h3.txt').write_text('array temperature_k float64 [2]: bit-identical\nD-b PASS\n', encoding='utf8')
        write_json(self.out/'h3-route.json', dict(
            kernel=str((self.ck/'l3r3'/'helpers'/'private_heat_certification_kernel_r1.py').resolve()),
            h3=dict(route='compiled', pinned_sha256=C.HELPER_SHA, build=dict(module_sha256=C.HELPER_SHA))))
        freeze = ''.join(f'{C.digest(p)} *{p.relative_to(self.ck).as_posix()}\n' for name in ('l2', 'l3r3')
                         for p in sorted((self.ck/name).rglob('*')) if p.is_file())
        for part in ('start', 'end'):
            (self.ck/f'ab3-frozen-{part}.sha256').write_text(freeze, encoding='utf8')
        (self.ck/'ab3-pins.sha256').write_text(f'{C.digest(harness)} *{harness.as_posix()}\n', encoding='utf8')
        (self.ck/'ab3-cap').mkdir()
        (self.ck/'ab3-cap'/'input.npy').write_bytes(b'captured-fixture')
        (self.ck/'ab3-w4').mkdir()
        (self.ck/'ab3-capture.log').write_text('synthetic\n', encoding='utf8')
        (self.ck/'q25.log').write_text('12:00:00 capture exit 0, files 1\n12:01:00 end exit 0\n', encoding='utf8')

    def save_arms(self):
        write_json(self.out/'summary.json', dict(arms=self.arms))

    def check(self):
        return C.result(self.ck, self.archive, 0, self.input_manifest)

    def test_complete_four_arm_evidence_and_timing_scope(self):
        report = self.check()
        self.assertEqual(report['status'], 'Q25 EVIDENCE CHECKS PASS')
        self.assertAlmostEqual(report['timing']['h2_over_h3'], 103/102)
        self.assertEqual(report['proof_arms'], [0, 1])
        self.assertEqual(report['timing']['h2_arm'], 3)
        self.assertEqual(report['timing']['h3_arm'], 2)

    def test_missing_arm_and_partial_exit_zero_refuse(self):
        for mutation in ('missing', 'partial'):
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(self.arms)
                if mutation == 'missing':
                    self.arms.pop()
                else:
                    self.arms[2].pop('status')
                self.save_arms()
                with self.assertRaises(C.Refusal):
                    self.check()
                self.arms = original

    def test_wrong_mode_label_layout_and_workers_refuse(self):
        for key, value in (('mode', 'proof'), ('label', 'h2'), ('layout', str(self.ck/'l3')),
                           ('used', [1, 1]), ('fallback', ['serial', None]), ('leaks', 1)):
            with self.subTest(key=key):
                original = copy.deepcopy(self.arms)
                self.arms[2][key] = value
                self.save_arms()
                with self.assertRaises(C.Refusal):
                    self.check()
                self.arms = original

    def test_wrong_route_and_pin_refuse(self):
        path = self.out/'h3-route.json'
        original = C.load(path)
        for key, value in (('route', 'unavailable'), ('pinned_sha256', 'b'*64)):
            with self.subTest(key=key):
                value_json = copy.deepcopy(original)
                value_json['h3'][key] = value
                write_json(path, value_json)
                with self.assertRaises(C.Refusal):
                    self.check()

    def test_changed_freeze_and_changed_current_source_refuse(self):
        path = self.ck/'ab3-frozen-end.sha256'
        original = path.read_bytes()
        path.write_bytes(original+b'changed\n')
        with self.assertRaises(C.Refusal):
            self.check()
        path.write_bytes(original)
        (self.ck/'l2'/'helpers'/'private_heat_certification_kernel_r1.py').write_bytes(b'changed source')
        with self.assertRaises(C.Refusal):
            self.check()

    def test_numeric_comparator_failure_and_actual_array_mismatch_refuse(self):
        path = self.out/'compare-h2-h3.txt'
        original = path.read_bytes()
        path.write_text('NUMERIC/OTHER\nD-b FAIL\n', encoding='utf8')
        with self.assertRaises(C.Refusal):
            self.check()
        path.write_bytes(original)
        np.save(self.out/'arm-1'/'temperature_k.npy', np.array([1.0, 0.0], dtype=np.float64))
        with self.assertRaises(C.Refusal):
            self.check()

    def test_empty_proof_capture_refuses(self):
        write_json(self.out/'arm-1'/'arrays.json', {})
        with self.assertRaises(C.Refusal):
            self.check()

    def test_all_digest_difference_values_are_retained_for_owner_disposition(self):
        write_json(self.out/'arm-1'/'legacy_metadata.json', {'result_id': 'b'*64})
        differences = self.check()['metadata_differences']
        self.assertEqual(differences, [dict(path='/result_id', before='a'*64, after='b'*64,
                                          classification='digest; owner approval required')])

    def test_metadata_number_difference_refuses_even_with_spoofed_pass_tail(self):
        write_json(self.out/'arm-0'/'legacy_metadata.json', {'number': 1})
        write_json(self.out/'arm-1'/'legacy_metadata.json', {'number': 2})
        with self.assertRaises(C.Refusal):
            self.check()

    def test_cli_success_and_fault_exit_status_and_report(self):
        arguments = ['q25_check_r1.py', 'result', '--ck', str(self.ck), '--archive-log', str(self.archive),
                     '--exit-code', '0', '--input-manifest', str(self.input_manifest)]
        for fault in (False, True):
            if fault:
                self.arms.pop()
                self.save_arms()
            output = io.StringIO()
            with patch.object(sys, 'argv', arguments), redirect_stdout(output):
                code = C.main()
            self.assertEqual(code, 1 if fault else 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report['status'], 'REFUSED' if fault else 'Q25 EVIDENCE CHECKS PASS')
            if fault:
                self.assertIn('exactly four', report['reason'])

    def test_nonzero_actual_exit_and_unpreserved_log_refuse(self):
        with self.assertRaises(C.Refusal):
            C.result(self.ck, self.archive, 1, self.input_manifest)
        self.archive.write_bytes(b'changed')
        with self.assertRaises(C.Refusal):
            self.check()

    def test_source_pin_and_harness_record_change_refuse(self):
        path = self.ck/'ab3-pins.sha256'
        original = path.read_bytes()
        path.write_text('0'*64+' *wrong.py\n', encoding='utf8')
        with self.assertRaises(C.Refusal):
            self.check()
        path.write_bytes(original)
        (self.ck/'h3'/'job_h3r3.sh').write_bytes(b'changed')
        with self.assertRaises(C.Refusal):
            self.check()

    def test_input_manifest_pins_actual_bytes(self):
        target = self.root/'input.py'
        target.write_bytes(b'input snapshot')
        manifest = self.root/'inputs.json'
        write_json(manifest, dict(schema='plan13.q25-inputs.r1', files=[dict(path=str(target), sha256=C.digest(target))]))
        self.assertEqual(C.verify_input_manifest(manifest)['files'], 1)
        target.write_bytes(b'changed')
        with self.assertRaises(C.Refusal):
            C.verify_input_manifest(manifest)

    def test_result_rechecks_external_capture_control_input(self):
        self.external_input.write_bytes(b'changed after preflight')
        with self.assertRaises(C.Refusal):
            self.check()

    def test_preflight_is_read_only_and_all_tag_artifacts_refuse(self):
        # A separate minimal root prevents test cleanup from touching retained evidence.
        other = self.root/'preflight'
        ck = other/'ck'
        ck.mkdir(parents=True)
        (ck/'q25.log').write_bytes(self.old_log)
        h13l1 = other/'h13l1'
        for name in ('runtime-src', 'helpers', 'ram'):
            (h13l1/name).mkdir(parents=True)
        write_json(h13l1/'control.json', {'paths': [str((h13l1/name).resolve()) for name in ('runtime-src', 'helpers', 'ram')]})
        bash, cygpath = other/'bash.exe', other/'cygpath.exe'
        bash.write_bytes(b'fixture')
        cygpath.write_bytes(b'fixture')
        archive = ck/'old.log'
        with patch.object(C, 'SOURCE_PINS', {}), patch.object(C, 'HARNESS_PINS', {}):
            self.assertEqual(C.preflight(ck, h13l1, archive, bash, cygpath)['status'], 'PREFLIGHT PASS')
            self.assertFalse(archive.exists())
            self.assertEqual((ck/'q25.log').read_bytes(), self.old_log)
            for name in ('ab3', 'ab3-cap', 'ab3-w4', 'ab3-capture.log', 'ab3-pins.sha256', 'ab3-frozen-start.sha256'):
                with self.subTest(name=name):
                    path = ck/name
                    path.write_bytes(b'preserve')
                    with self.assertRaises(C.Refusal):
                        C.preflight(ck, h13l1, archive, bash, cygpath)
                    self.assertEqual(path.read_bytes(), b'preserve')
                    path.unlink()


if __name__ == '__main__':
    unittest.main(verbosity=2)
