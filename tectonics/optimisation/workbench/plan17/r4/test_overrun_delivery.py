"""Synthetic notification contract only; importing this file starts nothing.

No CLI, queue, Atlas or scientific execution. The sibling delivery module is
loaded only when the authorised unittest invocation begins.
"""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SUCCESS = {'outcome': 'succeeded', 'exit_code': 0, 'tree_final': True}


def load_delivery():
    spec = importlib.util.spec_from_file_location('plan17_test_overrun', HERE / 'overrun.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def configuration(directory):
    return {
        'event_id': '33333333-3333-4333-8333-333333333333',
        'owner': '11111111-1111-4111-8111-111111111111',
        'coordinator': '22222222-2222-4222-8222-222222222222',
        'phase': 'q23',
        'manifest_sha256': 'a' * 64,
        'manifest_path': str(directory / 'REQUEST-test.json'),
        'result_directory': str(directory / 'proof-result'),
        'codex': 'C:/plan17-synthetic-only/codex.exe',
        'cwd': str(HERE),
        'projected_minutes': 32,
        'elapsed_seconds': 2881,
    }


def receipt(directory):
    return json.loads((directory / 'overrun.json').read_text(encoding='utf-8'))


class OverrunDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.delivery = load_delivery()

    def test_full_identity_actionable_nonterminal_message_and_persisted_attempt(self):
        with tempfile.TemporaryDirectory(prefix='overrun-contract-', dir=HERE) as temporary:
            directory = Path(temporary)
            config = configuration(directory)
            calls = []

            def runner(spec, delivery_dir, timeout=30):
                recipient = spec['argv'][3]
                message = spec['argv'][5]
                self.assertEqual(spec['argv'], [config['codex'], 'queue', '--thread',
                                               recipient, '--message', message])
                self.assertEqual(spec['cwd'], config['cwd'])
                self.assertEqual(timeout, 30)
                before = receipt(directory)
                self.assertEqual(before['schema'], 'plan17-overrun.r1')
                self.assertEqual(before['event_id'], config['event_id'])
                self.assertIs(before['nonterminal'], True)
                self.assertEqual(before['notifications'][recipient]['status'], 'attempting')
                for field in ('event_id', 'phase', 'manifest_sha256', 'manifest_path',
                              'result_directory', 'projected_minutes', 'elapsed_seconds'):
                    self.assertIn(str(config[field]), message, field)
                self.assertRegex(message.lower(), r'\boverrun\b')
                self.assertRegex(message.lower(), r'\b(?:nonterminal|non-terminal|still running)\b')
                self.assertIn('coordinator', message.lower())
                self.assertRegex(message.lower(), r'\b(?:review|assess|decid\w*|recommend\w*|action)\b')
                self.assertNotRegex(
                    message.lower(),
                    r'\b(?:notification|message|event|request|run)\s+'
                    r'(?:(?:has|have)\s+been\s+|is\s+|was\s+)?'
                    r'(?:read|acknowledged|accepted|approved|cleared)\b|'
                    r'\bgo\s+(?:granted|approved|received)\b',
                )
                calls.append(recipient)
                return dict(SUCCESS)

            result = self.delivery.deliver(config, directory, runner=runner)
            self.assertEqual(calls, [config['owner'], config['coordinator']])
            self.assertEqual(result, receipt(directory))
            self.assertEqual(result['schema'], 'plan17-overrun.r1')
            self.assertEqual(result['event_id'], config['event_id'])
            self.assertIs(result['nonterminal'], True)
            self.assertEqual(result['status'], 'queued')
            self.assertEqual(set(result['notifications']), set(calls))
            self.assertTrue(all(item['status'] == 'queued'
                                for item in result['notifications'].values()))

    def test_failed_timeout_exception_and_unconfirmed_recipients_are_not_retried(self):
        failures = (
            ('failed', {'outcome': 'failed', 'exit_code': 1, 'tree_final': True}),
            ('timed_out', {'outcome': 'timed_out', 'exit_code': None, 'tree_final': False}),
            ('nonfinal_success', {'outcome': 'succeeded', 'exit_code': 0, 'tree_final': False}),
            ('nonzero_success', {'outcome': 'succeeded', 'exit_code': 1, 'tree_final': True}),
            ('missing_exit', {'outcome': 'succeeded', 'exit_code': None, 'tree_final': True}),
            ('zero_failed', {'outcome': 'failed', 'exit_code': 0, 'tree_final': True}),
            ('exception', RuntimeError('planted delivery exception')),
        )
        for name, failure in failures:
            for failed_role in ('owner', 'coordinator'):
                with self.subTest(outcome=name, failed_role=failed_role):
                    with tempfile.TemporaryDirectory(prefix='overrun-outcome-', dir=HERE) as temporary:
                        directory = Path(temporary)
                        config = configuration(directory)
                        calls = []

                        def runner(spec, delivery_dir, timeout=30):
                            recipient = spec['argv'][3]
                            self.assertEqual(timeout, 30)
                            self.assertEqual(receipt(directory)['notifications'][recipient]['status'],
                                             'attempting')
                            calls.append(recipient)
                            if recipient == config[failed_role]:
                                if isinstance(failure, Exception):
                                    raise failure
                                return dict(failure)
                            return dict(SUCCESS)

                        result = self.delivery.deliver(config, directory, runner=runner)
                        self.assertEqual(calls, [config['owner'], config['coordinator']])
                        self.assertEqual(result, receipt(directory))
                        self.assertEqual(result['status'], 'failed_or_unconfirmed')
                        self.assertEqual(result['notifications'][config[failed_role]]['status'],
                                         'failed_or_unconfirmed')
                        other_role = 'coordinator' if failed_role == 'owner' else 'owner'
                        self.assertEqual(result['notifications'][config[other_role]]['status'], 'queued')

    def test_duplicate_recipient_is_sent_once_and_existing_event_refuses_replay(self):
        with tempfile.TemporaryDirectory(prefix='overrun-replay-', dir=HERE) as temporary:
            directory = Path(temporary)
            config = configuration(directory)
            config['coordinator'] = config['owner']
            calls = []

            def runner(spec, delivery_dir, timeout=30):
                recipient = spec['argv'][3]
                self.assertEqual(receipt(directory)['notifications'][recipient]['status'], 'attempting')
                calls.append(recipient)
                return dict(SUCCESS)

            result = self.delivery.deliver(config, directory, runner=runner)
            self.assertEqual(calls, [config['owner']])
            self.assertEqual(set(result['notifications']), {config['owner']})
            self.assertEqual(result['status'], 'queued')
            saved = (directory / 'overrun.json').read_bytes()
            with self.assertRaises((FileExistsError, ValueError, RuntimeError)):
                self.delivery.deliver(config, directory, runner=runner)
            self.assertEqual(calls, [config['owner']])
            self.assertEqual((directory / 'overrun.json').read_bytes(), saved)

        with tempfile.TemporaryDirectory(prefix='overrun-attempted-', dir=HERE) as temporary:
            directory = Path(temporary)
            config = configuration(directory)
            saved = json.dumps({'schema': 'plan17-overrun.r1', 'event_id': config['event_id'],
                                'nonterminal': True, 'notifications': {
                                    config['owner']: {'status': 'attempting'}}}).encode('utf-8')
            (directory / 'overrun.json').write_bytes(saved)
            calls = []

            def must_not_run(spec, delivery_dir, timeout=30):
                calls.append(spec)
                self.fail('an existing attempted event must refuse replay before runner')

            with self.assertRaises((FileExistsError, ValueError, RuntimeError)):
                self.delivery.deliver(config, directory, runner=must_not_run)
            self.assertEqual(calls, [])
            self.assertEqual((directory / 'overrun.json').read_bytes(), saved)


if __name__ == '__main__':
    unittest.main()
