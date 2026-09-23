"""Complete byte-derived package identities with bounded retained representation."""
import hashlib
import json
import marshal
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from atlas_tectonics import reuse
from atlas_tectonics._validation import TectonicsError


class SourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = mock.patch.object(reuse, '__file__', str(self.root/'reuse.py'))
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

    def test_last_byte_change_same_size_and_mtime_is_refused(self):
        raw = b'x'*(2*1024**2)+b'1'
        path = self.put('large.py', raw)
        before = path.stat()
        with reuse.ExecutionContext() as context:
            try:
                path.write_bytes(raw[:-1]+b'2')
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                self.assertEqual(path.stat().st_size, before.st_size)
                self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
                with self.assertRaisesRegex(TectonicsError, 'source changed'):
                    context.verify()
            finally:
                path.write_bytes(raw)

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

    def test_file_limit_is_unchanged_and_never_truncates(self):
        self.assertEqual(reuse._SOURCE_FILES, 128)
        self.assertEqual(reuse._SOURCE_CONTEXT_BYTES, 2*1024**2)
        for index in range(128):
            self.put(f'{index:03}.py', b'')
        self.assertEqual(len(reuse._source_bytes()), 128)
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


class IdentityVersionTests(unittest.TestCase):
    def test_v3_identity_is_distinct_and_refused_by_existing_checkpoint_gate(self):
        from atlas_tectonics.w07_workflow import PreparedW07Workflow, _hash
        from test_w07_workflow import make_workflow_fixture
        # Reconstruct the actual prior record format from current complete source
        # bytes and loaded instructions: even these cannot become a v4 binding.
        with reuse.ExecutionContext('scipy') as context:
            signatures, _, constants = reuse._callable_inventory('scipy')
            loaded = {key: {'code': reuse._digest(marshal.dumps(reuse._normal_code(code), 2)),
                            'defaults': reuse._digest(reuse._json(defaults))}
                      for key, (code, defaults) in signatures.items()}
            root = Path(reuse.__file__).parent
            sources = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in root.rglob('*.py')}
            legacy = reuse._digest(reuse._json({'schema': 'atlas.kernel-execution.v3',
                'code_marshal_format': 2, 'backend': 'scipy', 'sources': sources,
                'loaded_code': loaded, 'constants': reuse._digest(constants), 'runtime': context._runtime}))
            self.assertNotEqual(context.identity, legacy)
        with make_workflow_fixture('steady') as workflow:
            result = workflow.run()
            _, header = workflow._pack(result, None)
            workflow._header(0, header, None)
            header['execution'] = legacy
            header['content_id'] = _hash({k: v for k, v in header.items() if k != 'content_id'})
            with self.assertRaisesRegex(TectonicsError, 'checkpoint source/schedule/parent mismatch'):
                PreparedW07Workflow._header(workflow, 0, header, None)


if __name__ == '__main__':
    unittest.main()
