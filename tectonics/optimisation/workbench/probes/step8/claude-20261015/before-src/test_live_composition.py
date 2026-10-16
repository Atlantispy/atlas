"""The Step 8 source combination imports in a separate process."""
import json
from collections import Counter
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_step7_bundle as B
import differential_mesh_patch as DP
import partition_native_patch as PN
import live_memory_composition as LIVE


def write_layout(directory):
    root, helpers, ram, heat_report = B.write_layout(directory)
    package = root/'atlas_tectonics'
    sources = {path.name: path.read_text(encoding='utf8') for path in package.glob('*.py')}
    original = B.BASE/'runtime-src/atlas_tectonics'
    sources['integration_differential_geometry.py'] = PN.transform(
        (original/'integration_differential_geometry.py').read_bytes().decode())
    sources['integration_differential_mesh.py'] = DP.transform(sources['integration_differential_mesh.py'])
    selected, report = LIVE.apply_native(sources)
    for name, source in selected.items():
        (package/name).write_text(source, encoding='utf8', newline='\n')
    return root, helpers, ram, dict(native=report, heat=heat_report)


class CompositionTests(unittest.TestCase):
    def test_generated_native_sources_introduce_no_undefined_names(self):
        executable = os.environ.get('STEP8_RUFF')
        if not executable:
            self.skipTest('STEP8_RUFF must name the installed check-only Ruff executable')
        with tempfile.TemporaryDirectory(prefix='step8-names-', dir=B.T/'_t') as directory:
            root, _, _, _ = write_layout(directory)
            original = B.BASE/'runtime-src/atlas_tectonics'
            modules = sorted({row[0] for row in LIVE.STAGES})
            def findings(path):
                result = subprocess.run([executable, 'check', '--no-cache', '--isolated',
                    '--select', 'F821', '--output-format', 'json', str(path)],
                    capture_output=True, text=True, timeout=30)
                self.assertIn(result.returncode, (0, 1), result.stderr)
                return Counter(row['message'] for row in json.loads(result.stdout))
            for name in modules:
                with self.subTest(module=name):
                    added = findings(root/'atlas_tectonics'/name)-findings(original/name)
                    self.assertFalse(added, dict(added))

    def test_combined_native_and_heat_source_stages_import_in_fresh_process(self):
        with tempfile.TemporaryDirectory(prefix='step8-source-', dir=B.T/'_t') as directory:
            root, helpers, ram, report = write_layout(directory)
            self.assertEqual(len(report['native']['stages']), 10)
            self.assertTrue(report['heat']['live_memory'])
            sources = {p.name: p.read_text(encoding='utf8') for p in (root/'atlas_tectonics').glob('*.py')}
            with self.assertRaises((ValueError, RuntimeError)):
                LIVE.apply_native(sources)
            modules = sorted({row['module'].removesuffix('.py') for row in report['native']['stages']})
            script = ("import importlib,json,sys;sys.path[:0]=json.loads(sys.argv[1]);"
                "mods=json.loads(sys.argv[2]);"
                "[importlib.import_module('atlas_tectonics.'+name) for name in mods];"
                "import private_heat_native_issuer_r13,private_heat_joined_consumer_r6;"
                "print(json.dumps(mods))")
            paths = [str(root), str(helpers), str(ram), str(B.H/'source/tectonics/tests')]
            child = subprocess.run([sys.executable, '-B', '-c', script, json.dumps(paths), json.dumps(modules)],
                cwd=directory, capture_output=True, text=True, timeout=120)
            self.assertEqual(child.returncode, 0, child.stdout+'\n'+child.stderr)
            self.assertEqual(json.loads(child.stdout), modules)


if __name__ == '__main__':
    unittest.main(verbosity=2)
