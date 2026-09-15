"""Synthetic byte/storage tests only; no Atlas imports or valid native execution.

The opaque fixtures are NOT generated Zstandard or accepted terrain checkpoints.
They exercise the recovery tool's declared byte-integrity boundary, not the native
codec, scientific commitments, runtime bindings or continuation behaviour.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch

from tools import r5_recovery as r


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='atlas-r5-recovery-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.live = self.root / 'live'
        self.runtime = self.root / 'runtime'
        self.live.mkdir()
        self.runtime.mkdir()
        (self.live / 'source').mkdir()
        (self.live / 'source/module.py').write_bytes(b'# Synthetic dependency, not native source.\n')
        (self.live / 'evidence.json').write_bytes(b'{"fixture_only":true}')
        (self.runtime / 'codec.dll').write_bytes(b'NOT A LIBRARY: opaque byte fixture')
        self.store = self.live / 'shared'
        (self.store / 'objects').mkdir(parents=True)
        self.frame = b'OPAQUE TEST BYTES: not a native compressed frame'
        self.frame_sha = sha(self.frame)
        self.object = self.store / 'objects' / (self.frame_sha + '.zst')
        self.object.write_bytes(self.frame)
        self.ref = {'schema': r.REF_SCHEMA, 'sequence': 1,
                    'path': 'objects/' + self.frame_sha + '.zst',
                    'raw_sha256': sha(b'fixture logical row'), 'raw_size_bytes': 19,
                    'frame_sha256': self.frame_sha, 'frame_size_bytes': len(self.frame),
                    'storage_schema': r.RAW_SCHEMA, 'storage_size_bytes': 19,
                    'summary': {'fixture_only': True}, 'codec': {'fixture_only': True}}
        self.record = {'storage_schema': r.CONTROL_SCHEMA,
                       'execution_binding': {'fixture_only': True, 'sources': {'unchanged': '0' * 64}},
                       'wrapper': {'envelope': {'body': {'fixture_only': True}}},
                       'history_store': {'schema': r.STORE_SCHEMA, 'path': str(self.store)},
                       'history_refs': [self.ref]}
        self.controls = [self.live / 'a/checkpoint.json', self.live / 'b/checkpoint.json']
        for control in self.controls:
            control.parent.mkdir()
            control.write_bytes(r.encoded(self.record))
        select = lambda alias, path: {'root': alias, 'path': path}
        self.plan = {
            'schema': r.PLAN_SCHEMA,
            'roots': {'workspace': str(self.live), 'runtime': str(self.runtime)},
            'controls': [select('workspace', 'a/checkpoint.json'), select('workspace', 'b/checkpoint.json')],
            'dependencies': {
                'source': {'paths': [select('workspace', 'source')], 'note': 'Synthetic source fixture only.'},
                'runtime': {'paths': [select('runtime', 'codec.dll')], 'note': 'Opaque library fixture; never loaded.'},
                'inputs': {'paths': [], 'note': 'No external inputs in this storage-only fixture.'},
                'provenance': {'paths': [select('workspace', 'evidence.json')], 'note': 'Synthetic evidence file only.'},
            },
        }
        self.bundle = self.root / 'bundle'
        self.restored = self.root / 'restored'

    def publish(self):
        return r.backup(self.plan, self.bundle, quiescent=True)['manifest_sha256']

    def write_control(self, record, index=0):
        self.controls[index].write_bytes(r.encoded(record))

    def assert_refused(self, operation):
        with self.assertRaises((r.RecoveryError, OSError)):
            operation()

    def rewrite_manifest(self, update):
        path = self.bundle / 'MANIFEST.json'
        manifest = r.decoded(path.read_bytes())
        update(manifest)
        raw = r.encoded(manifest)
        path.write_bytes(raw)
        digest = sha(raw)
        (self.bundle / 'COMPLETE.json').write_bytes(r.encoded({'schema': r.BUNDLE_SCHEMA, 'manifest_sha256': digest}))
        return digest

    def test_inventory_is_read_only_and_deduplicates_shared_references(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report = r.inventory(self.plan)
        frames = [row for row in report['files'] if 'frame' in row['roles']]
        self.assertEqual(len(frames), 1)
        self.assertEqual(len(report['controls']), 2)
        self.assertEqual(report['boundary'], r.BOUNDARY)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_backup_and_restore_exact_bytes_without_shared_file_aliases(self):
        original = [p.read_bytes() for p in self.controls]
        digest = self.publish()
        manifest = r.verify(self.bundle, digest)
        blobs = list((self.bundle / 'blobs').iterdir())
        self.assertEqual(len(blobs), len({row['sha256'] for row in manifest['files']}))
        result = r.restore(self.bundle, self.restored, digest)
        self.assertFalse(result['live_integration_performed'])
        for name, raw in zip(('a', 'b'), original):
            target = self.restored / f'workspace/{name}/checkpoint.json'
            self.assertEqual(target.read_bytes(), raw)
            self.assertEqual(json.loads(raw)['history_store']['path'], str(self.store))
            self.assertFalse(os.path.samefile(target, self.controls[0]))
        self.assertEqual([p.read_bytes() for p in self.controls], original)
        (self.restored / 'workspace/a/checkpoint.json').write_bytes(b'edit temporary recovery copy only')
        r.verify(self.bundle, digest)
        self.assertEqual(self.controls[0].read_bytes(), original[0])

    def test_self_contained_relative_store_layout_is_preserved(self):
        self.plan['controls'] = self.plan['controls'][:1]
        destination = self.controls[0].parent / 'store'
        shutil.copytree(self.store, destination)
        record = deepcopy(self.record)
        record['history_store']['path'] = 'store'
        self.write_control(record)
        digest = self.publish()
        r.restore(self.bundle, self.restored, digest)
        copied = self.restored / 'workspace/a/store/objects' / self.object.name
        self.assertEqual(copied.read_bytes(), self.frame)
        self.assertEqual((self.restored / 'workspace/a/checkpoint.json').read_bytes(), self.controls[0].read_bytes())

    def test_empty_history_retains_required_store_directory(self):
        self.plan['controls'] = self.plan['controls'][:1]
        record = deepcopy(self.record)
        record['history_refs'] = []
        self.write_control(record)
        self.object.unlink()
        digest = self.publish()
        r.restore(self.bundle, self.restored, digest)
        self.assertTrue((self.restored / 'workspace/shared').is_dir())

    def test_same_bytes_across_different_stores_are_packed_once(self):
        other = self.live / 'other'
        shutil.copytree(self.store, other)
        record = deepcopy(self.record)
        record['history_store']['path'] = str(other)
        self.write_control(record, 1)
        digest = self.publish()
        manifest = r.verify(self.bundle, digest)
        frames = [row for row in manifest['files'] if 'frame' in row['roles']]
        self.assertEqual(len(frames), 2)
        self.assertEqual(len([p for p in (self.bundle / 'blobs').iterdir() if p.name == self.frame_sha]), 1)
        r.restore(self.bundle, self.restored, digest)
        self.assertTrue((self.restored / 'workspace/other/objects' / self.object.name).is_file())

    def test_backup_remains_verifiable_after_original_files_are_removed(self):
        digest = self.publish()
        shutil.rmtree(self.live)
        shutil.rmtree(self.runtime)
        r.verify(self.bundle, digest)
        r.restore(self.bundle, self.restored, digest)
        self.assertEqual((self.restored / 'runtime/codec.dll').read_bytes(), b'NOT A LIBRARY: opaque byte fixture')

    def test_bundle_can_move_without_changing_manifest_hash(self):
        digest = self.publish()
        moved = self.root / 'moved'
        self.bundle.rename(moved)
        r.verify(moved, digest)
        r.restore(moved, self.restored, digest)

    def test_missing_frame_refused(self):
        self.object.unlink()
        self.assert_refused(lambda: r.inventory(self.plan))

    def test_corrupt_frame_refused(self):
        self.object.write_bytes(b'x' * len(self.frame))
        self.assert_refused(lambda: r.inventory(self.plan))

    def test_frame_size_mismatch_refused(self):
        record = deepcopy(self.record)
        record['history_refs'][0]['frame_size_bytes'] += 1
        self.write_control(record)
        self.assert_refused(lambda: r.inventory(self.plan))

    def test_invalid_reference_contracts_refused(self):
        updates = [
            ('sequence', True), ('sequence', 2), ('schema', 'old'), ('path', '../escape'),
            ('frame_sha256', '0' * 63), ('raw_sha256', 'g' * 64), ('raw_size_bytes', 0),
            ('raw_size_bytes', 32 * 1024 * 1024 + 1), ('storage_size_bytes', False),
            ('storage_size_bytes', 18), ('frame_size_bytes', 64 * 1024 * 1024 + 1),
            ('codec', []), ('summary', []), ('storage_schema', 'different'),
        ]
        for key, value in updates:
            with self.subTest(key=key, value=value):
                record = deepcopy(self.record)
                record['history_refs'][0][key] = value
                self.write_control(record)
                self.assert_refused(lambda: r.inventory(self.plan))

    def test_mixed_codec_and_reference_limit_refused(self):
        record = deepcopy(self.record)
        second = deepcopy(self.ref)
        second.update(sequence=2, codec={'different': True})
        record['history_refs'].append(second)
        self.write_control(record)
        self.assert_refused(lambda: r.inventory(self.plan))
        record['history_refs'] = [deepcopy(self.ref) for _ in range(257)]
        self.write_control(record)
        self.assert_refused(lambda: r.inventory(self.plan))

    def test_missing_empty_or_unknown_dependency_declaration_refused(self):
        for role in r.ROLES:
            plan = deepcopy(self.plan)
            del plan['dependencies'][role]
            self.assert_refused(lambda: r.inventory(plan))
        for role in ('source', 'runtime', 'provenance'):
            plan = deepcopy(self.plan)
            plan['dependencies'][role]['paths'] = []
            self.assert_refused(lambda: r.inventory(plan))
        plan = deepcopy(self.plan)
        plan['dependencies']['inputs']['note'] = ' '
        self.assert_refused(lambda: r.inventory(plan))

    def test_missing_or_empty_dependency_file_tree_refused(self):
        (self.live / 'source/module.py').unlink()
        self.assert_refused(lambda: r.inventory(self.plan))
        (self.runtime / 'codec.dll').unlink()
        self.assert_refused(lambda: r.inventory(self.plan))

    def test_duplicate_keys_nonfinite_json_and_oversized_controls_refused(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e9999}', b'\xff', b'[]'):
            with self.subTest(raw=raw):
                self.controls[0].write_bytes(raw)
                self.assert_refused(lambda: r.inventory(self.plan))
        self.controls[0].write_bytes(b' ' * 1025)
        with patch.object(r, 'MAX_CONTROL', 1024):
            self.assert_refused(lambda: r.inventory(self.plan))

    def test_inline_history_old_schema_and_wrapper_refused(self):
        for mutate in (lambda x: x.update(storage_schema='r4'), lambda x: x.update(wrapper=[]),
                       lambda x: x['wrapper']['envelope']['body'].update(history=[]),
                       lambda x: x.update(extra=True)):
            record = deepcopy(self.record)
            mutate(record)
            self.write_control(record)
            self.assert_refused(lambda: r.inventory(self.plan))

    def test_store_outside_allowlist_and_relative_traversal_refused(self):
        for location in ('../outside', str(self.root / 'outside'), str(self.live / '../outside')):
            record = deepcopy(self.record)
            record['history_store']['path'] = location
            self.write_control(record)
            self.assert_refused(lambda: r.inventory(self.plan))

    def test_unsafe_selection_paths_refused(self):
        for relative in ('../outside', '/absolute', 'a/../b', 'a//b', 'a/./b', 'a\\b', 'a:stream',
                         'con.txt', 'lpt1', 'x.', 'x ', 'a/\nfile', 'a/*', ''):
            with self.subTest(path=relative):
                plan = deepcopy(self.plan)
                plan['controls'][0]['path'] = relative
                self.assert_refused(lambda: r.inventory(plan))

    def test_overlapping_roots_or_duplicate_controls_refused(self):
        plan = deepcopy(self.plan)
        plan['roots']['nested'] = str(self.live / 'a')
        self.assert_refused(lambda: r.inventory(plan))
        plan = deepcopy(self.plan)
        plan['controls'].append(deepcopy(plan['controls'][0]))
        self.assert_refused(lambda: r.inventory(plan))

    def test_casefold_destination_collision_refused(self):
        if os.name == 'nt':
            self.skipTest('fixture requires case-sensitive names; manifest test covers Windows-safe refusal')
        (self.live / 'source/MODULE.py').write_bytes(b'other')
        self.assert_refused(lambda: r.inventory(self.plan))

    def test_symlink_files_directories_and_dangling_links_refused(self):
        if os.name == 'nt':
            self.skipTest('symlink privileges are not assumed; reparse-attribute test is portable')
        link = self.live / 'source/link'
        for target in (self.runtime / 'codec.dll', self.runtime, self.root / 'absent'):
            os.symlink(target, link)
            self.assert_refused(lambda: r.inventory(self.plan))
            link.unlink()

    def test_windows_reparse_attribute_refused(self):
        path = self.runtime / 'codec.dll'
        original = Path.lstat
        class Reparse:
            st_mode = stat.S_IFREG | 0o600
            st_file_attributes = 0x400
        def fake(current, *args, **kwargs):
            return Reparse() if current == path else original(current, *args, **kwargs)
        with patch.object(Path, 'lstat', fake):
            self.assert_refused(lambda: r.inventory(self.plan))

    def test_active_and_stale_writer_locks_refused_and_preserved(self):
        lock = self.controls[0].with_name('checkpoint.json.lock')
        lock.write_bytes(b'owner-token')
        self.assert_refused(lambda: r.inventory(self.plan))
        self.assert_refused(lambda: r.backup(self.plan, self.bundle, quiescent=True))
        self.assertEqual(lock.read_bytes(), b'owner-token')

    def test_explicit_quiescence_confirmation_required(self):
        self.assert_refused(lambda: r.backup(self.plan, self.bundle))
        self.assertFalse(self.bundle.exists())

    def test_output_overlap_and_existing_destination_refused(self):
        self.assert_refused(lambda: r.backup(self.plan, self.live / 'backup', quiescent=True))
        self.bundle.mkdir()
        marker = self.bundle / 'do-not-touch'
        marker.write_bytes(b'previous result')
        self.assert_refused(lambda: r.backup(self.plan, self.bundle, quiescent=True))
        self.assertEqual(marker.read_bytes(), b'previous result')

    def test_stale_publication_lock_not_removed(self):
        lock = self.root / 'bundle.recovery-lock'
        lock.write_bytes(b'stale-token')
        self.assert_refused(lambda: r.backup(self.plan, self.bundle, quiescent=True))
        self.assertEqual(lock.read_bytes(), b'stale-token')
        self.assertFalse(self.bundle.exists())

    def test_insufficient_space_refused_without_publication(self):
        with patch.object(r.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(100, 100, 0)):
            self.assert_refused(lambda: r.backup(self.plan, self.bundle, quiescent=True))
        self.assertFalse(self.bundle.exists())

    def test_changed_control_during_copy_not_published(self):
        original = r._hash
        changed = False
        def copy(path, destination=None):
            nonlocal changed
            result = original(path, destination)
            if destination is not None and not changed:
                changed = True
                data = deepcopy(self.record)
                data['wrapper']['envelope']['body']['changed'] = True
                self.write_control(data)
            return result
        with patch.object(r, '_hash', side_effect=copy):
            self.assert_refused(lambda: r.backup(self.plan, self.bundle, quiescent=True))
        self.assertFalse(self.bundle.exists())
        self.assertTrue(list(self.root.glob('.bundle.incomplete-*')))

    def test_added_dependency_during_copy_not_published(self):
        original = r._hash
        def copy(path, destination=None):
            result = original(path, destination)
            if destination is not None:
                (self.live / 'source/new.py').write_bytes(b'changed selected file set')
            return result
        with patch.object(r, '_hash', side_effect=copy):
            self.assert_refused(lambda: r.backup(self.plan, self.bundle, quiescent=True))
        self.assertFalse(self.bundle.exists())

    def test_injected_write_failure_and_interrupt_leave_no_published_bundle(self):
        original = r._write
        def fail(path, raw):
            if path.name == 'MANIFEST.json':
                raise OSError('injected disk-write failure')
            return original(path, raw)
        with patch.object(r, '_write', side_effect=fail):
            self.assert_refused(lambda: r.backup(self.plan, self.bundle, quiescent=True))
        self.assertFalse(self.bundle.exists())
        with patch.object(r, 'verify', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                r.backup(self.plan, self.bundle, quiescent=True)
        self.assertFalse(self.bundle.exists())
        self.assertFalse((self.root / 'bundle.recovery-lock').exists())

    def test_wrong_external_digest_and_tampered_manifest_refused(self):
        digest = self.publish()
        self.assert_refused(lambda: r.verify(self.bundle, '0' * 64))
        (self.bundle / 'MANIFEST.json').write_bytes((self.bundle / 'MANIFEST.json').read_bytes() + b' ')
        self.assert_refused(lambda: r.verify(self.bundle, digest))
        self.assert_refused(lambda: r.restore(self.bundle, self.restored, digest))
        self.assertFalse(self.restored.exists())

    def test_missing_marker_and_corrupt_blob_refused(self):
        digest = self.publish()
        marker = (self.bundle / 'COMPLETE.json').read_bytes()
        (self.bundle / 'COMPLETE.json').unlink()
        self.assert_refused(lambda: r.verify(self.bundle, digest))
        (self.bundle / 'COMPLETE.json').write_bytes(marker)
        (self.bundle / 'blobs' / self.frame_sha).write_bytes(b'corrupt')
        self.assert_refused(lambda: r.verify(self.bundle, digest))

    def test_manifest_path_traversal_collision_and_boundary_lies_refused(self):
        digest = self.publish()
        original = (self.bundle / 'MANIFEST.json').read_bytes()
        def check(update):
            (self.bundle / 'MANIFEST.json').write_bytes(original)
            altered = self.rewrite_manifest(update)
            self.assert_refused(lambda: r.verify(self.bundle, altered))
        check(lambda x: x['files'][0].update(path='../outside'))
        check(lambda x: x['files'].append(deepcopy(x['files'][0])))
        check(lambda x: x['boundary'].update(native_runtime_verified=True))
        check(lambda x: x['controls'][0].update(history_references=9))

    def test_file_directory_prefix_collision_refused(self):
        self.publish()
        def change(manifest):
            row = deepcopy(manifest['files'][0])
            row['path'] += '/child'
            manifest['files'].append(row)
        digest = self.rewrite_manifest(change)
        self.assert_refused(lambda: r.verify(self.bundle, digest))

    def test_case_ambiguous_manifest_refused_on_every_platform(self):
        self.publish()
        def change(manifest):
            row = deepcopy(manifest['files'][0])
            row['path'] = row['path'].upper()
            manifest['files'].append(row)
        digest = self.rewrite_manifest(change)
        self.assert_refused(lambda: r.verify(self.bundle, digest))

    def test_manifest_cannot_omit_referenced_frame(self):
        self.publish()
        digest = self.rewrite_manifest(lambda x: x.update(files=[row for row in x['files'] if 'frame' not in row['roles']]))
        self.assert_refused(lambda: r.verify(self.bundle, digest))

    def test_foreign_windows_paths_are_resolved_lexically_not_accessed(self):
        roots = {'workspace': r'C:\Atlas', 'runtime': r'D:\Runtime'}
        data = deepcopy(self.record)
        data['history_store']['path'] = r'C:\Atlas\shared'
        expected = []
        info = r._control(r.encoded(data), ('workspace', 'a/checkpoint.json'), roots,
                          lambda *args: expected.append(args))
        self.assertEqual(info['store'], {'root': 'workspace', 'path': 'shared'})
        self.assertEqual(expected[0][0], ('workspace', 'shared/objects/' + self.frame_sha + '.zst'))
        if os.name != 'nt':
            plan = deepcopy(self.plan)
            plan['roots'] = roots
            self.assert_refused(lambda: r.inventory(plan))

    def test_bundle_verify_and_staged_restore_with_windows_origin_on_posix(self):
        if os.name == 'nt':
            self.skipTest('cross-platform fixture specifically targets POSIX staging')
        self.publish()
        manifest = r.decoded((self.bundle / 'MANIFEST.json').read_bytes())
        manifest['plan']['roots'] = {'workspace': r'C:\Atlas', 'runtime': r'D:\Runtime'}
        record = deepcopy(self.record)
        record['history_store']['path'] = r'C:\Atlas\shared'
        raw = r.encoded(record)
        digest = sha(raw)
        (self.bundle / 'blobs' / digest).write_bytes(raw)
        for entry in manifest['files']:
            if 'control' in entry['roles']:
                entry.update(sha256=digest, size_bytes=len(raw))
        raw_manifest = r.encoded(manifest)
        expected = sha(raw_manifest)
        (self.bundle / 'MANIFEST.json').write_bytes(raw_manifest)
        (self.bundle / 'COMPLETE.json').write_bytes(r.encoded({'schema': r.BUNDLE_SCHEMA, 'manifest_sha256': expected}))
        r.verify(self.bundle, expected)
        r.restore(self.bundle, self.restored, expected)
        self.assertEqual((self.restored / 'workspace/a/checkpoint.json').read_bytes(), raw)

    def test_restore_existing_live_or_bundle_paths_refused(self):
        digest = self.publish()
        for destination in (self.bundle / 'restore', self.live / 'restore', self.root):
            self.assert_refused(lambda: r.restore(self.bundle, destination, digest))
        self.restored.mkdir()
        (self.restored / 'preserve').write_bytes(b'unchanged')
        self.assert_refused(lambda: r.restore(self.bundle, self.restored, digest))
        self.assertEqual((self.restored / 'preserve').read_bytes(), b'unchanged')

    def test_changed_backup_during_restore_not_published(self):
        digest = self.publish()
        original = r._hash
        def copy(path, destination=None):
            result = original(path, destination)
            if destination is not None:
                (self.bundle / 'blobs' / self.frame_sha).write_bytes(b'corrupt during restore')
            return result
        with patch.object(r, '_hash', side_effect=copy):
            self.assert_refused(lambda: r.restore(self.bundle, self.restored, digest))
        self.assertFalse(self.restored.exists())

    def test_injected_restore_failure_not_published(self):
        digest = self.publish()
        original = r._write
        def fail(path, raw):
            if path.name == 'RESTORE_RECEIPT.json':
                raise OSError('injected receipt-write failure')
            return original(path, raw)
        with patch.object(r, '_write', side_effect=fail):
            self.assert_refused(lambda: r.restore(self.bundle, self.restored, digest))
        self.assertFalse(self.restored.exists())
        r.verify(self.bundle, digest)

    def test_file_count_limit(self):
        with patch.object(r, 'MAX_FILES', 3):
            self.assert_refused(lambda: r.inventory(self.plan))

    def test_known_absolute_source_and_library_pins_verified(self):
        data = deepcopy(self.record)
        source = self.live / 'source/module.py'
        library = self.runtime / 'codec.dll'
        data['execution_binding'] = {
            'sources': {str(source): sha(source.read_bytes())},
            'compression': {'library_path': str(library), 'library_sha256': sha(library.read_bytes())},
        }
        self.write_control(data)
        digest = self.publish()
        manifest = r.verify(self.bundle, digest)
        pins = manifest['controls'][0]['dependency_pins']
        self.assertEqual(pins['recognised_absolute_pins_verified'], 2)
        self.assertFalse(pins['full_native_binding_validation_performed'])

    def test_bound_library_mismatch_is_not_silently_rebound(self):
        data = deepcopy(self.record)
        data['execution_binding']['compression'] = {
            'library_path': str(self.runtime / 'codec.dll'), 'library_sha256': '0' * 64}
        self.write_control(data)
        before = self.controls[0].read_bytes()
        self.assert_refused(lambda: r.backup(self.plan, self.bundle, quiescent=True))
        self.assertFalse(self.bundle.exists())
        self.assertEqual(self.controls[0].read_bytes(), before)

    def test_bound_source_not_selected_or_outside_roots_refused(self):
        data = deepcopy(self.record)
        for source in (self.live / 'not-selected.py', self.root / 'outside.py'):
            source.write_bytes(b'not selected')
            data['execution_binding']['sources'] = {str(source): sha(source.read_bytes())}
            self.write_control(data)
            self.assert_refused(lambda: r.inventory(self.plan))

    def test_relative_source_pins_are_explicitly_unresolved(self):
        report = r.inventory(self.plan)
        pins = report['controls'][0]['dependency_pins']
        self.assertEqual(pins['relative_source_pins_not_resolved'], 1)
        self.assertFalse(pins['full_native_binding_validation_performed'])

    def test_non_regular_dependency_is_refused_without_opening_it(self):
        if not hasattr(os, 'mkfifo'):
            self.skipTest('POSIX FIFO fixture is not available on this host')
        os.mkfifo(self.live / 'source/pipe')
        self.assert_refused(lambda: r.inventory(self.plan))

    def test_tool_imports_only_standard_library_and_never_atlas(self):
        import ast
        import sys
        tree = ast.parse(Path(r.__file__).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split('.')[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or '').split('.')[0]]
            else:
                continue
            for name in names:
                self.assertIn(name, sys.stdlib_module_names)
        self.assertFalse(any(name == 'work' or name.startswith('work.') for name in sys.modules))

    def test_cli_inventory_backup_verify_restore_and_nonzero_refusal(self):
        path = self.root / 'plan.json'
        path.write_bytes(r.encoded(self.plan))
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(r.main(['inventory', '--plan', str(path)]), 0)
        self.assertEqual(json.loads(output.getvalue())['boundary'], r.BOUNDARY)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(r.main(['backup', '--plan', str(path), '--destination', str(self.bundle), '--quiescent']), 0)
        digest = json.loads(output.getvalue())['manifest_sha256']
        for command in ('verify', 'restore'):
            arguments = [command, '--bundle', str(self.bundle), '--expected-manifest-sha256', digest]
            if command == 'restore':
                arguments += ['--destination', str(self.restored)]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(r.main(arguments), 0)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(r.main(['verify', '--bundle', str(self.bundle), '--expected-manifest-sha256', '0' * 64]), 2)


if __name__ == '__main__':
    unittest.main()
