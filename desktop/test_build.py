"""Small copy-boundary tests; do not assemble a second complete runtime."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('desktop_build', Path(__file__).with_name('build.py'))
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class BuildTests(unittest.TestCase):
    def test_copy_preserves_scientific_source_bytes_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / 'source.py', root / 'out' / 'copy.py'
            source.write_bytes(b'# source\r\nx = -0.0\r\n')
            build.copy_file(source, target)
            self.assertEqual(source.read_bytes(), target.read_bytes())
            with self.assertRaises(FileExistsError):
                build.copy_file(source, target)

    def test_tree_excludes_bytecode_and_unselected_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            (source / '__pycache__').mkdir(parents=True)
            (source / 'a.py').write_text('x = 1\n')
            (source / 'private.txt').write_text('not selected')
            (source / '__pycache__' / 'a.pyc').write_bytes(b'cached')
            build.copy_tree(source, root / 'out', lambda p: p.suffix == '.py')
            self.assertEqual([p.name for p in (root / 'out').iterdir()], ['a.py'])

    def test_ui_contract_is_explicit_and_unique(self):
        self.assertEqual(len(build.UI_FILES), 33)
        self.assertEqual(len(set(build.UI_FILES)), 33)
        self.assertIn('native-launch.mjs', build.UI_FILES)
        self.assertIn('bundle-data.mjs', build.UI_FILES)
        self.assertTrue(all('/' not in name and not name.endswith('.test.mjs') for name in build.UI_FILES))

    def test_ui_snapshot_must_match_its_pin_before_any_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ui = root / 'ui'
            ui.mkdir()
            for name in build.UI_FILES:
                (ui / name).write_bytes(name.encode())
            pin = root / 'ui-snapshot.json'
            record = {'schema': build.UI_PIN_SCHEMA,
                      'files': {name: build.digest(ui / name) for name in build.UI_FILES}}
            pin.write_text(json.dumps(record), encoding='utf-8')
            self.assertEqual(build.ui_snapshot(ui, pin), record['files'])
            (ui / 'serve.mjs').write_bytes(b'edited')
            with self.assertRaisesRegex(ValueError, 'serve.mjs'):
                build.ui_snapshot(ui, pin)
            (ui / 'serve.mjs').unlink()
            with self.assertRaisesRegex(ValueError, 'Not a plain UI file: serve.mjs'):
                build.ui_snapshot(ui, pin)
            (ui / 'serve.mjs').write_bytes(b'serve.mjs')
            del record['files']['bundle-data.mjs']
            pin.write_text(json.dumps(record), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'exactly the 33'):
                build.ui_snapshot(ui, pin)
            with self.assertRaisesRegex(ValueError, 'No pinned UI snapshot'):
                build.ui_snapshot(ui, root / 'absent.json')
        self.assertEqual(build.UI_PIN, build.ROOT / 'desktop' / 'ui-snapshot.json')

    def test_build_manifest_tracks_delivered_bytes_not_itself(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            file = root / 'Atlas.exe'
            file.write_bytes(b'fixture')
            self.assertEqual(build.seal(root), 1)
            record = json.loads((root / 'build-manifest.json').read_text())
            self.assertEqual(record['files'], {'Atlas.exe': build.digest(file)})
            file.write_bytes(b'changed development fixture')
            self.assertEqual(build.seal(root), 1)
            current = json.loads((root / 'build-manifest.json').read_text())
            self.assertNotEqual(record['files']['Atlas.exe'], current['files']['Atlas.exe'])


if __name__ == '__main__':
    unittest.main()
