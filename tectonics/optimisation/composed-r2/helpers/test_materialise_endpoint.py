"""Targeted field/entry invariants; not a real historical migration result."""
import ast
import gc
from hashlib import sha256
from pathlib import Path
import unittest
import sys

import numpy as np
import materialise_endpoint as M

sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'runtime-integration-r1/runtime-src'))


def uncapped(value):
    """W.canonical's exact encoder call without its 8 MiB metadata cap."""
    import json
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def large_rows(target):
    """Synthetic layout rows (IDs, exact rational hex pairs, integers, floats); no science."""
    rows, size, index = [], 0, 0
    while size < target:
        ident = sha256(index.to_bytes(8, 'little')).hexdigest()
        row = dict(id=ident, q=[[hex(index*7919+k), hex(2*k+1)] for k in range(4)],
                   n=index, w=index/7, tags=['collar', ident[:16]])
        rows.append(row)
        size += len(uncapped(row))+1
        index += 1
    return rows


def spatial_fixture(state, mesh_raw):
    """State/mesh blobs and their lineage header (which names state fields only)."""
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow as C
    blobs = dict(state=uncapped(state), mesh=mesh_raw)
    arrays = {f'spatial-record:{kind}': np.frombuffer(raw, dtype=np.uint8) for kind, raw in blobs.items()}
    refs = {kind: dict(array=f'spatial-record:{kind}', bytes=len(raw), sha256=sha256(raw).hexdigest())
            for kind, raw in blobs.items()}
    header, _ = C._spatial_headers(dict(state, thermal_mesh=None), None, refs)
    return arrays, header


class MaterialisationTests(unittest.TestCase):
    def setUp(self):
        self.a = np.array([[1., 2.], [3., 4.]], dtype='<f8')
        self.rows = [dict(name='enthalpy_j', dtype='float64', shape=[2, 2],
                          sha256=sha256(self.a.tobytes()).hexdigest())]

    def test_exact_equivalent_dtype_spelling_only(self):
        M.check_field_group({'enthalpy_j': self.a}, self.rows)
        self.rows[0]['dtype'] = '<f8'
        M.check_field_group({'enthalpy_j': self.a}, self.rows)

    def test_changed_field_bytes_refuse(self):
        self.a[0, 0] += 1
        with self.assertRaisesRegex(M.EndpointMaterialisationRefused, 'bytes'):
            M.check_field_group({'enthalpy_j': self.a}, self.rows)

    def test_shape_coverage_duplicates_and_noncontiguous_refuse(self):
        for arrays, rows in (({}, self.rows), ({'enthalpy_j': self.a}, self.rows*2),
                ({'enthalpy_j': self.a.ravel()}, self.rows),
                ({'enthalpy_j': self.a.T}, self.rows),
                ({'enthalpy_j': self.a.astype('>f8')}, self.rows)):
            with self.subTest(rows=len(rows), names=list(arrays)):
                with self.assertRaises(M.EndpointMaterialisationRefused):
                    M.check_field_group(arrays, rows)

    def test_no_initialisation_solve_or_publication_route(self):
        tree = ast.parse(Path(M.__file__).read_text(encoding='utf8'))
        forbidden = {'initial_state', 'initial_state_from_funding', 'fund', 'advance',
                     'advance_spatial', 'solve', 'publish_migrated_root', 'put'}
        calls = {node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
                 for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, (ast.Attribute, ast.Name))}
        self.assertFalse(calls & forbidden)
        self.assertIn('admit', calls)  # separate runtime admission still mandatory
        self.assertIn('derive_historical_plan_graph', calls)
        self.assertIn('bind_migrated_base', calls)

    def test_spatial_decode_identical_to_existing_and_failure_keeps_charge(self):
        from atlas_tectonics.resources import WorkBudget
        from atlas_tectonics.integration_regional_workflow import CollarWorkflow as C
        state = {name: name for name in ('schema', 'state_id', 'owner_id', 'funding_id',
            'time_s', 'intervals', 'parent_state_id', 'collar_state_id', 'support_id',
            'trajectory_id', 'grid_id', 'thermal_mesh_id')}
        records = dict(state=state, mesh={'fixture': 'layout only, no science claim'})
        arrays = {f'spatial-record:{kind}': np.frombuffer(M.W.canonical(row), dtype=np.uint8)
                  for kind, row in records.items()}
        refs = {kind: dict(array=f'spatial-record:{kind}', bytes=arrays[f'spatial-record:{kind}'].nbytes,
                          sha256=sha256(arrays[f'spatial-record:{kind}'].tobytes()).hexdigest())
                for kind in records}
        expected = dict(state, thermal_mesh=records['mesh'])
        header, _ = C._spatial_headers(expected, None, refs)
        budget = WorkBudget(16 << 20)
        with C._spatial_restore_records(header, None, arrays, budget) as (ordinary, _):
            self.assertEqual(ordinary, expected)
        with M.spatial_records(header, arrays, budget) as actual:
            self.assertEqual(actual.value, expected)
            self.assertGreater(budget.reserved_bytes, 0)
        del actual
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)
        saved_error = None
        try:
            with M.spatial_records(header, arrays, budget) as borrowed:
                self.assertEqual(borrowed.value, expected)
                raise RuntimeError('held caller traceback')
        except RuntimeError as error:
            saved_error = error
        self.assertGreater(budget.reserved_bytes, 0)
        saved_error.__traceback__ = None
        saved_error = borrowed = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_canonical_check_matches_metadata_encoder_and_bound(self):
        """For small records the uncapped check equals W.canonical(value) == raw.

        Every raw spelling here is accepted by json.loads; the bound is checked
        against the actual canonical length, including growing spellings.
        """
        import json
        import random
        from atlas_tectonics.resources import WorkBudget
        spellings = [b'{}', b'{"a":1}', b'{"b":1,"a":2}', b' {"a" : 1 } ', b'{"a":1,"a":2}',
                     b'{"a":-0}', b'{"a":1e15}', b'{"a":9E15,"b":[1e9,0.5e1,1.0]}', b'{"a":1e-5}',
                     b'{"a":"\x7f"}', b'{"a":"\\u0041\\/\\b"}', '{"é":"\U0001f600"}'.encode(),
                     b'{"a":"\\ud83d\\ude00","b":"\\ud800"}', '{"a":"é"}'.encode('utf-16-le'),
                     '{"a":"āx"}'.encode('utf-16-be'), ('{"a":"'+'ā'*10+'"}').encode('utf-16-be'),
                     '{"a":1.5}'.encode('utf-32')]
        generator = random.Random(20261014)
        def value(depth=0):
            pick = generator.randrange(9 if depth < 3 else 6)
            if pick == 0:
                return generator.choice([0, -0.0, 1e15, 9e15, 1e16, 1e-5, 0.1, 5e-324, 2.5e300])
            if pick == 1:
                return generator.randrange(-10**20, 10**20)
            if pick == 2:
                return ''.join(generator.choice('a"\\\x00\x1f\x7féā\U0001f600/') for _ in range(5))
            if pick in (3, 4, 5):
                return generator.choice([None, True, False, 'id'])
            if pick in (6, 7):
                return [value(depth+1) for _ in range(generator.randrange(4))]
            return {''.join(generator.choice('abé\x7f') for _ in range(2)): value(depth+1)
                    for _ in range(generator.randrange(4))}
        for _ in range(300):
            item = {'v': value()}
            spellings.extend((M.W.canonical(item), json.dumps(item).encode(),
                              json.dumps(item, ensure_ascii=False, indent=1).encode(),
                              json.dumps(item, ensure_ascii=False).encode('utf-16')))
        budget = WorkBudget(1 << 30)
        for raw in spellings:
            with self.subTest(raw=raw[:60]):
                record = json.loads(raw)
                self.assertEqual(M._canonical_equal(record, raw, budget), M.W.canonical(record) == raw)
                self.assertLessEqual(len(M.W.canonical(record)), M._canonical_bound(record, raw)[0])
                self.assertEqual(budget.reserved_bytes, 0)
        self.assertTrue(any(M._canonical_equal(json.loads(r), r, budget) for r in spellings))
        for raw in (b'{"a":NaN}', b'{"a":[Infinity]}'):
            for check in (lambda r, raw: M.W.canonical(r) == raw, lambda r, raw: M._canonical_equal(r, raw, budget)):
                with self.assertRaisesRegex(M.W.WorkflowTransferRefused, 'finite JSON metadata required'):
                    check(json.loads(raw), raw)
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)
        # Sorted item lists on the deepest dict path (2+2+2); siblings do not add.
        self.assertEqual(M._canonical_bound({'a': {'b': {}, 'c': {'d': 1, 'e': 2}}, 'f': [{'g': 1}]}, b'')[1], 6)

    def test_large_canonical_records_pass_with_charged_workspace(self):
        """>8 MiB synthetic records: the 8 MiB metadata encoder refuses, these accept."""
        from atlas_tectonics.resources import WorkBudget
        from atlas_tectonics.integration_regional_workflow import CollarWorkflow as C
        rows = large_rows(20 << 20)
        ids = {name: sha256(name.encode()).hexdigest() for name in ('partition', 'funding', 'plan', 'grid', 'interval')}
        partition = dict(partition_id=ids['partition'], scope='physical-interval', funding_id=ids['funding'],
                         collar_plan_id=ids['plan'], grid_id=ids['grid'], start_time_s=[0, 1], end_time_s=[1, 1],
                         interval_id=ids['interval'], parent_partition_id=None, supports=rows)
        raw = uncapped(partition)
        self.assertGreater(len(raw), M.W.MAX_METADATA_BYTES)
        with self.assertRaisesRegex(M.W.WorkflowTransferRefused, 'exceeds 8 MiB'):
            M.W.canonical(partition)
        refs = {'partition': dict(array='partition-record:partition', bytes=len(raw), sha256=sha256(raw).hexdigest())}
        header = C._partition_header(partition, refs)
        budget = WorkBudget(4 << 30)
        arrays = {'partition-record:partition': np.frombuffer(raw, dtype=np.uint8)}
        with M.partition_record(header, arrays, budget) as decoded:
            self.assertEqual(decoded.value, partition)
            self.assertGreater(budget.reserved_bytes, 4*len(raw))
            self.assertEqual(budget.statistics()['categories'].get('restart-canonical-encode', 0), 0)
        peaks = budget.statistics()['category_peaks']
        self.assertGreaterEqual(peaks['restart-canonical-encode'], 5*len(raw)//2)
        del decoded
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)
        # Spatial state/mesh: the mesh alone exceeds the metadata cap.
        state = {name: name for name in ('schema', 'state_id', 'owner_id', 'funding_id', 'time_s', 'intervals',
            'parent_state_id', 'collar_state_id', 'support_id', 'trajectory_id', 'grid_id', 'thermal_mesh_id')}
        mesh = {'fixture': 'layout only, no science claim', 'rows': rows}
        arrays, header = spatial_fixture(state, uncapped(mesh))
        self.assertGreater(arrays['spatial-record:mesh'].nbytes, M.W.MAX_METADATA_BYTES)
        budget = WorkBudget(4 << 30)
        with M.spatial_records(header, arrays, budget) as actual:
            self.assertEqual(actual.value, dict(state, thermal_mesh=mesh))
            self.assertGreater(budget.reserved_bytes, 6*arrays['spatial-record:mesh'].nbytes)
        self.assertGreaterEqual(budget.statistics()['category_peaks']['restart-canonical-encode'],
                                5*arrays['spatial-record:mesh'].nbytes//2)
        del actual
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_large_noncanonical_records_still_refuse_and_hold_charges(self):
        import json
        from atlas_tectonics.resources import WorkBudget
        rows = large_rows(12 << 20)
        state = {name: name for name in ('schema', 'state_id', 'owner_id', 'funding_id', 'time_s', 'intervals',
            'parent_state_id', 'collar_state_id', 'support_id', 'trajectory_id', 'grid_id', 'thermal_mesh_id')}
        mesh = {'rows': rows, 'fixture': 'layout only, no science claim'}
        spellings = {'reordered keys': json.dumps(mesh, separators=(',', ':')).encode(),
                     'extra whitespace': json.dumps(mesh, sort_keys=True).encode(),
                     'float spelling': uncapped(dict(mesh, scale=1e15)).replace(b'1000000000000000.0', b'1e15'),
                     'nonfinite': json.dumps(dict(mesh, scale=float('nan')), sort_keys=True,
                                             separators=(',', ':')).encode()}
        for label, raw in spellings.items():
            with self.subTest(label):
                self.assertGreater(len(raw), M.W.MAX_METADATA_BYTES)
                arrays, header = spatial_fixture(state, raw)
                budget = WorkBudget(4 << 30)
                saved = None
                try:
                    with M.spatial_records(header, arrays, budget):
                        self.fail('noncanonical record accepted')
                except ValueError as error:
                    saved = error
                if label == 'nonfinite':
                    self.assertIs(type(saved), M.W.WorkflowTransferRefused)
                    # The raised encode keeps its charged workspace with its frame.
                    self.assertGreater(budget.statistics()['categories']['restart-canonical-encode'], 0)
                else:
                    self.assertIs(type(saved), M.EndpointMaterialisationRefused)
                    self.assertIn('not canonical', str(saved))
                    self.assertEqual(budget.statistics()['categories'].get('restart-canonical-encode', 0), 0)
                self.assertGreater(budget.statistics()['category_peaks']['restart-canonical-encode'], 0)
                # Held traceback keeps the raw and decoded reservations.
                self.assertGreater(budget.reserved_bytes, 6*len(raw))
                saved.__traceback__ = None
                saved = None
                gc.collect()
                self.assertEqual(budget.reserved_bytes, 0)

    def test_spatial_extra_blob_refuses_before_decoding(self):
        from atlas_tectonics.resources import WorkBudget
        budget = WorkBudget(1 << 20)
        with self.assertRaises(M.EndpointMaterialisationRefused):
            with M.spatial_records({'record_blobs': {}}, {'foreign': self.a}, budget):
                self.fail('must refuse')
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
