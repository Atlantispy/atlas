"""Interpreter links are supported without weakening scientific input checks."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from atlas_tectonics import TectonicsError
from atlas_tectonics.integration import reuse


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
        with self.assertRaisesRegex(TectonicsError, 'unavailable or linked'):
            reuse._source_bytes((('', self.root),))

    def test_runtime_identity_omits_absolute_path(self):
        record = self.record(self.binary)
        self.assertNotIn(str(self.root), reuse._json(record).decode())
