"""Interpreter links are supported without weakening scientific input checks."""
from pathlib import Path
import hashlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from atlas_tectonics import TectonicsError
from atlas_tectonics import reuse


class InterpreterPortabilityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.binary = self.root / 'python-binary'
        self.binary.write_bytes(b'fixture executable identity, not executed')
        reuse._loaded_binary.cache_clear()
        self.addCleanup(reuse._loaded_binary.cache_clear)

    def link(self, name, target):
        p = self.root / name
        try:
            p.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('host cannot create interpreter-link fixture: '+str(exc))
        return p

    def record(self, path):
        with mock.patch.object(sys, 'executable', str(path)):
            return reuse._runtime_record('reference')

    def test_regular_interpreter_content_is_hashed(self):
        record = self.record(self.binary)
        self.assertEqual(record['binaries']['python'], hashlib.sha256(self.binary.read_bytes()).hexdigest())

    def test_link_and_target_have_same_runtime_record(self):
        p = self.link('python', self.binary)
        self.assertEqual(self.record(p), self.record(self.binary))

    def test_relative_link_chain_resolves(self):
        self.link('first', self.binary.name)
        p = self.link('second', 'first')
        self.assertEqual(self.record(p), self.record(self.binary))

    def test_copy_and_target_have_same_runtime_record(self):
        other = self.root/'copy'
        shutil.copyfile(self.binary, other)
        self.assertEqual(self.record(other), self.record(self.binary))

    def test_interpreter_link_retargeting_changes_binary_identity(self):
        other = self.root/'other'; other.write_bytes(b'different binary')
        p = self.link('python', self.binary)
        a = self.record(p)
        p.unlink(); p.symlink_to(other)
        self.assertNotEqual(a['binaries']['python'], self.record(p)['binaries']['python'])

    def test_missing_interpreter_fails(self):
        with self.assertRaisesRegex(TectonicsError, 'cannot be resolved'):
            self.record(self.root/'missing')

    def test_dangling_interpreter_link_fails(self):
        p = self.link('python', self.root/'missing')
        with self.assertRaisesRegex(TectonicsError, 'cannot be resolved'):
            self.record(p)

    def test_cyclic_interpreter_link_fails(self):
        p = self.link('python', 'python')
        with self.assertRaisesRegex(TectonicsError, 'cannot be resolved'):
            self.record(p)

    def test_directory_is_not_an_interpreter(self):
        with self.assertRaisesRegex(TectonicsError, 'not a regular file'):
            self.record(self.root)

    def test_empty_interpreter_is_not_current_directory(self):
        with mock.patch.object(sys, 'executable', ''):
            with self.assertRaisesRegex(TectonicsError, 'unavailable'):
                reuse._runtime_record('reference')

    def test_none_interpreter_fails(self):
        with mock.patch.object(sys, 'executable', None):
            with self.assertRaisesRegex(TectonicsError, 'unavailable'):
                reuse._runtime_record('reference')

    def test_resolution_permission_error_is_explicit(self):
        with mock.patch.object(Path, 'resolve', side_effect=PermissionError('fixture denial')):
            with self.assertRaisesRegex(TectonicsError, 'cannot be resolved'):
                reuse._runtime_record('reference')

    def test_builtin_math_fallback_uses_resolved_interpreter(self):
        p = self.link('python', self.binary)
        # A built-in math module has no __file__; extension modules retain their
        # own binary hash. Do not broaden the exception to linked extensions.
        with mock.patch.object(reuse, 'math', object()):
            r = self.record(p)
        self.assertEqual(r['binaries']['math'], r['binaries']['python'])

    def test_strict_file_hash_still_refuses_source_or_data_links(self):
        p = self.link('scientific-input', self.binary)
        with self.assertRaisesRegex(TectonicsError, 'unavailable or linked'):
            reuse._file_hash(p)

    def test_loaded_extension_hash_still_refuses_links(self):
        p = self.link('extension', self.binary)
        with self.assertRaisesRegex(TectonicsError, 'unavailable or linked'):
            reuse._loaded_binary(str(p))

    def test_source_inventory_still_refuses_linked_source(self):
        self.link('linked.py', self.binary)
        with mock.patch.object(reuse, '__file__', str(self.root/'reuse.py')):
            with self.assertRaisesRegex(TectonicsError, 'unavailable or linked'):
                reuse._source_bytes()

    def test_runtime_identity_contains_hash_not_absolute_path(self):
        record = self.record(self.binary)
        self.assertNotIn(str(self.root), reuse._json(record).decode())

    def test_live_interpreter_is_a_real_resolved_file(self):
        target = Path(reuse._interpreter_binary())
        self.assertTrue(target.is_file())
        self.assertFalse(target.is_symlink())
        self.assertEqual(target, Path(sys.executable).resolve(strict=True))
