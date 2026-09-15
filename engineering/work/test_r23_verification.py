"""Focused fresh-byte/source-identity regression; no scientific runs."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from work.generator_upgrade_r22 import provenance as parent
from work.generator_upgrade_r23 import provenance as local
from work.generator_upgrade_r23.verification import Binding, LIMIT, verify_files


class VerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.identity = parent.identity()

    def test_live_binding_and_defensive_identity(self):
        binding = Binding(self.identity)
        exposed = binding.identity
        exposed['sources'].clear()
        binding.verify()
        self.assertEqual(binding.identity, parent.identity())
        self.assertEqual(binding.metrics['verification_calls'], 1)
        unsupported = binding.identity
        unsupported['moving_ground'] = {}
        with self.assertRaisesRegex(ValueError, 'moving-ground binding'):
            Binding(unsupported)

    def test_byte_change_with_same_size_and_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'source.py'
            path.write_bytes(b'a = 1\n')
            original = path.stat()
            pins = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()}
            verify_files(pins)
            path.write_bytes(b'a = 2\n')
            os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
            with self.assertRaisesRegex(ValueError, 'source changed; no silent rebind'):
                verify_files(pins)

    def test_new_missing_inventory_and_conflicting_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'source.py'
            path.write_bytes(b'a = 1\n')
            pins = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()}
            inventory = {str(root): [str(path)]}
            verify_files(pins, inventory)
            new = root/'extra.py'
            new.write_bytes(b'')
            with self.assertRaisesRegex(ValueError, 'inventory changed'):
                verify_files(pins, inventory)
            new.unlink()
            path.unlink()
            with self.assertRaisesRegex(ValueError, 'inventory changed'):
                verify_files(pins, inventory)
        name, digest = next(iter(self.identity['sources'].items()))
        changed = ('0' if digest[0] != '0' else '1')+digest[1:]
        with self.assertRaisesRegex(ValueError, 'conflicting source pins'):
            Binding(self.identity, extra_sources={name: changed})

    def test_module_capture_and_runtime_drift(self):
        binding = Binding(self.identity)
        with mock.patch.object(parent, '_R12_EXECUTED_SHA256', '0'*64):
            with self.assertRaisesRegex(ValueError, 'executed source differs'):
                binding.verify()
        with mock.patch.dict(os.environ, {'OMP_NUM_THREADS': 'r23-changed-value'}):
            with self.assertRaisesRegex(ValueError, 'runtime changed'):
                binding.verify()
        sources = local.sources()
        own_binding = Binding(self.identity, extra_sources=sources,
                              extra_inventory={str(local.HERE): sorted(sources)})
        injected = SimpleNamespace(__file__=str(local.HERE/'missing.py'),
                                   _R12_EXECUTED_SHA256='0'*64)
        with mock.patch.dict(sys.modules, {'work.generator_upgrade_r23.injected': injected}):
            with self.assertRaisesRegex(ValueError, 'executed source differs'):
                own_binding.verify()

    def test_unsafe_path_size_and_link(self):
        with self.assertRaisesRegex(ValueError, 'absolute non-traversing'):
            verify_files({'relative.py': '0'*64})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'source.py'
            with path.open('wb') as handle:
                handle.truncate(LIMIT+1)
            with self.assertRaisesRegex(ValueError, 'bounded unlinked regular'):
                verify_files({str(path): '0'*64})
            path.write_bytes(b'')
            linked = root/'linked.py'
            try:
                os.link(path, linked)
            except OSError:
                return
            with self.assertRaisesRegex(ValueError, 'bounded unlinked regular'):
                verify_files({str(linked): hashlib.sha256(b'').hexdigest()})

    def test_replacement_growth_and_extra_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'source.py'
            path.write_bytes(b'pass\n')
            pins = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()}
            binding = Binding(self.identity, extra_sources=pins,
                              extra_inventory={str(root): [str(path)]})
            binding.verify()
            original_fstat = os.fstat
            grew = False
            def changed_fstat(descriptor):
                nonlocal grew
                info = original_fstat(descriptor)
                if not grew:
                    grew = True
                    with path.open('ab') as handle:
                        handle.write(b'# grew\n')
                return info
            with mock.patch('os.fstat', side_effect=changed_fstat):
                with self.assertRaisesRegex(ValueError, 'source changed while reading'):
                    verify_files(pins)
            path.write_bytes(b'pass\n')
            original_open = os.open
            def changed_open(name, flags, *args, **kwargs):
                if Path(name) == path:
                    replacement = root/'replacement.tmp'
                    replacement.write_bytes(b'pass\n')
                    os.replace(replacement, path)
                return original_open(name, flags, *args, **kwargs)
            with mock.patch('os.open', side_effect=changed_open):
                with self.assertRaisesRegex(ValueError, 'source changed while opening'):
                    verify_files(pins)


if __name__ == '__main__':
    unittest.main()
