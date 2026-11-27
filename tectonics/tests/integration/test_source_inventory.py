"""Complete byte-derived package identities with bounded retained representation."""
from contextlib import contextmanager
import hashlib
import json
import marshal
import os
import stat
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from atlas_tectonics.integration import reuse
from atlas_tectonics._validation import TectonicsError


class SourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.real_roots = reuse._source_roots()
        patcher = mock.patch.object(reuse, '_source_roots', return_value=(('', self.root),))
        patcher.start()
        self.addCleanup(patcher.stop)

    def put(self, name, raw):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def encoded(self, inventory):
        return reuse._json({'schema': 'atlas.package-source-digests.v1',
                            'files': {k: json.loads(v) for k, v in inventory.items()}})

    def test_complete_nested_membership_and_independent_digests(self):
        sources = {'empty.py': b'', 'nested/\u00e9.py': b'x = 1\r\n', 'unit.py': bytes(range(256))}
        for name, raw in sources.items():
            self.put(name, raw)
        self.put('not-source.txt', b'unrelated')
        inventory = reuse._source_bytes()
        self.assertEqual(list(inventory), sorted(sources))
        self.assertEqual({name: json.loads(record) for name, record in inventory.items()},
            {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
             for name, raw in sources.items()})
        self.assertEqual(inventory, reuse._source_bytes())

    def test_raw_source_over_two_mib_is_complete_and_streamed(self):
        raw = bytes(range(256))*(2*1024**2//256+257)
        path = self.put('large.py', raw)
        reads = []
        opener = Path.open
        class ObservedStream:
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def fileno(self): return self.stream.fileno()
            def readinto(self, view):
                count = self.stream.readinto(view)
                reads.append((len(view), count))
                return count
        def opened(current, *args, **kwargs):
            result = ObservedStream()
            result.stream = opener(current, *args, **kwargs)
            return result
        with mock.patch.object(Path, 'open', opened):
            inventory = reuse._source_bytes()
        self.assertEqual(sum(count for _, count in reads), len(raw))
        self.assertLessEqual(max(size for size, _ in reads), 64*1024)
        self.assertEqual(json.loads(inventory[path.name]),
            {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        self.assertLess(len(self.encoded(inventory)), 256)

    def test_empty_file_add_remove_and_rename_change_identity(self):
        path = self.put('original.py', b'')
        original = reuse._source_bytes()
        extra = self.put('extra.py', b'')
        self.assertNotEqual(original, reuse._source_bytes())
        extra.unlink()
        path.rename(self.root/'renamed.py')
        self.assertNotEqual(original, reuse._source_bytes())
        (self.root/'renamed.py').unlink()
        self.assertNotEqual(original, reuse._source_bytes())

    def test_expanded_file_limit_is_bounded_and_never_truncates(self):
        self.assertEqual(reuse._SOURCE_FILES, 512)
        self.assertEqual(reuse._SOURCE_CONTEXT_BYTES, 2*1024**2)
        for index in range(512):
            self.put(f'{index:03}.py', b'')
        self.assertEqual(len(reuse._source_bytes()), 512)
        self.put('overflow.py', b'')
        with mock.patch.object(Path, 'open', side_effect=AssertionError('inventory should refuse before reading')):
            with self.assertRaisesRegex(TectonicsError, 'context budget'):
                reuse._source_bytes()

    def test_encoded_limit_includes_schema_names_counts_digests_and_punctuation(self):
        self.put('nested/\u00e9.py', b'a')
        self.put('other.py', b'b')
        inventory = reuse._source_bytes()
        size = len(self.encoded(inventory))
        with mock.patch.object(reuse, '_SOURCE_CONTEXT_BYTES', size):
            self.assertEqual(inventory, reuse._source_bytes())
        with mock.patch.object(reuse, '_SOURCE_CONTEXT_BYTES', size-1):
            with self.assertRaisesRegex(TectonicsError, 'context budget'):
                reuse._source_bytes()

    def test_empty_inventory_schema_also_obeys_cap(self):
        size = len(self.encoded({}))
        with mock.patch.object(reuse, '_SOURCE_CONTEXT_BYTES', size):
            self.assertEqual(reuse._source_bytes(), {})
        with mock.patch.object(reuse, '_SOURCE_CONTEXT_BYTES', size-1):
            with self.assertRaisesRegex(TectonicsError, 'context budget'):
                reuse._source_bytes()

    def test_growth_during_capture_refuses_without_reading_forever(self):
        path = self.put('unit.py', b'x'*100)
        opener = Path.open
        class GrowingStream:
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def fileno(self): return self.stream.fileno()
            def readinto(self, view):
                count = self.stream.readinto(view)
                if count:
                    with opener(path, 'ab') as writer:
                        writer.write(b'y'*100)
                return count
        def opened(current, *args, **kwargs):
            result = GrowingStream()
            result.stream = opener(current, *args, **kwargs)
            return result
        with mock.patch.object(Path, 'open', opened):
            with self.assertRaisesRegex(TectonicsError, 'source changed during'):
                reuse._source_bytes()

    def test_replacement_between_path_check_and_open_refuses(self):
        path = self.put('unit.py', b'x = 1\n')
        replacement = self.put('replacement.txt', b'x = 1\n')
        stamp = path.stat()
        os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        opener = Path.open
        def opened(current, *args, **kwargs):
            if current == path:
                os.replace(replacement, path)
            return opener(current, *args, **kwargs)
        with mock.patch.object(Path, 'open', opened):
            with self.assertRaisesRegex(TectonicsError, 'source changed during'):
                reuse._source_bytes()

    def test_nonregular_source_refuses_before_open(self):
        path = self.put('unit.py', b'anything')
        original = Path.lstat
        def linked(current, *args, **kwargs):
            result = original(current, *args, **kwargs)
            if current == path:
                values = list(result)
                values[0] = stat.S_IFLNK | 0o777
                return os.stat_result(values)
            return result
        with mock.patch.object(Path, 'lstat', linked), mock.patch.object(
                Path, 'open', side_effect=AssertionError('must refuse before opening')):
            with self.assertRaisesRegex(TectonicsError, 'unavailable or linked'):
                reuse._source_bytes()

    def test_link_replacement_after_read_refuses(self):
        path = self.put('unit.py', b'anything')
        original = Path.lstat
        calls = 0
        def switched(current, *args, **kwargs):
            nonlocal calls
            result = original(current, *args, **kwargs)
            if current == path:
                calls += 1
                if calls == 2:
                    values = list(result)
                    values[0] = stat.S_IFLNK | 0o777
                    return os.stat_result(values)
            return result
        with mock.patch.object(Path, 'lstat', switched):
            with self.assertRaisesRegex(TectonicsError, 'source changed during'):
                reuse._source_bytes()


if __name__ == '__main__':
    unittest.main()
