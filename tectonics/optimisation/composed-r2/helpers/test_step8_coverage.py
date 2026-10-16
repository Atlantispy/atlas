"""Compact projection preserves the original exact physical coverage predicates."""
import ast
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import sys
from types import SimpleNamespace
from contextlib import contextmanager
from hashlib import sha256
import gzip
import json
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE/'compact-geometry-r1'),
               str(HERE.parent/'runtime-integration-r1/runtime-src')]
from atlas_tectonics.resources import WorkBudget
from test_mesh_tables import small_mesh_record, compact_fixture
from compact_restart_patch import coverage_projection, inspect_compact_preadvance


class CoverageTests(unittest.TestCase):
    def test_same_physical_predicates_without_full_mesh_export(self):
        source = HERE.parents[2]/'heat-repair-20261007/private_heat_original_coverage_r1.py'
        tree = ast.parse(source.read_text(encoding='utf8'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'physical_coverage')
        env = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), env)
        physical = env['physical_coverage']
        decode = lambda pair: Fraction(int(pair[0], 16), int(pair[1], 16))
        budget = WorkBudget(256 << 20)
        mesh = small_mesh_record(budget)
        mesh['booked_cell_rule'] = {'closed_graph_id': 'a'*64}
        mesh['required_thermal_boundary_faces'] = [mesh['faces'][0]['face_id']]
        graph = {b: mesh[a] for a, b in (('funding_id', 'funding_id'), ('support_id', 'end_support_id'),
                 ('grid_id', 'grid_id'), ('trajectory_id', 'trajectory_id'), ('time_s', 'end_time_s'))}
        graph['cells'] = [{'cell_id': row['logical_cell_id'], 'end_volume_m3': ['0x1', '0x1']}
                          for row in mesh['cells']]
        view, *rest = compact_fixture(mesh, budget)
        wrapped = SimpleNamespace(_compact=view, _resource=budget)
        with coverage_projection(wrapped, budget=budget, check=lambda: None) as projection:
            self.assertEqual(physical(projection, graph, 'a'*64, decode), physical(mesh, graph, 'a'*64, decode))
            cases = []
            for field in ('funding_id', 'grid_id', 'trajectory_id', 'end_support_id', 'end_time_s'):
                row = deepcopy(graph); row[field] = 'different'; cases.append(row)
            row = deepcopy(graph); row['cells'][0]['end_volume_m3'] = ['-0x1', '0x1']; cases.append(row)
            row = deepcopy(graph); row['cells'].append(deepcopy(row['cells'][0])); cases.append(row)
            row = deepcopy(graph); row['cells'].pop(); cases.append(row)
            for changed in cases:
                with self.assertRaises(ValueError):
                    physical(mesh, changed, 'a'*64, decode)
                with self.assertRaises(ValueError):
                    physical(projection, changed, 'a'*64, decode)
        canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        @contextmanager
        def decoded(raw, *, budget, cancel):
            with budget.reserve(65536+16*len(raw), category='fixture-decoder'):
                yield SimpleNamespace(value=json.loads(raw))
        resources = SimpleNamespace(check=lambda cancel: cancel(), decoded=decoded,
            workspace=lambda budget, size, *, cancel, category: budget.reserve(size, category=category))
        coverage = SimpleNamespace(source_bindings=lambda: None, physical_coverage=physical,
            _coverage_bytes=lambda *args: 65536, _copy_value=lambda value, check: deepcopy(value),
            save_operands=lambda artifacts, **operands: {k: {'raw_sha256': sha256(v).hexdigest()} for k, v in operands.items()},
            digest=lambda path: sha256(Path(path).read_bytes()).hexdigest())
        record = {}
        with tempfile.TemporaryDirectory(prefix='step8-coverage-', dir=HERE.parents[3]/'_t') as directory:
            result = inspect_compact_preadvance(coverage, wrapped,
                SimpleNamespace(_json=canonical(graph), geometry_id='a'*64), SimpleNamespace(_json=b'{}'),
                resources, budget, lambda: None, directory, record, lambda: None)
            self.assertEqual(result, physical(mesh, graph, 'a'*64, decode))
            self.assertEqual(gzip.decompress((Path(directory)/'preadvance-mesh.json.gz').read_bytes()), canonical(mesh))
            self.assertEqual(record['preadvance_operands']['mesh']['raw_sha256'], view.geometry_id)
        del projection, wrapped, view, rest
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
