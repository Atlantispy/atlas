"""Two source-only q23/q63 binding controls; importing this file runs nothing.

The separately cleared native eleven-token invocation supplies a pinned metadata
fixture. No live admission, queue import, process launch or science is exercised.
Faults are in-memory snapshots. The exclusive result is written only if both
methods pass, in controls' already-created result directory.
"""
import argparse
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
TEST_FILE = Path(__file__).resolve()
ADMISSION = HERE / 'admission_r7.py'
ARGS = None


class TicketBindingControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ARGS is None:
            raise ValueError('the exact source-bound native control command is required')
        cls.request_path = ARGS.manifest.resolve()
        cls.request_sha256 = ARGS.sha256
        raw = cls.request_path.read_bytes()
        if sha256(raw).hexdigest() != cls.request_sha256:
            raise ValueError('control request identity changed')
        cls.manifest = json.loads(raw)
        if cls.manifest['pins'].get(str(ADMISSION)) != sha256(ADMISSION.read_bytes()).hexdigest():
            raise ValueError('r7 admission source is not request-pinned')
        spec = importlib.util.spec_from_file_location('plan17_ticket_r7_tested', ADMISSION)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        cls.phase = cls.manifest['phases'][ARGS.phase]
        cls.native_argv = list(sys.orig_argv)
        cls.result_directory = Path(cls.manifest['phases']['controls']['result_directory'])
        if not cls.result_directory.is_absolute() or not cls.result_directory.is_dir():
            raise ValueError('controls result directory must already exist')

    def bind(self, argv=None, **changes):
        values = dict(manifest=self.manifest, phase=self.phase,
                      manifest_path=self.request_path, manifest_sha256=self.request_sha256,
                      dispatcher=TEST_FILE, argv=self.native_argv if argv is None else argv)
        values.update(changes)
        return self.module.command_binding(**values)

    def test_native_scientific_phase_and_exact_assigned_ticket(self):
        binding = self.bind(list(sys.orig_argv))
        declared = self.manifest['interpreter_binding']
        self.assertEqual(len(self.native_argv), 11)
        self.assertEqual(self.native_argv[1:4], ['-B', '-s', '-P'])
        self.assertEqual(self.native_argv[-2:], ['--phase', 'q23'])
        self.assertEqual(self.phase['ticket'], 'q63')
        self.assertIn(Path(self.native_argv[0]).resolve(),
                      {Path(declared[name]).resolve() for name in ('venv_executable', 'base_executable')})
        self.assertEqual(Path(sys.executable).resolve(), Path(declared['venv_executable']).resolve())
        self.assertEqual(Path(sys._base_executable).resolve(), Path(declared['base_executable']).resolve())
        self.assertEqual(os.environ.get('PYTHONHASHSEED'), '0')
        self.assertEqual(sys.flags.hash_randomization, 0)
        self.assertTrue(sys.flags.dont_write_bytecode and sys.flags.no_user_site and sys.flags.safe_path)
        self.assertEqual(binding['scientific_phase'], 'q23')
        self.assertEqual(binding['queue_ticket'], 'q63')
        self.assertEqual(binding['argv'], self.native_argv)
        self.assertEqual(binding['request']['sha256'], self.request_sha256)
        self.assertEqual(binding['dispatcher']['path'], str(TEST_FILE))
        self.assertEqual(binding['dispatcher']['sha256'], self.manifest['pins'][str(TEST_FILE)])
        expected_key = ' '.join([Path(self.native_argv[0]).name, '-B', '-s', '-P', TEST_FILE.name,
                                 '--manifest', self.request_path.name, '--sha256', self.request_sha256,
                                 '--phase', 'q23'])
        self.assertEqual(binding['cmd_key'], expected_key)
        self.assertLess(len(expected_key), 400)
        self.assertIn(self.request_sha256, binding['cmd_key'].split())
        commands = json.dumps(self.phase['commands'], sort_keys=True,
                              separators=(',', ':'), allow_nan=False).encode()
        self.assertEqual(binding['commands_sha256'], sha256(commands).hexdigest())
        self.assertEqual(binding['interpreter']['raw_orig_argv0'], self.native_argv[0])
        for name, source in binding['interpreter']['sources'].items():
            path = str(Path(declared[name]).resolve())
            self.assertEqual(source, dict(path=path, sha256=self.manifest['pins'][path]))
        self.assertEqual(binding['queue_source']['sha256'], self.module.RUNQ_SHA256)

        for index, value in ((10, 'q24'), (10, 'q63'), (8, '0' * 64), (4, str(ADMISSION))):
            changed = list(self.native_argv)
            changed[index] = value
            with self.subTest(token=index, value=value), self.assertRaises(ValueError):
                self.bind(changed)
        changed_phase = dict(self.phase, ticket='q23')
        with self.assertRaisesRegex(ValueError, 'request-bound long proof'):
            self.bind(phase=changed_phase)
        changed_manifest = deepcopy(self.manifest)
        changed_manifest['phases']['q23']['ticket'] = 'q23'
        with self.assertRaisesRegex(ValueError, 'loaded request differs'):
            self.bind(manifest=changed_manifest, phase=changed_manifest['phases']['q23'])
        with self.assertRaisesRegex(ValueError, 'changed admission source'):
            self.bind(manifest_sha256='0' * 64)

        native_read = self.module._read

        def changed_dispatcher(path, expected=None):
            raw, source = native_read(path, expected)
            if Path(path).resolve() == TEST_FILE:
                source = dict(source, sha256=sha256(raw + b'\n# in-memory source fault\n').hexdigest())
            return raw, source

        with patch.object(self.module, '_read', side_effect=changed_dispatcher):
            with self.assertRaisesRegex(ValueError, 'dispatcher is not pinned'):
                self.bind()
        for ticket in (None, 63, True, '', 'q0', 'q01', 'Q63', 'q63 ', 'q63\n'):
            changed = deepcopy(self.manifest)
            changed['phases']['q23']['ticket'] = ticket
            raw = json.dumps(changed).encode()
            digest = sha256(raw).hexdigest()
            argv = list(self.native_argv)
            argv[8] = digest

            def changed_request(path, expected=None):
                if Path(path).resolve() == self.request_path:
                    self.assertEqual(expected, digest)
                    return raw, dict(path=str(self.request_path), sha256=digest)
                return native_read(path, expected)

            with self.subTest(ticket=ticket), patch.object(self.module, '_read', side_effect=changed_request):
                with self.assertRaisesRegex(ValueError, 'exact queue ticket binding'):
                    self.bind(argv, manifest=changed, phase=changed['phases']['q23'], manifest_sha256=digest)
        self.assertEqual(list(sys.orig_argv), self.native_argv)
        type(self).native_binding = binding

    def test_synthetic_admission_preserves_failed_q23_and_exact_q63_guards(self):
        module = self.module
        shared = module.load_shared()
        binding = self.bind()
        row = dict(id='q63', status='running', runner_pid=63, tracker='job', cores=7, min=32,
                   job_name='Local\\runq-run-q63-63', cmd_key=binding['cmd_key'],
                   pred_peak_gib=Decimal('1.2'), pred_basis=module.BOOKING_BASIS, gib=Decimal('1.2'))
        failed = dict(id='q23', status='failed', runner_pid=23, tracker='job', exit=1,
                      job_name='Local\\runq-run-q23-23')
        queue = dict(tickets=[failed, row])
        environment = dict(RUNQ_PRED_PEAK_GIB='1.2', RUNQ_TICKET_GIB='1.2')
        source = dict(path='synthetic/queue.json', sha256='c' * 64)
        peaks_source = dict(path='synthetic/peaks.json', sha256='d' * 64)

        def admit(**overrides):
            values = dict(phase=self.phase, binding=binding, queue=queue, queue_source=source,
                          ancestors={63}, environment=environment, available_bytes=5 << 30,
                          peaks={}, peaks_source=peaks_source,
                          flags=SimpleNamespace(hash_randomization=0), shared=shared)
            values.update(overrides)
            return module.admit_snapshot(**values)

        admitted = admit()
        self.assertEqual(admitted['predicted_peak_bytes'], module.gib_bytes('1.2'))
        self.assertEqual(admitted['provenance']['job_name'], row['job_name'])
        self.assertEqual(admitted['provenance']['queue'], source)
        self.assertEqual(queue['tickets'][0], failed)
        for mutation in (dict(id='q23'), dict(ticket_hold='held'),
                         dict(job_name='Local\\runq-run-q23-63'), dict(cmd_key='another-source-command')):
            changed = deepcopy(queue)
            changed['tickets'][1].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                admit(queue=changed)
        duplicate = dict(row, status='queued', runner_pid=None)
        with self.assertRaisesRegex(ValueError, 'duplicated'):
            admit(queue=dict(tickets=[failed, row, duplicate]))
        for changed in (dict(environment, RUNQ_PRED_PEAK_GIB='1.3'),
                        dict(environment, RUNQ_TICKET_GIB='1.3')):
            with self.subTest(environment=changed), self.assertRaises(ValueError):
                admit(environment=changed)
        history = [dict(peak=Decimal('1.3'), who='synthetic-prior', when='synthetic', tracker='job')]
        unrelated = admit(peaks={'another-source-command': history})
        self.assertEqual(unrelated['predicted_peak_bytes'], module.gib_bytes('1.2'))
        with self.assertRaisesRegex(ValueError, 'prediction basis/history mismatch'):
            admit(peaks={binding['cmd_key']: history})
        measured_queue = deepcopy(queue)
        measured_queue['tickets'][1].update(pred_peak_gib=Decimal('1.3'),
            pred_basis='max of 1 earlier job-tracked run(s) of this command')
        measured = admit(queue=measured_queue, peaks={binding['cmd_key']: history},
                         environment=dict(environment, RUNQ_PRED_PEAK_GIB='1.3'))
        self.assertEqual(measured['predicted_peak_bytes'], module.gib_bytes('1.3'))
        self.assertEqual(measured['provenance']['history'][0]['who'], 'synthetic-prior')
        self.assertEqual(queue['tickets'], [failed, row])
        self.assertEqual(list(sys.orig_argv), self.native_argv)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--phase', choices=['q23'], required=True)
    ARGS = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TicketBindingControls)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        with (TicketBindingControls.result_directory / 'native-ticket.json').open('x', encoding='utf-8') as stream:
            json.dump(dict(schema='plan17-native-ticket-control.r7', status='PASS', methods=2,
                           scope='native metadata and synthetic admission only; no live queue or science',
                           manifest_sha256=TicketBindingControls.request_sha256,
                           native_binding=TicketBindingControls.native_binding), stream, indent=2, allow_nan=False)
            stream.write('\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
