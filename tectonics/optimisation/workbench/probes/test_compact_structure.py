"""Synthetic native manifests with current compact metadata/reference layouts.

No codec is imported and no encoded payload's validity is claimed here.
"""
import copy
from hashlib import sha256
import unittest

import compact_structure as C


def ident(text):
    return sha256(text.encode()).hexdigest()


def description(label, count, dtype='|u1', chunk_bytes=16):
    width = chunk_bytes//int(dtype[-1])
    return dict(dtype=dtype, shape=[count],
                chunks=[ident(label+str(n)) for n in range((count+width-1)//width)])


def manifest(key, arrays, metadata):
    return dict(schema=C.ARRAY_SCHEMA, invocation=key, arrays=arrays, metadata=metadata,
                execution_mode='strict')


def codec_arrays(arrays):
    return {k: dict(dtype=d['dtype'], shape=d['shape'], sha256=ident(k)) for k, d in arrays.items()}


def fixture():
    # Structural snapshots mirror the current source contracts. Codec column
    # contents are deliberately absent: the helper only inventories descriptors.
    producer = dict(collar_plan_id=ident('collar'), role='lossless indexed storage')
    mesh_id, partition_id, content = ident('mesh'), ident('partition'), ident('support')
    support = dict(schema=C.SUPPORT_SCHEMA, content_sha256=content, nbytes=19, authority=C.AUTHORITY)
    support_key = C._digest(support)
    support_array = description('packed', 19)
    columns = {'cell.id': description('cell', 2, '<u8')}
    mesh_codec = dict(schema=C.MESH_CODEC, geometry_id=mesh_id, header={}, grid_fields=[],
                      support_tables=['differential_supports'], required_faces_present=True,
                      cell_count=2, face_count=3, arrays=codec_arrays(columns))
    mesh = dict(schema=C.MESH_SCHEMA, geometry_id=mesh_id, codec_metadata=mesh_codec,
                supports={content: 19}, source_producer=producer, parent_snapshot=None,
                authority=C.AUTHORITY)
    mesh_key = C._digest(mesh)
    mesh_arrays = {'mesh:cell.id': columns['cell.id'], 'support-blobs': support_array}
    mesh_ref = dict(schema=C.MESH_SCHEMA, snapshot_key=mesh_key, geometry_id=mesh_id,
                    source_producer=producer,
                    array_bindings={k: C._digest(v) for k, v in mesh_arrays.items()})
    partition_arrays = {'node.kind': description('node', 3)}
    partition_codec = dict(schema=C.PARTITION_CODEC, partition_id=partition_id, body_node=0,
                           support_count=1, arrays=codec_arrays(partition_arrays))
    partition_binding = dict(schema=C.PARTITION_SCHEMA, partition_id=partition_id, source_producer=producer)
    partition_key = C._digest(partition_binding)
    partition = dict(partition_binding, codec_metadata=partition_codec, authority=C.AUTHORITY)
    partition_ref = dict(schema=C.PARTITION_SCHEMA, snapshot_key=partition_key,
                         partition_id=partition_id, source_producer=producer,
                         array_bindings={k: C._digest(v) for k, v in partition_arrays.items()})
    binding = dict(schema=C.LINK_SCHEMA, geometry_id=mesh_id, source_producer=producer)
    link_key = C._digest(binding)
    workflow_key = ident('workflow')
    workflow_arrays = {'spatial-mesh:'+k: v for k, v in mesh_arrays.items()}
    workflow_arrays.update({'partition-dag:'+k: v for k, v in partition_arrays.items()})
    workflow_arrays['enthalpy_j'] = description('enthalpy', 2, '<f8')
    rows = {
        support_key: manifest(support_key, {'bytes': support_array}, support),
        mesh_key: manifest(mesh_key, mesh_arrays, mesh),
        partition_key: manifest(partition_key, partition_arrays, partition),
        link_key: manifest(link_key, mesh_arrays, dict(binding=binding, mesh_reference=mesh_ref)),
        workflow_key: manifest(workflow_key, workflow_arrays,
                               dict(schema=C.WORKFLOW_SCHEMA, compact_partition=partition_ref,
                                    exterior_state=dict(compact_mesh=mesh_ref))),
    }
    return copy.deepcopy(rows), dict(mesh=mesh_key, partition=partition_key, link=link_key,
                                    support=support_key, workflow=workflow_key)


class InventoryTests(unittest.TestCase):
    def test_packed_mesh_partition_and_aliases_preserve_sharing(self):
        rows, keys = fixture()
        before = copy.deepcopy(rows)
        result = C.inventory(rows, chunk_bytes=16)
        self.assertEqual(rows, before)
        self.assertEqual(result['status'], 'PASS_MANIFEST_INVENTORY_ONLY')
        self.assertEqual(result['totals']['logical_array_bytes'], 146)
        self.assertEqual(result['totals']['unique_referenced_raw_bytes'], 54)
        self.assertEqual(result['totals']['repeated_reference_raw_bytes'], 92)
        self.assertEqual(result['totals']['unique_chunk_references'], 5)
        self.assertIsNone(result['totals']['physical_encoded_bytes'])
        self.assertEqual(len(result['compact']['roots']), 2)
        self.assertEqual(len(result['compact']['aliases']), 3)
        mesh = next(r for r in result['compact']['roots'] if r['key'] == keys['mesh'])
        self.assertEqual(mesh['packed_support_bytes'], 19)
        self.assertEqual(mesh['unique_referenced_raw_bytes'], 35)
        self.assertEqual(result['compact']['compact_snapshot_count'], 5)
        self.assertEqual(result['compact']['unique_referenced_raw_bytes'], 54)

    def test_successor_nested_partition_reference(self):
        rows, keys = fixture()
        meta = rows[keys['workflow']]['metadata']
        meta['differential_partition'] = dict(compact_partition=meta.pop('compact_partition'))
        result = C.inventory(rows, chunk_bytes=16)
        self.assertIn('workflow-partition-header', [r['location'] for r in result['compact']['aliases']])

    def test_noncompact_is_other_not_claimed_legacy(self):
        key = ident('plain')
        result = C.inventory({key: manifest(key, {'x': description('x', 3, '<f8')}, {})}, chunk_bytes=17)
        self.assertEqual(result['compact']['status'], 'ABSENT')
        self.assertEqual(result['compact']['other_snapshot_count'], 1)
        self.assertEqual(result['totals']['unique_referenced_raw_bytes'], 24)

    def test_conflicting_chunk_dtype_and_final_size_refuse(self):
        for dtype, count in (('<u8', 2), ('|u1', 15)):
            key = ident('collision')
            first, second = description('same', 16), description('same', count, dtype)
            with self.subTest(dtype=dtype, count=count), self.assertRaisesRegex(C.CompactInventoryRefused, 'incompatible dtype or byte count'):
                C.inventory({key: manifest(key, {'a': first, 'b': second}, {})}, chunk_bytes=16)

    def test_unknown_versions_and_locations_refuse(self):
        for meta in ({'schema': 'atlas.compact-mesh-store.v3'},
                     {'codec_metadata': {'schema': 'atlas.compact-exterior-mesh.v2'}},
                     {'compact_future': {}}, {'schema': C.MESH_CODEC}):
            key = ident('future')
            with self.subTest(meta=meta), self.assertRaises(C.CompactInventoryRefused):
                C.inventory({key: manifest(key, {'x': description('x', 1)}, meta)}, chunk_bytes=16)

    def test_missing_target_and_changed_alias_refuse(self):
        rows, keys = fixture()
        del rows[keys['mesh']]
        with self.assertRaisesRegex(C.CompactInventoryRefused, 'target missing'):
            C.inventory(rows, chunk_bytes=16)
        rows, keys = fixture()
        rows[keys['workflow']]['arrays']['spatial-mesh:mesh:cell.id']['chunks'][0] = ident('changed')
        with self.assertRaisesRegex(C.CompactInventoryRefused, 'descriptor binding differs'):
            C.inventory(rows, chunk_bytes=16)

    def test_codec_shape_and_double_partition_reference_refuse(self):
        rows, keys = fixture()
        rows[keys['partition']]['metadata']['codec_metadata']['arrays']['node.kind']['shape'] = [4]
        with self.assertRaisesRegex(C.CompactInventoryRefused, 'dtype or shape differs'):
            C.inventory(rows, chunk_bytes=16)
        rows, keys = fixture()
        meta = rows[keys['workflow']]['metadata']
        meta['differential_partition'] = dict(compact_partition=meta['compact_partition'])
        with self.assertRaisesRegex(C.CompactInventoryRefused, 'reference/alias coverage'):
            C.inventory(rows, chunk_bytes=16)

    def test_bounds_and_zero_length_arrays(self):
        key = ident('empty-array')
        result = C.inventory({key: manifest(key, {'empty': description('empty', 0)}, {})}, chunk_bytes=16)
        self.assertEqual(result['totals']['unique_referenced_raw_bytes'], 0)
        with self.assertRaises(C.CompactInventoryRefused):
            C.inventory({}, chunk_bytes=0)
        nested = {}
        for _ in range(66):
            nested = dict(child=nested)
        with self.assertRaisesRegex(C.CompactInventoryRefused, 'metadata census bound'):
            C.inventory({key: manifest(key, {'empty': description('empty', 0)}, nested)}, chunk_bytes=16)


if __name__ == '__main__':
    unittest.main()
