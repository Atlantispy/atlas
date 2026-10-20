"""Deterministic liveness/lock tests. Never reads or mutates the live queue."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('candidate_runq', HERE/'runq.py')
Q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(Q)


class LivenessTests(unittest.TestCase):
    def probe(self, error):
        kernel = Mock()
        kernel.OpenProcess.return_value = 0
        return (
            patch.object(Q.psutil, 'pid_exists', return_value=False),
            patch.object(Q, '_K32', kernel),
            patch.object(Q.ctypes, 'get_last_error', return_value=error, create=True),
        )

    def test_access_denied_keeps_runner_and_lock_and_refuses_admission(self):
        a, b, c = self.probe(5)
        with a, b, c, tempfile.TemporaryDirectory(dir=HERE) as temp:
            lock = Path(temp)/'lock.json'
            original = json.dumps({'pid': 1234, 'owner': 'existing'})
            lock.write_text(original)
            queue = {'tickets': [{'status': 'running', 'runner_pid': 1234}]}
            with patch.object(Q, 'LOCK', lock):
                Q.reap(queue)
                self.assertEqual(queue['tickets'][0]['status'], 'running')
                self.assertEqual(Q.lock_holder()['owner'], 'existing')
                self.assertFalse(Q.try_lock({'owner': 'new', 'gib': 1, 'id': 'test', 'what': 'fixture'}))
                self.assertEqual(lock.read_text(), original)

    def test_genuinely_absent_pid_reaped_and_stale_lock_replaceable(self):
        a, b, c = self.probe(87)
        with a, b, c, tempfile.TemporaryDirectory(dir=HERE) as temp:
            lock = Path(temp)/'lock.json'
            lock.write_text(json.dumps({'pid': 1234}))
            queue = {'tickets': [{'status': 'running', 'runner_pid': 1234}]}
            with patch.object(Q, 'LOCK', lock):
                Q.reap(queue)
                self.assertEqual(queue['tickets'][0]['status'], 'died')
                self.assertIsNone(Q.lock_holder())
                self.assertTrue(Q.try_lock({'owner': 'new', 'gib': 1, 'id': 'test', 'what': 'fixture'}))
                self.assertEqual(json.loads(lock.read_text())['owner'], 'new')

    def test_normal_live_skips_fallback(self):
        kernel = Mock()
        with patch.object(Q.psutil, 'pid_exists', return_value=True), patch.object(Q, '_K32', kernel):
            self.assertTrue(Q.pid_exists(1234))
        kernel.OpenProcess.assert_not_called()

    def test_fallback_open_closes_handle(self):
        kernel = Mock()
        kernel.OpenProcess.return_value = 123
        with patch.object(Q.psutil, 'pid_exists', return_value=False), patch.object(Q, '_K32', kernel):
            self.assertTrue(Q.pid_exists(1234))
        kernel.OpenProcess.assert_called_once_with(0x1000, False, 1234)
        kernel.CloseHandle.assert_called_once_with(123)

    def test_other_os_preserves_negative(self):
        with patch.object(Q.psutil, 'pid_exists', return_value=False), patch.object(Q, '_K32', None):
            self.assertFalse(Q.pid_exists(1234))

    def test_unexpected_probe_error_fails_closed(self):
        a, b, c = self.probe(8)
        with a, b, c:
            with self.assertRaises(OSError):
                Q.pid_exists(1234)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LivenessTests))
    if len(sys.argv) == 2:
        pid = int(sys.argv[1])
        record = {'pid': pid, 'observer_pid': os.getpid(), 'psutil_pid_exists': Q.psutil.pid_exists(pid)}
        handle = Q._K32.OpenProcess(0x1000, False, pid)
        record['open_process_succeeded'] = bool(handle)
        record['open_process_error'] = 0 if handle else Q.ctypes.get_last_error()
        if handle:
            Q._K32.CloseHandle(handle)
        record['candidate_pid_exists'] = Q.pid_exists(pid)
        record['tests_passed'] = result.wasSuccessful()
        (HERE/'sandbox-live-pid.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf8')
        print(json.dumps(record))
    sys.exit(not result.wasSuccessful())
