"""Bounded stdlib fixtures for the Plan22 candidate wrapper, not Atlas runs."""
import contextlib
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('plan22_builder_under_test', HERE / 'build_candidate.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
REAL_LOAD_BASE = BUILDER.load_base


def digest(raw):
    return sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=True) + '\n').encode()


class Utilities:
    """Fixture implementations of the unchanged, pinned builder utility contract."""
    digest = staticmethod(digest)
    read_map = staticmethod(json.loads)

    @staticmethod
    def inside(root, relative):
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Fixture path escapes')
        return root / path

    @classmethod
    def read_source(cls, root, relative):
        return cls.inside(root, relative).read_bytes()

    @staticmethod
    def refuse_existing(path):
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)

    @staticmethod
    def entry_index(repo, entries):
        return {entry['member']: entry for entry in entries}

    @staticmethod
    def generation(entries):
        rows = sorted(({'member': e['member'], 'public_sha256': e['public_sha256']}
                       for e in entries), key=lambda row: row['member'])
        return digest(encoded(rows))


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='.fixture-', dir=HERE)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.output = self.root / 'candidate'
        self.entries = []
        members = [f'source/src/module{i:03}.py' for i in range(240)]
        members += ['source/helpers/record_views.py', 'source/helpers/mesh_tables.py']
        members += [f'source/helpers/helper{i:03}.py' for i in range(404)]
        for index, member in enumerate(members):
            public_path = 'parent/' + member
            raw = ('raise RuntimeError("Selected source must not execute: %d")\n' % index).encode()
            self.write(public_path, raw)
            self.entries.append(dict(member=member, public_path=public_path, public_sha256=digest(raw)))
        self.write('combined.json', encoded({'entries': self.entries[:-1]}))
        self.write('parent/SOURCE-MAP.json', encoded({'entries': self.entries[-1:]}))
        for name in ('parent/build.py', 'tools/combined.py', 'tools/shared.py'):
            self.write(name, b'# Pinned fixture metadata tool; selected sources are never imported.\n')
        self.base = types.SimpleNamespace(
            BASE_TOOL='tools/combined.py', BASE_TOOL_SHA=self.file_pin('tools/combined.py'),
            BASE_MAP='combined.json', BASE_MAP_SHA=self.file_pin('combined.json'),
            PREFIX='parent/', MAP_SHA=self.file_pin('parent/SOURCE-MAP.json'),
            FLAGS=('runtime_admission', 'default_changed', 'scientific_acceptance', 'interval_authority',
                   'installed_package_changed'),
            OVERLAY_FLAGS=('public_runtime_compatibility', 'runtime_policy_adopted', 's9_selected'),
            check_counts=self.check_counts, overlay_identity=self.overlay_identity,
            materialise=self.materialise_parent,
        )
        shared = types.SimpleNamespace(SHARED='tools/shared.py', SHARED_SHA=self.file_pin('tools/shared.py'),
                                       shared=lambda repo: Utilities)
        self.base.combined = lambda repo: shared
        self.mapping = dict(schema=BUILDER.SCHEMA, identity_kind=BUILDER.IDENTITY_KIND,
                            entries=[], **dict.fromkeys(BUILDER.FLAGS, False))
        parents = {entry['member']: entry for entry in self.entries}
        for member in sorted(BUILDER.REPLACEMENTS | BUILDER.ADDITIONS):
            path = BUILDER.PREFIX + member
            raw = ('raise RuntimeError("Candidate source must not execute: %s")\n' % member).encode()
            self.write(path, raw)
            prior = parents.get(member, {})
            self.mapping['entries'].append(dict(member=member, public_path=path, public_sha256=digest(raw),
                public_base=prior.get('public_path'), public_base_sha256=prior.get('public_sha256'),
                selected_composition_member=False))
        self.mapping['public_overlay_identity_sha256'] = self.overlay_identity(self.mapping['entries'], Utilities)
        for attribute, value in (('FROZEN', True), ('BASE_TOOL', 'parent/build.py'),
                                 ('BASE_TOOL_SHA', self.file_pin('parent/build.py')),
                                 ('load_base', lambda repo: self.base)):
            patcher = patch.object(BUILDER, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.repin_map()

    def write(self, relative, raw):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def file_pin(self, relative):
        return digest((self.repo / relative).read_bytes())

    def repin_map(self):
        path = BUILDER.PREFIX + 'SOURCE-MAP.json'
        self.write(path, encoded(self.mapping))
        BUILDER.MAP_SHA = self.file_pin(path)

    @staticmethod
    def check_counts(entries, expected):
        counts = {'selected_native_files': sum(m.startswith('source/src/') for m in entries),
                  'selected_helper_files': sum(m.startswith('source/helpers/') for m in entries)}
        if counts != expected:
            raise ValueError('Complete source selection counts differ')

    @staticmethod
    def overlay_identity(entries, utilities):
        return utilities.digest(encoded([{'member': e['member'], 'public_sha256': e['public_sha256']}
                                         for e in entries]))

    def materialise_parent(self, repo, stage):
        stage.mkdir()
        for entry in self.entries:
            destination = stage / entry['member'].removeprefix('source/')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((repo / entry['public_path']).read_bytes())
        manifest = dict(files={e['member'].removeprefix('source/'): e['public_sha256'] for e in self.entries},
            selection_sha256=Utilities.generation(self.entries),
            source_maps=[{'path': self.base.BASE_MAP, 'sha256': self.base.BASE_MAP_SHA},
                         {'path': self.base.PREFIX + 'SOURCE-MAP.json', 'sha256': self.base.MAP_SHA}],
            **dict.fromkeys(self.base.FLAGS + self.base.OVERLAY_FLAGS, False))
        (stage / 'SOURCE-MANIFEST.json').write_bytes(encoded(manifest))

    def assert_refused(self, message):
        with self.assertRaisesRegex((ValueError, OSError), message):
            BUILDER.materialise(self.repo, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('.plan22-candidate-*')), [])

    def test_complete_candidate_preserves_644_members_and_denies_authority(self):
        result = BUILDER.materialise(self.repo, self.output)
        self.assertEqual(result['files'], 647)
        manifest = json.loads((self.output / 'SOURCE-MANIFEST.json').read_bytes())
        self.assertEqual(len(manifest['files']), 647)
        unchanged = 0
        for entry in self.entries:
            if entry['member'] not in BUILDER.REPLACEMENTS:
                self.assertEqual((self.output / entry['member'].removeprefix('source/')).read_bytes(),
                                 (self.repo / entry['public_path']).read_bytes())
                unchanged += 1
        self.assertEqual(unchanged, 644)
        for member, pin in manifest['files'].items():
            self.assertEqual(digest((self.output / member).read_bytes()), pin)
        self.assertTrue(all(manifest[key] is False for key in BUILDER.FLAGS))
        self.assertEqual(len(manifest['source_tools']), 3)

    def test_map_and_tool_pins_fail_closed(self):
        for attribute in ('MAP_SHA', 'BASE_TOOL_SHA'):
            with self.subTest(attribute=attribute), patch.object(BUILDER, attribute, '0' * 64):
                self.assert_refused('Pinned input changed')
        with patch.object(BUILDER, 'MAP_SHA', None):
            self.assert_refused('Reviewed Plan22 map pin required')

    def test_loader_refuses_tampered_tool_before_execution(self):
        self.write(BUILDER.BASE_TOOL, b'raise RuntimeError("Unpinned tool executed")\n')
        with self.assertRaisesRegex(ValueError, 'Pinned input changed'):
            REAL_LOAD_BASE(self.repo)

    def test_both_public_base_path_and_pin_must_match(self):
        for entry in self.mapping['entries']:
            if entry['member'] not in BUILDER.REPLACEMENTS:
                continue
            for field in ('public_base', 'public_base_sha256'):
                with self.subTest(member=entry['member'], field=field):
                    original = entry[field]
                    entry[field] = 'incorrect'
                    self.repin_map()
                    self.assert_refused('Current public base differs')
                    entry[field] = original
        self.repin_map()

    def test_every_authority_flag_is_required_false(self):
        for key in BUILDER.FLAGS:
            with self.subTest(key=key):
                self.mapping[key] = True
                self.repin_map()
                self.assert_refused('Candidate map grants authority')
                self.mapping[key] = False
        self.repin_map()

    def test_parent_file_drift_is_detected_before_publication(self):
        self.write(self.entries[0]['public_path'], b'corrupt parent source\n')
        self.assert_refused('Pinned input changed')

    def test_existing_destination_and_late_failure_are_atomic(self):
        self.output.mkdir()
        marker = self.output / 'keep.txt'
        marker.write_text('untouched', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            BUILDER.materialise(self.repo, self.output)
        self.assertEqual(marker.read_text(encoding='utf-8'), 'untouched')
        self.output = self.root / 'other-candidate'

        def fail_after_partial_write(repo, stage):
            stage.mkdir()
            (stage / 'partial').write_bytes(b'disposable')
            raise OSError('injected staging failure')

        self.base.materialise = fail_after_partial_write
        self.assert_refused('injected staging failure')

    def test_cli_reports_unfrozen_failure_with_exit_one(self):
        errors = io.StringIO()
        with patch.object(BUILDER, 'FROZEN', False), patch('sys.argv', [
                'build_candidate.py', '--repo', str(self.repo), '--output', str(self.output)]), \
                contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as caught:
            BUILDER.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn('Plan22 candidate construction refused: The corrected public source map is not frozen',
                      errors.getvalue())
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
