"""Standard-library fixtures for the public source merge; no scientific imports."""
import copy
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import build_selection as B


class MaterialiserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='plan21-builder-test-')
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.output = self.repo / 'new-tree'
        real_repo = Path(B.__file__).resolve().parents[4]
        shared = 'tectonics/optimisation/workbench/plan18/build_selection.py'
        for relative in (B.BASE_TOOL, shared):
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((real_repo / relative).read_bytes())
        self.base = B.combined(self.repo)
        self.utilities = self.base.shared(self.repo)
        self.base_entries = []
        names = ['source/src/atlas_tectonics/example.py', 'source/helpers/unchanged.py',
                 *sorted(B.REPLACEMENTS)]
        for member in names:
            self.base_entries.append(self.entry(member, 'inputs/' + member, 'base'))
        self.historical = self.repo / 'historical-map.json'
        self.historical.write_bytes(b'{"fixture": "predecessor"}\n')
        self.base_mapping = dict(
            schema=self.base.SCHEMA, selected_members=len(names), entries=self.base_entries,
            source_maps=[dict(path=self.historical.name,
                              sha256=self.utilities.digest(self.historical.read_bytes()))],
            public_selection_sha256=self.utilities.generation(self.base_entries),
            **dict.fromkeys(self.base.FLAGS, False))
        self.mapping = dict(schema=B.SCHEMA, identity_kind=B.IDENTITY_KIND,
                            entries=[], **dict.fromkeys(B.OVERLAY_FLAGS, False))
        base_index = {e['member']: e for e in self.base_entries}
        for member in sorted(B.REPLACEMENTS | B.ADDITIONS):
            entry = self.entry(member, B.PREFIX + member, 'overlay')
            base = base_index.get(member)
            entry.update(base_public_path=base['public_path'] if base else None,
                         base_public_sha256=base['public_sha256'] if base else None,
                         # Private predecessor hashes need not equal public bytes.
                         base_sha256='a' * 64 if base else None)
            self.mapping['entries'].append(entry)
        self.map_path = self.repo / B.PREFIX / 'SOURCE-MAP.json'
        self.base_map_path = self.repo / B.BASE_MAP
        self.base_counts = dict(selected_native_files=1, selected_helper_files=3)
        self.counts = dict(selected_native_files=1, selected_helper_files=4)
        self.save()

    def entry(self, member, relative, label):
        raw = ('raise AssertionError("Do not execute ' + label + ' ' + member + '")\n').encode()
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return dict(member=member, public_path=relative, public_sha256=self.utilities.digest(raw))

    def save(self, mapping=None, base_mapping=None):
        overlay = copy.deepcopy(self.mapping if mapping is None else mapping)
        overlay['public_overlay_identity_sha256'] = B.overlay_identity(overlay['entries'], self.utilities)
        base = self.base_mapping if base_mapping is None else base_mapping
        for path, document in ((self.map_path, overlay), (self.base_map_path, base)):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((json.dumps(document, indent=2) + '\n').encode())
        return dict(MAP_SHA=self.utilities.digest(self.map_path.read_bytes()),
                    BASE_MAP_SHA=self.utilities.digest(self.base_map_path.read_bytes()),
                    BASE_COUNTS=self.base_counts, COUNTS=self.counts)

    def materialise(self, mapping=None, base_mapping=None):
        with patch.multiple(B, **self.save(mapping, base_mapping)):
            return B.materialise(self.repo, self.output)

    def test_complete_merge_preserves_base_and_records_new_identity(self):
        original = {e['public_path']: (self.repo / e['public_path']).read_bytes()
                    for e in self.base_entries}
        result = self.materialise()
        self.assertEqual(result['files'], 5)
        manifest = json.loads((self.output / 'SOURCE-MANIFEST.json').read_bytes())
        expected = {e['member']: e for e in self.base_entries}
        expected.update({e['member']: e for e in self.mapping['entries']})
        self.assertEqual(result['selection_sha256'], self.utilities.generation(expected.values()))
        self.assertEqual(manifest['selection_sha256'], result['selection_sha256'])
        self.assertEqual(manifest['selected_members'], 5)
        self.assertEqual({k: manifest[k] for k in self.counts}, self.counts)
        self.assertEqual(len(manifest['files']), 5)
        for member, entry in expected.items():
            relative = member.removeprefix('source/')
            self.assertEqual((self.output / relative).read_bytes(),
                             (self.repo / entry['public_path']).read_bytes())
            self.assertEqual(manifest['files'][relative], entry['public_sha256'])
        for relative, raw in original.items():
            self.assertEqual((self.repo / relative).read_bytes(), raw)
        self.assertTrue(all(manifest[k] is False for k in B.FLAGS + B.OVERLAY_FLAGS))
        self.assertEqual([e['path'] for e in manifest['source_maps']],
                         [B.BASE_MAP, B.PREFIX + 'SOURCE-MAP.json', self.historical.name])
        self.assertEqual(manifest['base_selection_sha256'], self.base_mapping['public_selection_sha256'])
        self.assertEqual(set(manifest['replaced_public_sources']), B.REPLACEMENTS)
        with self.assertRaises(FileExistsError):
            self.materialise()

    def test_changed_map_bytes_refuse_before_publication(self):
        for path in (self.base_map_path, self.map_path):
            with self.subTest(map=path.name, parent=path.parent.name):
                pins = self.save()
                path.write_bytes(path.read_bytes() + b' ')
                with patch.multiple(B, **pins), self.assertRaisesRegex(ValueError, 'reviewed bytes'):
                    B.materialise(self.repo, self.output)
                self.assertFalse(self.output.exists())

    def test_changed_base_overlay_and_historical_sources_refuse(self):
        paths = [self.historical, self.repo / self.base_entries[0]['public_path'],
                 self.repo / self.base_entries[-1]['public_path'],
                 self.repo / self.mapping['entries'][0]['public_path']]
        for path in paths:
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                path.write_bytes(raw + b'# drift\n')
                with self.assertRaisesRegex(ValueError, 'changed'):
                    self.materialise()
                path.write_bytes(raw)
                self.assertFalse(self.output.exists())

    def test_unknown_missing_and_duplicate_overlay_members_refuse(self):
        for change in ('unknown', 'missing', 'duplicate', 'case-duplicate'):
            with self.subTest(change=change):
                mapping = copy.deepcopy(self.mapping)
                if change == 'unknown':
                    mapping['entries'][0]['member'] = 'source/helpers/unselected.py'
                elif change == 'missing':
                    mapping['entries'].pop()
                else:
                    extra = dict(mapping['entries'][0])
                    if change == 'case-duplicate':
                        extra['member'] = extra['member'].upper().replace('SOURCE/HELPERS/', 'source/helpers/')
                    mapping['entries'].append(extra)
                with self.assertRaisesRegex(ValueError, 'membership|Duplicate'):
                    self.materialise(mapping)
                self.assertFalse(self.output.exists())

    def test_public_base_provenance_is_distinct_from_private_hash(self):
        # The successful merge above already has intentionally unequal private
        # base_sha256 and public_sha256. Public provenance must still match.
        for field, value in (('base_public_path', 'inputs/wrong.py'),
                             ('base_public_sha256', '0' * 64)):
            mapping = copy.deepcopy(self.mapping)
            mapping['entries'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'public base differs'):
                self.materialise(mapping)
        mapping = copy.deepcopy(self.mapping)
        mapping['entries'][-1]['base_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'must not claim a base'):
            self.materialise(mapping)

    def test_authority_and_source_count_changes_refuse(self):
        for flag in B.FLAGS + B.OVERLAY_FLAGS:
            mapping = copy.deepcopy(self.mapping)
            mapping[flag] = True
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'authority'):
                self.materialise(mapping)
        for field, value in (('runtime_admission', True), ('selected_members', 5),
                             ('public_selection_sha256', '0' * 64)):
            base = copy.deepcopy(self.base_mapping)
            base[field] = value
            with self.subTest(base_field=field), self.assertRaises(ValueError):
                self.materialise(base_mapping=base)
        pins = self.save()
        pins['BASE_COUNTS'] = dict(selected_native_files=2, selected_helper_files=2)
        with patch.multiple(B, **pins), self.assertRaisesRegex(ValueError, 'counts differ'):
            B.materialise(self.repo, self.output)
        pins = self.save()
        pins['COUNTS'] = dict(selected_native_files=2, selected_helper_files=3)
        with patch.multiple(B, **pins), self.assertRaisesRegex(ValueError, 'counts differ'):
            B.materialise(self.repo, self.output)
        self.assertFalse(self.output.exists())

    def test_traversal_and_substituted_overlay_path_refuse(self):
        for field, value in (('member', 'source/helpers/../escape.py'),
                             ('public_path', '../escape.py'),
                             ('public_path', self.base_entries[0]['public_path'])):
            mapping = copy.deepcopy(self.mapping)
            mapping['entries'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.materialise(mapping)
        with patch.multiple(B, **self.save()), self.assertRaisesRegex(ValueError, 'Invalid relative'):
            B.materialise(self.repo, self.repo / 'unused' / '..' / 'escape')
        self.assertFalse(self.output.exists())

    def test_linked_destination_parent_and_source_refuse(self):
        parent = self.repo / 'linked-parent'
        parent.mkdir()
        source = self.repo / self.mapping['entries'][0]['public_path']
        original = Path.lstat
        for linked, output in ((parent, parent / 'new-tree'), (source, self.output)):
            def lstat(path, *args, **kwargs):
                if path == linked:
                    return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
                return original(path, *args, **kwargs)
            with self.subTest(path=linked.name), patch.multiple(B, **self.save()):
                with patch.object(Path, 'lstat', lstat), self.assertRaisesRegex(ValueError, 'Linked or reparse'):
                    B.materialise(self.repo, output)
                self.assertFalse(output.exists())

    def test_duplicate_json_keys_and_overlay_identity_refuse(self):
        pins = self.save()
        raw = self.map_path.read_bytes().replace(b'"schema":', b'"schema":"duplicate", "schema":', 1)
        self.map_path.write_bytes(raw)
        pins['MAP_SHA'] = self.utilities.digest(raw)
        with patch.multiple(B, **pins), self.assertRaisesRegex(ValueError, 'Duplicate map key'):
            B.materialise(self.repo, self.output)
        pins = self.save()
        mapping = json.loads(self.map_path.read_bytes())
        mapping['public_overlay_identity_sha256'] = '0' * 64
        raw = json.dumps(mapping).encode()
        self.map_path.write_bytes(raw)
        pins['MAP_SHA'] = self.utilities.digest(raw)
        with patch.multiple(B, **pins), self.assertRaisesRegex(ValueError, 'overlay identity'):
            B.materialise(self.repo, self.output)

    def test_changed_construction_tools_refuse_without_execution(self):
        for relative in (B.BASE_TOOL, self.base.SHARED):
            path = self.repo / relative
            original = path.read_bytes()
            path.write_bytes(b'raise AssertionError("Unreviewed tool must not execute")\n')
            with self.subTest(tool=relative), self.assertRaisesRegex(ValueError, 'tool changed'):
                self.materialise()
            path.write_bytes(original)
        self.assertFalse(self.output.exists())

    def test_write_failure_removes_staging_without_publishing(self):
        original = Path.write_bytes
        def fail(path, raw):
            if '.plan21-selection-' in str(path):
                raise OSError('injected write failure')
            return original(path, raw)
        pins = self.save()
        with patch.multiple(B, **pins), patch.object(Path, 'write_bytes', fail):
            with self.assertRaisesRegex(OSError, 'injected write failure'):
                B.materialise(self.repo, self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.repo.glob('.plan21-selection-*')))

    def test_cli_failure_reports_nonzero_and_preserves_output_absence(self):
        result = subprocess.run([sys.executable, '-B', B.__file__, '--repo', str(self.repo),
                                 '--output', str(self.output)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Plan21 source construction refused:', result.stderr)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
