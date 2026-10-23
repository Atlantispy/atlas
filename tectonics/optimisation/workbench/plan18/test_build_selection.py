"""Disposable standard-library controls; never import the selected Atlas sources."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import build_selection as B


class ConstructionBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='plan18-builder-control-')
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.output = self.repo / 'built'
        self.retained = 'source/src/atlas_tectonics/base.py'
        parent = []
        for member in sorted(B.REPLACEMENTS | {self.retained}):
            relative = 'previous/' + member
            data = ('# previous ' + member + '\n').encode()
            self.write(relative, data)
            parent.append(dict(member=member, public_path=relative, public_sha256=B.digest(data)))
        parent_bytes = self.encode(dict(entries=parent))
        self.write(B.PARENT, parent_bytes)
        self.entries = copy.deepcopy(parent)
        for member in sorted(B.REPLACEMENTS | B.ADDITIONS):
            # Executing a payload would fail even the successful construction control.
            data = ('raise AssertionError("Do not execute selected source")  # ' + member + '\n').encode()
            relative = B.PREFIX + member
            self.write(relative, data)
            entry = dict(member=member, public_path=relative, public_sha256=B.digest(data))
            if member in B.REPLACEMENTS:
                self.entries = [e if e['member'] != member else entry for e in self.entries]
            else:
                self.entries.append(entry)
        counts = {'selected_native_files': 2, 'selected_helper_files': 9}
        self.mapping = dict(schema=B.SCHEMA, identity_kind=B.IDENTITY_KIND,
                            predecessor_map=B.PARENT, predecessor_source_map_sha256=B.digest(parent_bytes),
                            entries=self.entries, public_selection_sha256=B.generation(self.entries),
                            **counts, **dict.fromkeys(B.FLAGS, False))
        for name, value in (('PARENT_SHA', B.digest(parent_bytes)), ('COUNTS', counts)):
            context = patch.object(B, name, value)
            context.start()
            self.addCleanup(context.stop)
        self.save(self.mapping)

    @staticmethod
    def encode(value):
        return (json.dumps(value, indent=2, ensure_ascii=True) + '\n').encode()

    def write(self, relative, data):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def save(self, mapping):
        self.write(B.PREFIX + 'SOURCE-MAP.json', self.encode(mapping))

    def assert_refused(self, mapping):
        self.save(mapping)
        with self.assertRaises(ValueError):
            B.materialise(self.repo, self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.repo.glob('.plan18-selection-*')))

    def test_complete_build_manifest_and_existing_output_refusal(self):
        result = B.materialise(self.repo, self.output)
        self.assertEqual(result['files'], 11)
        manifest = json.loads((self.output / 'SOURCE-MANIFEST.json').read_bytes())
        self.assertEqual(len(manifest['files']), 11)
        for entry in self.entries:
            relative = entry['member'].removeprefix('source/')
            data = (self.output / relative).read_bytes()
            self.assertEqual(data, (self.repo / entry['public_path']).read_bytes())
            self.assertEqual(manifest['files'][relative], B.digest(data))
        sentinel = self.output / 'historical-receipt.json'
        sentinel.write_bytes(b'preserve exactly\n')
        with self.assertRaises(FileExistsError):
            B.materialise(self.repo, self.output)
        self.assertEqual(sentinel.read_bytes(), b'preserve exactly\n')

    def test_altered_payload_and_predecessor_refuse_without_output(self):
        for relative in (self.entries[0]['public_path'], B.PARENT):
            path = self.repo / relative
            original = path.read_bytes()
            path.write_bytes(original + b'changed\n')
            with self.subTest(path=relative), self.assertRaisesRegex(ValueError, 'drift|predecessor'):
                B.materialise(self.repo, self.output)
            self.assertFalse(self.output.exists())
            path.write_bytes(original)

    def test_omission_duplicate_unexpected_member_and_counts_refuse(self):
        variants = []
        missing = copy.deepcopy(self.mapping)
        missing['entries'].pop()
        variants.append(missing)
        duplicate = copy.deepcopy(self.mapping)
        duplicate['entries'].append(copy.deepcopy(duplicate['entries'][0]))
        variants.append(duplicate)
        unexpected = copy.deepcopy(self.mapping)
        unexpected['entries'][-1]['member'] = 'source/helpers/extra.py'
        variants.append(unexpected)
        wrong_count = copy.deepcopy(self.mapping)
        wrong_count['selected_helper_files'] += 1
        variants.append(wrong_count)
        for mapping in variants:
            mapping['public_selection_sha256'] = B.generation(mapping['entries'])
            with self.subTest(mapping=mapping):
                self.assert_refused(mapping)

    def test_identity_schema_pins_and_authority_refuse(self):
        changes = [('schema', 'wrong'), ('identity_kind', 'HISTORICAL'),
                   ('public_selection_sha256', '0' * 64), ('predecessor_map', 'other.json'),
                   ('predecessor_source_map_sha256', '0' * 64)]
        changes += [(field, value) for field in B.FLAGS for value in (True, 0, None)]
        for field, value in changes:
            mapping = copy.deepcopy(self.mapping)
            mapping[field] = value
            with self.subTest(field=field, value=value):
                self.assert_refused(mapping)

    def test_required_override_and_unrelated_rebinding_refuse(self):
        for member in (next(iter(B.REPLACEMENTS)), next(iter(B.ADDITIONS)), self.retained):
            mapping = copy.deepcopy(self.mapping)
            entry = next(e for e in mapping['entries'] if e['member'] == member)
            entry['public_path'] = 'other.py'
            self.write('other.py', b'other\n')
            entry['public_sha256'] = B.digest(b'other\n')
            mapping['public_selection_sha256'] = B.generation(mapping['entries'])
            with self.subTest(member=member):
                self.assert_refused(mapping)
        mapping = copy.deepcopy(self.mapping)
        next(e for e in mapping['entries'] if e['member'] == self.retained)['source'] = 'changed provenance'
        self.assert_refused(mapping)

    def test_unsafe_and_aliased_paths_refuse(self):
        for relative in ('../escape.py', '/escape.py', 'C:/escape.py', 'a\\escape.py',
                         'a/../escape.py', 'a/./escape.py', 'a//escape.py',
                         'a/escape.py:stream', 'a/CON.py', 'a/escape.py.'):
            mapping = copy.deepcopy(self.mapping)
            mapping['entries'][0]['public_path'] = relative
            with self.subTest(path=relative):
                self.assert_refused(mapping)
        mapping = copy.deepcopy(self.mapping)
        mapping['entries'].append(dict(mapping['entries'][0], member=mapping['entries'][0]['member'].upper()))
        self.assert_refused(mapping)

    def test_linked_path_refuses(self):
        outside = self.repo / 'outside'
        outside.mkdir()
        link = self.repo / 'link'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest('Operating system refused symlink creation: ' + str(error))
        with self.assertRaisesRegex(ValueError, 'Linked|reparse'):
            B.inside(self.repo, 'link/payload.py')

    def test_windows_reparse_attribute_refuses(self):
        directory = self.repo / 'junction'
        directory.mkdir()
        original = Path.lstat

        def junction_info(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == directory:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        with patch.object(Path, 'lstat', junction_info):
            with self.assertRaisesRegex(ValueError, 'reparse'):
                B.inside(self.repo, 'junction/payload.py')

    def test_destination_created_during_validation_is_preserved(self):
        validate = B.validate_map

        def create_destination(repo, mapping):
            payloads = validate(repo, mapping)
            self.output.mkdir()
            (self.output / 'historical-receipt.json').write_bytes(b'keep\n')
            return payloads

        with patch.object(B, 'validate_map', side_effect=create_destination):
            with self.assertRaises(FileExistsError):
                B.materialise(self.repo, self.output)
        self.assertEqual((self.output / 'historical-receipt.json').read_bytes(), b'keep\n')
        self.assertFalse(list(self.repo.glob('.plan18-selection-*')))

    def test_manifest_binds_copied_snapshot_despite_later_source_change(self):
        map_bytes = (self.repo / (B.PREFIX + 'SOURCE-MAP.json')).read_bytes()
        validate = B.validate_map

        def change_sources_after_validation(repo, mapping):
            payloads = validate(repo, mapping)
            self.write(self.entries[0]['public_path'], b'later source state\n')
            self.write(B.PREFIX + 'SOURCE-MAP.json', b'{"later": true}\n')
            return payloads

        with patch.object(B, 'validate_map', side_effect=change_sources_after_validation):
            B.materialise(self.repo, self.output)
        manifest = json.loads((self.output / 'SOURCE-MANIFEST.json').read_bytes())
        self.assertEqual(manifest['source_map_sha256'], B.digest(map_bytes))
        for relative, sha in manifest['files'].items():
            self.assertEqual(B.digest((self.output / relative).read_bytes()), sha)
        first = self.entries[0]
        self.assertEqual(B.digest((self.output / first['member'].removeprefix('source/')).read_bytes()),
                         first['public_sha256'])

    def test_duplicate_json_keys_and_cli_failure_status(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate map key'):
            B.read_map(b'{"entries": [], "entries": []}')
        self.write(self.entries[0]['public_path'], b'altered\n')
        error = io.StringIO()
        with patch('sys.argv', ['build_selection.py', '--repo', str(self.repo), '--output', str(self.output)]):
            with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as stopped:
                B.main()
        self.assertEqual(stopped.exception.code, 1)
        self.assertIn('refused', error.getvalue())
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
