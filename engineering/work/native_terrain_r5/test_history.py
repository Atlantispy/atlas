"""Focused shared-frame storage checks, without numerical model execution."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from work.native_terrain_r3 import history as old
from work.native_terrain_r3.test_history import row
from . import history as h


class SharedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='native-r5-history-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = old.History.from_rows(self.root / 'old', [row(), row(2)])
        self.store = self.root / 'store'

    def test_import_reuses_exact_objects_without_recompression_or_rewrite(self):
        with patch.object(h.compression, 'encode', side_effect=AssertionError('import recompressed a frame')):
            first = h.History.from_history(self.source, self.store)
            objects = {ref['path']: (self.store / ref['path']).stat() for ref in first.refs}
            with patch.object(old.os, 'link', side_effect=AssertionError('existing frame rewritten')):
                second = h.History.from_history(self.source, self.store)
        self.assertEqual(first.refs, second.refs)
        self.assertEqual(len(list((self.store / 'objects').iterdir())), len(self.source))
        for old_ref, ref in zip(self.source.refs, first.refs):
            self.assertEqual(ref['path'], 'objects/' + ref['frame_sha256'] + '.zst')
            source_path, target = self.source.root / old_ref['path'], self.store / ref['path']
            self.assertEqual(target.read_bytes(), source_path.read_bytes())
            self.assertEqual((target.stat().st_ino, target.stat().st_mtime_ns),
                             (objects[ref['path']].st_ino, objects[ref['path']].st_mtime_ns))
            self.assertNotEqual(target.stat().st_ino, source_path.stat().st_ino)
        self.assertEqual(first.materialize(), self.source.materialize())

    def test_independent_append_and_summary_views_preserve_shared_prefix(self):
        first = h.History.from_history(self.source, self.store)
        second = deepcopy(first)
        prefix = first.refs
        self.assertIs(first._entries, second._entries)
        second.append(row(3))
        self.assertEqual(first.refs, prefix)
        self.assertEqual(second.refs[:len(first)], prefix)
        self.assertEqual((len(first), len(second), len(self.source)), (2, 3, 2))
        exposed = first[0]
        exposed['diagnostics']['extra'].append('untrusted mutation')
        self.assertNotEqual(exposed, first[0])
        self.assertEqual(list(first), first[:])
        self.assertFalse(hasattr(first._entries[0], '__dict__'))
        for name in ('_root', '_entries', '_codec_bytes'):
            with self.assertRaises(AttributeError):
                setattr(first, name, None)
            with self.assertRaises(AttributeError):
                delattr(first, name)

    def test_independent_concurrent_publication_has_one_closed_object(self):
        histories = [h.History(self.store) for _ in range(3)]
        barrier = Barrier(len(histories))
        def publish(path, frame):
            barrier.wait(timeout=10)
            return old._immutable(path, frame)
        with patch.object(h, '_immutable', side_effect=publish):
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(lambda history: history.append(row(3)), histories))
        self.assertEqual(len(list((self.store / 'objects').iterdir())), 1)
        for history in histories:
            self.assertEqual(history.refs, histories[0].refs)
            self.assertEqual(history.materialize(), histories[0].materialize())

    def test_object_identity_is_independent_of_sequence_and_store_root(self):
        first = h.History.from_history(self.source, self.store)
        other = h.History.from_rows(self.root / 'another', [row(2)])
        self.assertEqual(first.refs[1]['path'], other.refs[0]['path'])
        self.assertNotEqual(first.refs[1]['sequence'], other.refs[0]['sequence'])
        with patch.object(h.compression, 'encode', side_effect=AssertionError('copy recompressed')):
            same_store = h.History.from_history(first, self.store)
            exported = h.History.from_history(first, self.root / 'exported')
        self.assertIsNot(same_store, first)
        self.assertEqual(first.refs, same_store.refs)
        self.assertEqual(first.refs, exported.refs)
        self.assertEqual(exported.materialize(), first.materialize())

    def test_missing_or_changed_object_is_never_silently_repaired_or_overwritten(self):
        history = h.History.from_history(self.source, self.store)
        path = self.store / history.refs[0]['path']
        before, info = path.read_bytes(), path.stat()
        corrupt = bytearray(before)
        corrupt[-1] ^= 1
        path.write_bytes(corrupt)
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        for action in (lambda: list(history.iter_raw()),
                       lambda: h.History.from_refs(self.store, history.refs),
                       lambda: h.History.from_history(self.source, self.store),
                       lambda: history.append(row())):
            with self.subTest(action=action), self.assertRaises(ValueError):
                action()
        self.assertEqual(path.read_bytes(), corrupt)
        self.assertEqual(len(history), 2)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            list(history.iter_raw())
        with self.assertRaises(FileNotFoundError):
            h.History.from_refs(self.store, history.refs)

    def test_import_authenticates_full_source_row_and_summary(self):
        forged = deepcopy(self.source)
        object.__setattr__(forged, '_entries', (replace(forged._entries[0], summary_bytes=b'{}'),))
        with self.assertRaisesRegex(ValueError, 'summary differs'):
            h.History.from_history(forged, self.store)
        self.assertEqual(list((self.store / 'objects').iterdir()), [])
        path = self.source.root / self.source.refs[0]['path']
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'frame hash differs'):
            h.History.from_history(self.source, self.store)

    def test_reference_shape_path_order_codec_and_summary_fail_closed(self):
        history = h.History.from_history(self.source, self.store)
        changes = [lambda refs: refs.reverse(),
            lambda refs: refs[0].update(schema=old.REF_SCHEMA),
            lambda refs: refs[0].update(path='../outside.zst'),
            lambda refs: refs[0].update(path='objects/' + '0' * 64 + '.zst'),
            lambda refs: refs[0].update(raw_sha256='0' * 64),
            lambda refs: refs[0].update(frame_size_bytes=True),
            lambda refs: refs[0].update(storage_size_bytes=1),
            lambda refs: refs[0]['summary'].update(operation_id='forged'),
            lambda refs: refs[0]['codec'].update(version='unbound'),
            lambda refs: refs[0].update(extra='ambiguous')]
        for index, change in enumerate(changes):
            refs = history.refs
            change(refs)
            with self.subTest(index=index), self.assertRaises(ValueError):
                h.History.from_refs(self.store, refs)

    def test_full_restart_parses_rows_but_hot_iteration_does_not(self):
        history = h.History.from_history(self.source, self.store)
        refs = history.refs
        with patch.object(h, '_parse', side_effect=AssertionError('logical row reparsed')):
            self.assertEqual(list(history.iter_raw()), list(self.source.iter_raw()))
        with patch.object(h, '_parse', wraps=h._parse) as parse:
            restored = h.History.from_refs(self.store, refs)
            self.assertGreaterEqual(parse.call_count, len(history))
        self.assertEqual(restored.refs, refs)

    def test_bounds_source_codec_and_predecessor_overlap_protection(self):
        history = h.History.from_history(self.source, self.store)
        for destination in (self.source.root, self.source.root / 'nested', self.root):
            with self.subTest(destination=destination), self.assertRaisesRegex(ValueError, 'overlap'):
                h.History.from_history(self.source, destination)
        with self.assertRaises(ValueError):
            h.History(self.root / '..' / 'outside')
        for module in (h, old):
            with patch.object(module, '_R12_EXECUTED_SHA256', '0' * 64):
                with self.assertRaises(ValueError):
                    history.refs
        with patch.object(h.compression, '_digest', return_value='0' * 64):
            with self.assertRaises(ValueError):
                list(history.iter_raw())
        with patch.object(h, 'MAX_ROWS', len(history)):
            with self.assertRaises(ValueError):
                history.append(row(3))
            with self.assertRaises(ValueError):
                h.History.from_refs(self.store, history.refs * 2)
        empty = h.History.from_rows(self.root / 'empty', [])
        self.assertEqual((len(empty), empty.refs, list(empty.iter_raw())), (0, [], []))

    def test_fresh_process_shared_reference_roundtrip(self):
        history = h.History.from_history(self.source, self.store)
        refs_path = self.root / 'refs.json'
        refs_path.write_bytes(h._encoded(history.refs))
        code = ('import hashlib,json; from pathlib import Path; '
            'from work.native_terrain_r5.history import History; '
            'root=Path(' + repr(str(self.store)) + '); '
            'refs=json.loads(Path(' + repr(str(refs_path)) + ').read_bytes()); '
            'history=History.from_refs(root,refs); '
            'print(json.dumps([hashlib.sha256(raw).hexdigest() for raw in history.iter_raw()]))')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        result = subprocess.run([sys.executable, '-B', '-c', code], check=True,
            capture_output=True, text=True, timeout=30, cwd=Path(__file__).resolve().parents[2], **options)
        self.assertEqual(json.loads(result.stdout), [ref['raw_sha256'] for ref in history.refs])


if __name__ == '__main__':
    unittest.main(verbosity=2)
