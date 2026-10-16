"""Synthetic native-schema partitions only: no historical endpoint or solve."""
from concurrent.futures import CancelledError
from copy import deepcopy
from fractions import Fraction
import gc
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parents[1]/'runtime-integration-r1'/'runtime-src'
sys.path.insert(0, str(RUNTIME))

import numpy as np
import mesh_tables as M
import partition_tables as P
from atlas_tectonics import integration_differential_geometry as D
from atlas_tectonics import integration_volume as V
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits


def ident(value):
    return sha256(value.encode()).hexdigest()


def q(value):
    value = Fraction(value)
    return [hex(value.numerator), hex(value.denominator)]


def tiny_partition(budget, *, count=3, depth=4):
    """Actual Cartesian/radial records; deliberately synthetic source authority."""
    wide = Fraction((1 << 257)+1, (1 << 263)+7)
    vector = [q(wide), q(-Fraction(1, 1 << 1075)), q(0)]
    ray = dict(direction=[q(1), q(wide), q(0)], angular_velocity_rad_s=vector,
               prior_rotations=[dict(angular_velocity_rad_s=vector, duration_s=q(Fraction(1, 3)))])
    nested = dict(kind='moving-ray-edge', rays=[ray, ray])
    for _ in range(depth):
        nested = dict(kind='snapshot-rotated', constraint=nested, snapshot_offset_s=q(Fraction(1, 7)),
                      angular_velocity_rad_s=vector)
    constraints = {'carried:edge': nested,
        'normal': dict(kind='rotated-normal', normal=vector, angular_velocity_rad_s=vector),
        'plane': dict(kind='fixed-plane', normal=[q(1), q(0), q(0)], offset=q(wide))}
    box = V.CartesianCell((0, 0, 0), (1, 1, 1), budget=budget)
    layer = V.RadialLayer(10, 0, 1, budget=budget)
    box_record, layer_record = box.record(), layer.record()
    supports = []
    for i in range(count):
        supports.append(dict(schema=P.SUPPORT, interval_id=ident('interval'), kind='inherited',
            plate_id='plate:A', source_key=['patch\n\0\U0001f30d', 0], radial_layer=layer_record, voxel=box_record,
            exclusion_ids=[], exclusion_cells=[], material_angular_velocity_rad_s=vector,
            constraints=constraints, components=[dict(logical_cell_id=ident('cell'+str(i)),
                partition_path=['inherited', i, [1, -1]], owner_ray_ids=['vertex:a', 'fan:b'],
                constraints=[['carried:edge', 1], ['normal', -1], ['plane', 1]],
                parent_cell_id=ident('parent'+str(i)), start_identity='same physical component at accepted endpoint')],
            max_components=1000, work_units=123, start_time_s=q(0), end_time_s=q(1), duration_s=q(1),
            coverage='synthetic exact format control', grid_id=ident('grid'), voxel_index=[i, 0, 0],
            radial_band=0, chart=ident('chart'), source_chart_id=ident('chart')))
    body = dict(schema=P.PARTITION, scope='physical-interval', funding_id=ident('funding'),
        source={'fixture_only': True, 'time_s': -0.0, 'large_integer': 1 << 300},
        collar_plan_id=ident('collar'), volume_map_id=ident('map'), current_geometry_id=None,
        network_id=ident('network'), start_time_s=q(0), end_time_s=q(1),
        component_keys=[['patch\n\0\U0001f30d', 0]], component_registry=None, grid_id=ident('grid'),
        grid_lines=[[q(i) for i in range(3)], [q(0), q(1)], [q(0), q(1)]],
        grid_origin_m=[q(0)]*3, grid_basis=[[q(int(i == j)) for j in range(3)] for i in range(3)],
        initial_source_plate_ids=['plate:A'], source_regions=[dict(source_key=['patch', 0], plate_id='plate:A',
            radial_band=0, chart=ident('chart'), radial_layer=layer_record, source_chart_id=ident('chart'),
            kind='inherited', source_constraint_chart=dict(constraints=constraints, literals=[['carried:edge', 1]]),
            parent_owner_ray_ids=['vertex:a', 'fan:b'], parent_cells={'0,0,0': ident('parent0')},
            parent_chart={'parent_partition_id': ident('previous')})],
        excluded_static_cells=[], native_cells=[box_record], support_ids=[D._record_hash(r) for r in supports],
        native_contacts=[dict(native_index=0, physical_cell_id=box.cell_id, axis=0, end=1, side='x1',
            contacts=[dict(support_id=D._record_hash(r), logical_cell_id=r['components'][0]['logical_cell_id'],
                voxel_index=r['voxel_index'], axis=0, end=0) for r in supports], excluded_subfaces=[])],
        max_components=1000, coverage='synthetic exact format control', stocks='not allocated or reseeded',
        interval_id=ident('interval'), parent_partition_id=ident('previous'), parent_network_id=ident('network'),
        endpoint_network_id=ident('next'), start_support_id=ident('start'), end_support_id=ident('end'),
        trajectory={'segments': []}, trajectory_id=ident('trajectory'), prior_trajectory_id=ident('prior'),
        identity_start_cells=[dict(parent_cell_id=ident('parent'+str(i)), cell_id=ident('cell'+str(i))) for i in range(count)],
        start_remap='synthetic control')
    del layer, box
    return body, supports


def opened(body, supports, budget):
    metadata, arrays = P.pack_partition(body, iter(supports), expected_partition_id=D._record_hash(body), budget=budget)
    view = P.CompactPartition(metadata, arrays, expected_partition_id=D._record_hash(body), budget=budget)
    return view, metadata, arrays


def changed(metadata, arrays, name, change):
    metadata, arrays = deepcopy(metadata), dict(arrays)
    arrays[name] = arrays[name].copy()
    change(arrays[name])
    metadata['arrays'][name] = dict(dtype=arrays[name].dtype.str, shape=list(arrays[name].shape),
                                  sha256=sha256(arrays[name].tobytes()).hexdigest())
    return metadata, arrays


class PartitionTablesTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(128 << 20)
        self.body, self.supports = tiny_partition(self.budget)

    def tearDown(self):
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_native_body_and_all_support_bytes_ids_order(self):
        view, metadata, arrays = opened(self.body, self.supports, self.budget)
        self.assertEqual(b''.join(view.iter_legacy_json()), D._encoded(self.body))
        self.assertEqual(view.legacy_record().value, self.body)
        for i, record in enumerate(self.supports):
            self.assertEqual(view.support_id(i), D._record_hash(record))
            self.assertEqual(b''.join(view.iter_legacy_json(view.support(i))), D._encoded(record))
            self.assertEqual(view.legacy_record(view.support(i)).value, record)
        self.assertEqual(view.partition_id, D._record_hash(self.body))
        self.assertEqual(set(metadata['arrays']), set(arrays))

    def test_shared_constraint_ray_and_scalar_nodes_no_graph_expansion(self):
        view, _, _arrays = opened(self.body, self.supports, self.budget)
        with patch.object(P.CompactPartition, 'legacy_record', side_effect=AssertionError('whole expansion forbidden')):
            with patch.object(P.CompactPartition, 'iter_legacy_json', side_effect=AssertionError('whole scan forbidden')):
                a = view.constraint(0, 'carried:edge')
                self.assertEqual(a.index, view.constraint(1, 'carried:edge').index)
                self.assertEqual(a.index, view.root().field('source_regions').at(0).field('source_constraint_chart')
                                 .field('constraints').field('carried:edge').index)
                for _ in range(4):
                    self.assertEqual(a.field('kind').scalar().value, 'snapshot-rotated')
                    a = a.field('constraint')
                rays = a.field('rays')
                self.assertEqual(rays.at(0).index, rays.at(1).index)
                self.assertEqual(view.component(2, 0).field('logical_cell_id').scalar().value, ident('cell2'))
                self.assertEqual(view.support_by_id(view.support_id(1)).index, view.support(1).index)
                row = view.support(0).row()
                self.assertIs(type(row.value['constraints']), P.NodeRef)
                self.assertFalse(hasattr(row.value['constraints'], '__getitem__'))

    def test_wide_exact_rationals_unicode_and_signed_zero(self):
        view, _, arrays = opened(self.body, self.supports, self.budget)
        pair = view.constraint(0, 'plane').field('offset').scalar()
        self.assertEqual(pair.value, self.supports[0]['constraints']['plane']['offset'])
        self.assertGreater(max(int(x) for x in np.diff(arrays['int.offset'])), 128)
        key = view.support(0).field('source_key').at(0).scalar()
        self.assertEqual(key.value, 'patch\n\0\U0001f30d')
        self.assertEqual(M.canonical(view.root().field('source').field('time_s').scalar().value), b'-0.0')

    def test_owned_refs_rows_and_arrays_retain_lease(self):
        view, metadata, arrays = opened(self.body, self.supports, self.budget)
        row = view.component(0, 0).row()
        scalar = view.constraint(0, 'plane').field('offset').scalar()
        payload = view.storage_payload()
        saved_array = payload.value[1]['edge.child']
        del view, metadata, arrays, payload
        gc.collect()
        self.assertGreater(self.budget.reserved_bytes, 0)
        self.assertEqual(row.value['logical_cell_id'].scalar().value, ident('cell0'))
        self.assertEqual(scalar.value, self.supports[0]['constraints']['plane']['offset'])
        del row, scalar
        self.assertGreater(self.budget.reserved_bytes, 0)
        self.assertFalse(saved_array.flags.writeable)
        with self.assertRaises(ValueError):
            saved_array.flags.writeable = True

    def test_immutable_source_copy_and_detached_metadata(self):
        metadata, arrays = P.pack_partition(self.body, self.supports, expected_partition_id=D._record_hash(self.body), budget=self.budget)
        writable = {k: a.copy() for k, a in arrays.items()}
        view = P.CompactPartition(metadata, writable, expected_partition_id=D._record_hash(self.body), budget=self.budget)
        writable['int.sign'][:] = 0
        metadata['schema'] = 'tampered'
        self.assertEqual(view.legacy_record().value, self.body)
        with self.assertRaises(AttributeError):
            view.partition_id = '0'*64
        payload = view.storage_payload()
        payload.value[0]['schema'] = 'tampered'
        self.assertEqual(view.storage_payload().value[0]['schema'], P.SCHEMA)

    def test_wrong_expected_hash_reordered_missing_and_extra_supports(self):
        for support_rows in (self.supports[::-1], self.supports[:-1], self.supports+[self.supports[0]]):
            with self.assertRaises(P.PartitionTablesRefused):
                P.pack_partition(self.body, support_rows, expected_partition_id=D._record_hash(self.body), budget=self.budget)
        with self.assertRaises(P.PartitionTablesRefused):
            P.pack_partition(self.body, self.supports, expected_partition_id='0'*64, budget=self.budget)
        metadata, arrays = P.pack_partition(self.body, self.supports, expected_partition_id=D._record_hash(self.body), budget=self.budget)
        with self.assertRaises(P.PartitionTablesRefused):
            P.CompactPartition(metadata, arrays, expected_partition_id='0'*64, budget=self.budget)

    def test_unknown_scientific_fields_and_constraints_refused(self):
        for target in ('partition', 'support', 'component', 'constraint'):
            body, rows = deepcopy(self.body), deepcopy(self.supports)
            selected = {'partition': body, 'support': rows[0], 'component': rows[0]['components'][0],
                        'constraint': rows[0]['constraints']['plane']}[target]
            selected['unreviewed_science'] = 'must not disappear'
            body['support_ids'] = [D._record_hash(r) for r in rows]
            with self.assertRaises(P.PartitionTablesRefused):
                opened(body, rows, self.budget)
        body, rows = deepcopy(self.body), deepcopy(self.supports)
        rows[0]['constraints']['plane']['kind'] = 'approximate-plane'
        body['support_ids'] = [D._record_hash(r) for r in rows]
        with self.assertRaises(P.PartitionTablesRefused):
            opened(body, rows, self.budget)

    def test_corruption_partial_columns_forward_refs_and_rehashed_identity(self):
        view, metadata, arrays = opened(self.body, self.supports, self.budget)
        damaged = dict(arrays); damaged['edge.child'] = arrays['edge.child'].copy()
        damaged['edge.child'][0] += 1
        with self.assertRaises(P.PartitionTablesRefused):
            P.CompactPartition(metadata, damaged, expected_partition_id=view.partition_id, budget=self.budget)
        damaged = dict(arrays); del damaged['int.bytes']
        with self.assertRaises(P.PartitionTablesRefused):
            P.CompactPartition(metadata, damaged, expected_partition_id=view.partition_id, budget=self.budget)
        new_metadata, damaged = changed(metadata, arrays, 'edge.child', lambda a: a.__setitem__(0, view.node_count-1))
        with self.assertRaises(P.PartitionTablesRefused):
            P.CompactPartition(new_metadata, damaged, expected_partition_id=view.partition_id, budget=self.budget)
        new_metadata, damaged = changed(metadata, arrays, 'float.value', lambda a: a.__setitem__(0, 1.0))
        with self.assertRaisesRegex(P.PartitionTablesRefused, 'hash differs'):
            P.CompactPartition(new_metadata, damaged, expected_partition_id=view.partition_id, budget=self.budget)

    def test_cancellation_budget_refusal_and_held_error_lifetime(self):
        metadata, arrays = P.pack_partition(self.body, self.supports, expected_partition_id=D._record_hash(self.body), budget=self.budget)
        low = WorkBudget(1)
        with self.assertRaises(MemoryLimitError):
            P.CompactPartition(metadata, arrays, expected_partition_id=D._record_hash(self.body), budget=low)
        self.assertEqual(low.reserved_bytes, 0)
        before = self.budget.reserved_bytes
        counter = [0]
        def cancel():
            counter[0] += 1
            if counter[0] == 12:
                raise CancelledError('bounded cancellation control')
        failure = None
        try:
            P.CompactPartition(metadata, arrays, expected_partition_id=D._record_hash(self.body), budget=self.budget, check=cancel)
        except CancelledError as error:
            failure = error
        self.assertIsNotNone(failure)
        self.assertGreater(self.budget.reserved_bytes, before)
        failure = None
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)

    def test_large_list_requires_indexed_access(self):
        body = deepcopy(self.body)
        body['identity_start_cells'] = [dict(parent_cell_id=ident(str(i)), cell_id=ident(str(i+1))) for i in range(300)]
        view, _, _arrays = opened(body, self.supports, self.budget)
        rows = view.root().field('identity_start_cells')
        with self.assertRaises(P.PartitionTablesRefused):
            rows.row()
        self.assertEqual(rows.at(299).field('parent_cell_id').scalar().value, ident('299'))
        for bad in (-1, 300, True):
            with self.assertRaises(P.PartitionTablesRefused):
                rows.at(bad)

    def test_arraystore_append_reopen_unchanged_chunk_reuse(self):
        view, _, _arrays = opened(self.body, self.supports, self.budget)
        payload = view.storage_payload()
        limits = StoreLimits(chunk_bytes=256, max_array_bytes=2 << 20, max_store_bytes=16 << 20,
            max_manifest_bytes=256 << 10, sqlite_cache_bytes=65536, codec_workspace_bytes=65536)
        with tempfile.TemporaryDirectory(prefix='.pt-', dir=HERE.parents[4]) as directory:
            path = Path(directory)/'tables.sqlite'
            with ArrayStore(path, limits, budget=self.budget) as store:
                metadata, arrays = payload.value
                store.put(ident('partition-A'), arrays, metadata=metadata, budget=self.budget)
                with store._read_scope():
                    first = store._manifest(ident('partition-A'))
                first_chunks = store.statistics()['unique_chunks']
                store.put(ident('partition-B'), arrays, metadata=metadata, budget=self.budget)
                with store._read_scope():
                    second = store._manifest(ident('partition-B'))
                self.assertEqual(first['arrays'], second['arrays'])
                self.assertEqual(first_chunks, store.statistics()['unique_chunks'])
            with ArrayStore(path, limits, budget=self.budget) as store:
                restored = store.get(ident('partition-B'), budget=self.budget)
                again = P.CompactPartition(metadata, restored, expected_partition_id=view.partition_id, budget=self.budget)
                self.assertEqual(again.constraint(2, 'carried:edge').index, again.constraint(0, 'carried:edge').index)
                self.assertEqual(b''.join(again.iter_legacy_json()), D._encoded(self.body))
                del again, restored


if __name__ == '__main__':
    unittest.main()
