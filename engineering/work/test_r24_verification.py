"""Small native-identity and fresh-source-read regressions; no science runs."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from work.generator_upgrade_r22 import registry as native
from work.generator_upgrade_r24 import verification


class VerificationTests(unittest.TestCase):
    def test_native_identity_parity_and_runtime_drift_rejection(self):
        for operation in ('population_scenario', 'moving_roots', 'terrain_view'):
            with self.subTest(operation=operation):
                expected = native.binding(operation)
                self.assertEqual(verification.native_binding(operation), expected)
                verification.verify_native(operation, expected)
        expected = native.binding('population_scenario')
        previous = os.environ.get('OMP_NUM_THREADS')
        changed = '7' if previous != '7' else '8'
        with mock.patch.dict(os.environ, {'OMP_NUM_THREADS': changed}):
            with self.assertRaisesRegex(ValueError, 'binding changed'):
                verification.verify_native('population_scenario', expected)
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                native._verify('population_scenario', expected)
        verification.verify_native('population_scenario', expected)

    def test_same_size_same_timestamp_change_is_read_on_next_pass(self):
        with tempfile.TemporaryDirectory(prefix='r24-source-drift-') as directory:
            source = Path(directory)/'fixture.py'
            source.write_bytes(b'value = 1\n')
            initial = source.stat()
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            first = verification.Reader()
            self.assertEqual(first.checked(source, expected), b'value = 1\n')
            # Within one pass, content is deliberately shared, not rehashed
            # from a timestamp; digest requests must still be checked.
            with self.assertRaisesRegex(ValueError, 'no silent rebind'):
                first.checked(source, '0'*64)
            first.finish()
            source.write_bytes(b'value = 2\n')
            os.utime(source, ns=(initial.st_atime_ns, initial.st_mtime_ns))
            self.assertEqual(source.stat().st_size, initial.st_size)
            second = verification.Reader()
            with self.assertRaisesRegex(ValueError, 'no silent rebind'):
                second.checked(source, expected)
            second.finish()

    def test_replacement_between_file_read_and_final_path_check_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='r24-source-replace-') as directory:
            source, replacement = Path(directory)/'fixture.py', Path(directory)/'replacement.py'
            source.write_bytes(b'value = 1\n')
            replacement.write_bytes(b'value = 2\n')
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            reader = verification.Reader()
            original_info = reader.info
            calls = 0

            def inspect(path, directory):
                nonlocal calls
                if path == source and not directory:
                    calls += 1
                    if calls == 2:
                        # The opened file has closed before the final lstat,
                        # so replacement is valid on Windows as well.
                        replacement.replace(source)
                return original_info(path, directory)

            with mock.patch.object(reader, 'info', side_effect=inspect):
                with self.assertRaisesRegex(ValueError, 'changed while reading'):
                    reader.checked(source, expected)
            self.assertEqual(calls, 2)
            reader.finish()


if __name__ == '__main__':
    unittest.main()
