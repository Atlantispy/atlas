"""Bounded source-integrity refusals; no Atlas imports or native execution."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('s1a_build_checks', HERE / 'build_candidate.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ConstructionRefusals(unittest.TestCase):
    def test_changed_builder_bytes_refuse_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tool = root / builder.BASE_TOOL
            tool.parent.mkdir(parents=True)
            tool.write_bytes(b'changed builder')
            output = root / 'out'
            with self.assertRaisesRegex(ValueError, 'Pinned source changed'):
                builder.materialise(root, output)
            self.assertFalse(output.exists())

    def test_actual_port_refuses_changed_guard_row(self):
        spec = importlib.util.spec_from_file_location('s1a_port_checks', HERE / 'port_s1a.py')
        port = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(port)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = HERE.parents[4]
            parent_map = repo / 'tectonics/optimisation/workbench/plan39/SOURCE-MAP.json'
            rows = json.loads(parent_map.read_bytes())['entries']
            required = set(port.DEPENDENCIES) | {row for row, spec in port.ROWS.items() if spec[0] == 'diff'}
            base = root / 'base'
            (base / 'helpers').mkdir(parents=True)
            for entry in rows:
                row = entry['member'].removeprefix('source/')
                if row in required:
                    (base / row).write_bytes((repo / entry['public_path']).read_bytes())
            package = root / 'package'
            shutil.copytree(HERE / 'source', package)
            bad = package / port.GUARD
            bad.write_bytes(b'changed guard')
            port.PORT = package
            with self.assertRaisesRegex(ValueError, 'Pin differs: package helpers/sealed_guard_set.py'):
                port.derive(base / 'helpers')

    def test_cli_failure_is_nonzero_and_reports_refusal(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            message = io.StringIO()
            with patch('sys.argv', ['build_candidate.py', '--repo', str(root), '--output', str(root / 'out')]), \
                    patch.object(builder, 'materialise', side_effect=ValueError('injected source drift')), \
                    contextlib.redirect_stderr(message), self.assertRaises(SystemExit) as caught:
                builder.main()
            self.assertEqual(caught.exception.code, 1)
            self.assertIn('S1A source construction refused: injected source drift', message.getvalue())
            self.assertFalse((root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
