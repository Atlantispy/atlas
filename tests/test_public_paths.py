"""Synthetic privacy checks and a read-only scan of current public evidence."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import check_public_paths as guard


class SyntheticPublicPathTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for relative in guard.SCAN_ROOTS:
            (self.root / relative).mkdir(parents=True)

    def write(self, text, relative='tectonics/evidence/example.json'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_windows_literal_slashes_and_any_drive(self):
        for drive in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz':
            for slash in ('/', '\\'):
                with self.subTest(drive=drive, slash=slash):
                    path = slash.join((drive + ':', 'Users', 'SyntheticExample', 'result'))
                    self.assertTrue(guard.has_personal_home_path(path))

    def test_windows_json_escaped_and_mixed_case(self):
        for path in (r'q:\uSeRs\SyntheticExample\result', 'E:/USERS/SyntheticExample/result'):
            with self.subTest(path=path):
                self.assertTrue(guard.has_personal_home_path(json.dumps({'path': path})))

    def test_posix_paths_including_json_escaped_slashes(self):
        for path in ('/home/SyntheticExample/result', '/Users/SyntheticExample/result',
                     r'\/home\/SyntheticExample\/result', '/home/Synthetic Person/result'):
            with self.subTest(path=path):
                self.assertTrue(guard.has_personal_home_path(path))

    def test_only_exact_local_user_placeholder_is_accepted(self):
        for prefix in ('C:\\Users\\', 'z:/uSeRs/', '/home/', '/Users/'):
            for user in ('LOCAL_USER', 'local_user', 'LOCAL_USER_extra',
                         'LOCAL_USER Extra', 'OTHER_USER'):
                with self.subTest(prefix=prefix, user=user):
                    path = prefix + user + '/result'
                    self.assertEqual(guard.has_personal_home_path(json.dumps(path)),
                                     user != 'LOCAL_USER')

    def test_non_path_text_is_not_a_finding(self):
        for text in ('Users SyntheticExample', 'users/SyntheticExample',
                     'home/SyntheticExample', 'C: Users SyntheticExample',
                     'https://example.invalid/home/SyntheticExample',
                     '/opt/home/SyntheticExample/result', 'C:/build/result'):
            with self.subTest(text=text):
                self.assertFalse(guard.has_personal_home_path(text))

    def test_findings_are_relative_line_only_and_scan_is_read_only(self):
        path = self.write('plain text\nC:/Users/SyntheticExample/private/result\n')
        before = path.read_bytes()
        self.assertEqual(guard.check(self.root), [
            'tectonics/evidence/example.json:2: personal home path; '
            'use LOCAL_USER for the username'])
        self.assertEqual(path.read_bytes(), before)

    def test_scan_covers_nested_supported_text_extensions_only(self):
        for suffix in ('.json', '.MD', '.log', '.txt'):
            self.write('/home/SyntheticExample/result', 'tectonics/docs/nested/file' + suffix)
        self.write('/home/SyntheticExample/result', 'tectonics/docs/ignored.png')
        self.assertEqual(len(guard.check(self.root)), 4)

    def test_missing_expected_root_is_visible_failure(self):
        (self.root / 'tectonics/docs').rmdir()
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(guard.main(['--root', str(self.root)]), 2)
        self.assertIn('tectonics/docs:0: scan root missing or inaccessible', output.getvalue())
        self.assertNotIn(str(self.root), output.getvalue())

    def test_inaccessible_root_is_visible_without_exception_path(self):
        error = PermissionError(13, 'denied', str(self.root / 'tectonics/evidence'))
        with patch.object(guard.os, 'scandir', side_effect=error):
            with self.assertRaisesRegex(guard.ScanError, '^tectonics/evidence:0:'):
                guard.check(self.root)

    def test_unreadable_file_is_visible_without_exception_content(self):
        self.write('safe')
        with patch.object(Path, 'open', side_effect=PermissionError('SyntheticSecret')):
            with self.assertRaisesRegex(guard.ScanError,
                                        '^tectonics/evidence/example.json:0: text file unreadable'):
                guard.check(self.root)

    def test_invalid_utf8_fails_instead_of_skipping_text(self):
        path = self.write('safe')
        path.write_bytes(b'\xff')
        with self.assertRaisesRegex(guard.ScanError, 'unreadable as UTF-8'):
            guard.check(self.root)

    def test_cli_does_not_print_sensitive_content(self):
        self.write('C:/Users/SyntheticExample/private/result')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(guard.main(['--root', str(self.root)]), 1)
        self.assertNotIn('SyntheticExample', output.getvalue())
        self.assertNotIn('/private/', output.getvalue())

    def test_clean_scan_passes(self):
        self.write(json.dumps({'path': r'C:\Users\LOCAL_USER\result'}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(guard.main(['--root', str(self.root)]), 0)
        self.assertTrue(output.getvalue().startswith('PASS:'))


class CurrentEvidenceTests(unittest.TestCase):
    def test_current_public_evidence_has_no_personal_home_paths(self):
        self.assertEqual(guard.check(Path(__file__).resolve().parents[1]), [])


if __name__ == '__main__':
    unittest.main()
