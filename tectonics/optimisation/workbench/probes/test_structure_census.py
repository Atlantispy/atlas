"""Bounded synthetic boundary tests; no original database or science execution."""

from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

import structure_census as C
import structure_json as J


def noop():
    pass


class _Store:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def iter_chunks(self, key, name, *, budget):
        self.calls.append((key, name, budget))
        for offset, raw in self.rows:
            yield offset, np.frombuffer(raw, dtype=np.uint8)


class StructureCensusTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sc-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.serial = 0

    def record(self, value=None, *, raw=None):
        self.serial += 1
        path = self.directory / ('record-%d.json' % self.serial)
        path.write_bytes(C.canonical(value) if raw is None else raw)
        return {'path': path, 'scan': J.scan(path, select=C.select)}

    def scratch(self, rows, *, check=noop):
        store = _Store(rows)
        budget = object()
        scratch = C.Scratch(self.directory / 'structure-scratch', store, budget, check)
        return scratch, store, budget

    @staticmethod
    def description(size, dtype='|u1', shape=None):
        return {'dtype': dtype, 'shape': [size] if shape is None else shape, 'chunks': []}

    def test_graph_complete_copy_and_equal_field_byte_count(self):
        graph = {'edges': [1, 2], 'name': 'λ', 'nodes': {'n': 4}}
        records = {'spatial-record:graph': self.record(graph),
                   'spatial-record:exchange': self.record({'finite_proposal': {'graph': graph}})}
        result = C.graph_overlap(records, noop)
        self.assertEqual(result['status'], 'MEASURED')
        self.assertTrue(result['complete_byte_equal'])
        self.assertTrue(all(row['byte_equal'] for row in result['fields']))
        self.assertEqual(result['equal_field_value_bytes'],
                         sum(len(C.canonical(value)) for value in graph.values()))
        self.assertLess(result['equal_field_value_bytes'], result['graph_bytes'])
        self.assertEqual(result['graph_bytes'], result['embedded_graph_bytes'])

    def test_graph_equal_length_difference_and_missing_field(self):
        graph = {'same': [1, 2], 'different': 'aa', 'missing': 9}
        copied = {'same': [1, 2], 'different': 'bb'}
        records = {'spatial-record:graph': self.record(graph),
                   'spatial-record:exchange': self.record({'finite_proposal': {'graph': copied}})}
        result = C.graph_overlap(records, noop)
        fields = {row['name']: row for row in result['fields']}
        self.assertFalse(result['complete_byte_equal'])
        self.assertFalse(fields['different']['byte_equal'])
        self.assertEqual(fields['different']['graph_bytes'], fields['different']['finite_graph_bytes'])
        self.assertFalse(fields['missing']['byte_equal'])
        self.assertIsNone(fields['missing']['finite_graph_bytes'])
        self.assertTrue(fields['same']['byte_equal'])
        self.assertEqual(result['equal_field_value_bytes'], len(C.canonical(graph['same'])))

    def test_graph_semantic_equality_does_not_claim_byte_equality(self):
        graph = {'a': 1, 'b': 2}
        records = {'spatial-record:graph': self.record(raw=b' {"b":2,"a":1}\n'),
                   'spatial-record:exchange': self.record({'finite_proposal': {'graph': graph}})}
        result = C.graph_overlap(records, noop)
        self.assertFalse(result['complete_byte_equal'])
        self.assertTrue(all(row['byte_equal'] for row in result['fields']))
        self.assertEqual(result['equal_field_value_bytes'], 2)

    def test_graph_absence_is_not_a_false_comparison(self):
        self.assertEqual(C.graph_overlap({}, noop)['status'], 'NOT_PRESENT')
        records = {'spatial-record:graph': self.record({'a': 1}),
                   'spatial-record:exchange': self.record({'finite_proposal': {}})}
        result = C.graph_overlap(records, noop)
        self.assertEqual(result['status'], 'NOT_PRESENT')
        self.assertNotIn('complete_byte_equal', result)

    def test_support_matching_ids_also_requires_body_equality(self):
        support = {'kind': 'cell', 'value': 1}
        ident = sha256(C.canonical(support)).hexdigest()
        partition = self.record({'supports': [support], 'support_ids': [ident]})
        records = {'partition-record:partition': partition,
                   'spatial-record:mesh': self.record({'support_tables': {'differential_supports':
                       {ident: support, 'unreferenced': {'value': 3}}}})}
        result = C.support_overlap(records, noop)
        self.assertEqual(result['matching_ids'], 1)
        self.assertEqual(result['identical_supports'], 1)
        self.assertEqual(result['different_bytes_for_same_id'], 0)
        self.assertEqual(result['partition_id_hash_mismatches'], 0)
        self.assertEqual(result['shared_mesh_value_bytes'], len(C.canonical(support)))
        self.assertEqual(result['mesh_ids_absent_from_partition'], 1)
        records['spatial-record:mesh'] = self.record({'support_tables': {'differential_supports':
            {ident: {'kind': 'cell', 'value': 2}}}})
        result = C.support_overlap(records, noop)
        self.assertEqual(result['matching_ids'], 1)
        self.assertEqual(result['identical_supports'], 0)
        self.assertEqual(result['different_bytes_for_same_id'], 1)
        self.assertEqual(result['shared_mesh_value_bytes'], 0)

    def test_support_id_mismatch_and_unmatched_id_remain_visible(self):
        support = {'value': 1}
        records = {'partition-record:partition': self.record({'supports': [support], 'support_ids': ['wrong']}),
                   'spatial-record:mesh': self.record({'support_tables': {'differential_supports': {'other': support}}})}
        result = C.support_overlap(records, noop)
        self.assertEqual(result['partition_id_hash_mismatches'], 1)
        self.assertEqual(result['matching_ids'], 0)
        self.assertEqual(result['identical_supports'], 0)
        self.assertEqual(result['different_bytes_for_same_id'], 0)
        self.assertEqual(result['mesh_ids_absent_from_partition'], 1)

    def test_support_position_and_id_type_guards(self):
        mesh = self.record({'support_tables': {'differential_supports': {}}})
        cases = [({'supports': [{}], 'support_ids': []}, 'positions differ'),
                 ({'supports': [{}], 'support_ids': [1]}, 'not text')]
        for partition, message in cases:
            with self.subTest(partition=partition):
                records = {'partition-record:partition': self.record(partition), 'spatial-record:mesh': mesh}
                with self.assertRaisesRegex(ValueError, message):
                    C.support_overlap(records, noop)
        self.assertEqual(C.support_overlap({}, noop)['status'], 'NOT_PRESENT')

    def test_static_absence_is_distinct_from_difference(self):
        head = {'grid_lines': [1, 2], 'support_tables': {'voxels': [3], 'cones': [4]}}
        root = {'grid_lines': [1, 2], 'support_tables': {'voxels': [8], 'cones': [4]}}
        records = {'spatial-record:mesh': self.record(head),
                   'partition-record:partition': self.record({'grid_lines': [1, 9]})}
        result = C.static_comparisons(records, self.record(root), noop)
        rows = {(row['comparison'], tuple(row['path'])): row for row in result['comparisons']}
        self.assertEqual(rows[('head mesh versus partition', ('grid_lines',))]['status'], 'DIFFERENT')
        prefix = 'root mesh versus head mesh'
        self.assertEqual(rows[(prefix, ('grid_lines',))]['status'], 'BYTE_EQUAL')
        self.assertEqual(rows[(prefix, ('support_tables', 'voxels'))]['status'], 'DIFFERENT')
        self.assertEqual(rows[(prefix, ('support_tables', 'cones'))]['status'], 'BYTE_EQUAL')
        absent = rows[(prefix, ('support_tables', 'radial_layers'))]
        self.assertEqual(absent['status'], 'ABSENT')
        self.assertIsNone(absent['left_bytes'])
        self.assertIsNone(absent['right_bytes'])
        self.assertTrue(all(row['status'] == 'ABSENT' for row in C.static_comparisons({}, None, noop)['comparisons']))

    def test_static_repeated_aggregate_cannot_be_used_as_exact_span(self):
        repeated = self.record([{'grid_lines': [1]}, {'grid_lines': [1]}])
        normal = self.record({'grid_lines': [1]})
        with self.assertRaisesRegex(ValueError, 'not a single value'):
            C.static_comparisons({'spatial-record:mesh': repeated,
                                  'partition-record:partition': normal}, None, noop)

    def test_scratch_spools_contiguous_numpy_chunks_and_cleans_only_owned_files(self):
        sentinel = self.directory / 'keep.txt'
        sentinel.write_bytes(b'keep')
        scratch, store, budget = self.scratch([(0, b'ab'), (2, b'cde')])
        path, digest = scratch.spool('snapshot', 'json', self.description(5))
        self.assertEqual(path.read_bytes(), b'abcde')
        self.assertEqual(digest, sha256(b'abcde').hexdigest())
        self.assertEqual(store.calls, [('snapshot', 'json', budget)])
        self.assertEqual(scratch.total, 5)
        scratch.remove()
        self.assertFalse(scratch.directory.exists())
        self.assertEqual(sentinel.read_bytes(), b'keep')

    def test_scratch_rejects_offsets_declared_overflow_and_short_stream(self):
        cases = [([(0, b'ab'), (3, b'c')], 3, 'noncontiguous'),
                 ([(0, b'ab'), (1, b'c')], 3, 'noncontiguous'),
                 ([(0, b'abcd')], 3, 'exceeds declared'),
                 ([(0, b'ab')], 3, 'size differs')]
        for rows, declared, message in cases:
            with self.subTest(message=message, rows=rows):
                scratch, _, _ = self.scratch(rows)
                with self.assertRaisesRegex(ValueError, message):
                    scratch.spool('s', 'a', self.description(declared))
                scratch.remove()

    def test_scratch_size_dtype_shape_disk_and_exclusive_directory_bounds(self):
        scratch, _, _ = self.scratch([(0, b'abc')])
        for description in (self.description(3, '<i4'), self.description(3, shape=[1, 3])):
            with self.subTest(description=description):
                with self.assertRaisesRegex(ValueError, 'one-dimensional byte array'):
                    scratch.spool('s', 'a', description)
        with patch.object(J, 'MAX_SOURCE_BYTES', 2):
            with self.assertRaisesRegex(ValueError, 'byte bound'):
                scratch.spool('s', 'a', self.description(3))
        with patch.object(C.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(ValueError, 'disk space'):
                scratch.spool('s', 'a', self.description(3))
        scratch.spool('s', 'a', self.description(3))
        with patch.object(C, 'MAX_SCRATCH', 5):
            with self.assertRaisesRegex(ValueError, 'byte bound'):
                scratch.spool('s', 'a', self.description(3))
        with self.assertRaisesRegex(ValueError, 'exclusive scratch'):
            C.Scratch(scratch.directory, _Store([]), object(), noop)
        with self.assertRaisesRegex(ValueError, 'selected run directory child'):
            C.Scratch(self.directory / 'wrong-name', _Store([]), object(), noop)
        self.assertEqual(scratch.total, 3)
        scratch.remove()

    def test_scratch_cancellation_preserves_exception_and_partial_owned_file(self):
        class Cancelled(Exception):
            pass

        calls = 0

        def check():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise Cancelled('original cancellation')

        scratch, _, _ = self.scratch([(0, b'ab'), (2, b'cd')], check=check)
        with self.assertRaisesRegex(Cancelled, 'original cancellation'):
            scratch.spool('s', 'a', self.description(4))
        self.assertEqual(scratch.files[0].read_bytes(), b'ab')
        scratch.remove()

    def test_scratch_cleanup_refuses_foreign_path_and_preserves_unknown_children(self):
        scratch, _, _ = self.scratch([])
        foreign = self.directory / 'foreign.txt'
        foreign.write_bytes(b'keep')
        scratch.files.append(foreign)
        with self.assertRaisesRegex(ValueError, 'scratch path changed'):
            scratch.remove()
        self.assertEqual(foreign.read_bytes(), b'keep')
        scratch.files.clear()
        unknown = scratch.directory / 'not-created-by-scratch.txt'
        unknown.write_bytes(b'keep')
        with self.assertRaises(OSError):
            scratch.remove()
        self.assertEqual(unknown.read_bytes(), b'keep')
        unknown.unlink()  # Test-owned fixture only, after proving preservation.
        scratch.remove()

    def test_restart_inventory_separates_unique_arrays_from_documented_rereads(self):
        head_names = ['source-audit:source', 'collar', 'exterior-fv:outside',
                      'spatial-record:state', 'spatial-record:mesh',
                      'differential-record:geometry', 'differential-network:node',
                      'partition-record:partition', 'spatial-record:graph']
        manifests = {'head': {'arrays': {name: {} for name in head_names}},
                     'root': {'arrays': {name: {} for name in C.ROOT_ARRAYS}}}
        head_sizes = {name: i + 1 for i, name in enumerate(head_names)}
        root_sizes = {name: 10 * (i + 1) for i, name in enumerate(C.ROOT_ARRAYS)}
        summaries = {key: {'arrays': {name: {'logical_bytes': size} for name, size in sizes.items()}}
                     for key, sizes in [('head', head_sizes), ('root', root_sizes)]}
        groups = {'source_audit': [{'name': 'source'}], 'full_collar': [{'name': 'collar'}],
                  'exterior': [{'name': 'outside'}]}
        endpoint = {'head_key': 'head', 'root_key': 'root'}
        result = C.restart_inventory(manifests, summaries, endpoint, groups)
        unique = sum(head_sizes.values()) - head_sizes['spatial-record:graph'] + sum(root_sizes.values())
        reread = root_sizes['component_mass_kg'] + root_sizes['enthalpy_j']
        self.assertEqual(result['unique_selected_array_bytes'], unique)
        self.assertEqual(result['decoded_bytes_with_documented_rereads'], unique + reread)
        self.assertEqual(result['additional_head_census_arrays'], ['spatial-record:graph'])
        self.assertEqual(len(result['stages']), 8)
        duplicate = result['stages'][-1]
        self.assertEqual(duplicate['stage'], 'initial workload duplicate read')
        self.assertEqual(duplicate['arrays'], ['component_mass_kg', 'enthalpy_j'])
        self.assertEqual(duplicate['logical_bytes'], reread)
        del manifests['root']['arrays']['enthalpy_j']
        with self.assertRaisesRegex(ValueError, 'selection missing'):
            C.restart_inventory(manifests, summaries, endpoint, groups)

    def test_small_decode_and_byte_comparison_refuse_truncated_spans(self):
        record = self.record({'a': [1, 2]})
        row = record['scan']['fields'][0]
        self.assertEqual(C.read_small(record['path'], row), [1, 2])
        with patch.object(C, 'MAX_SMALL', row['bytes'] - 1):
            with self.assertRaisesRegex(ValueError, 'small decode bound'):
                C.read_small(record['path'], row)
        self.assertEqual(C.span_hash(record['path'], row, noop), sha256(b'[1,2]').hexdigest())
        other = self.record({'a': [1, 2]})
        other['path'].write_bytes(b'{"a":[')
        with self.assertRaisesRegex(ValueError, 'truncated'):
            C.same_span(record['path'], row, other['path'], row, noop)
        with self.assertRaisesRegex(ValueError, 'span changed'):
            C.read_small(other['path'], row)
        with self.assertRaisesRegex(ValueError, 'truncated'):
            C.span_hash(other['path'], row, noop)

    def heat_fixture(self, *, ledger_change=None, field_change=None, binding_change=None):
        ledger = {'cell_ids': ['cell-0', 'cell-1'], 'face_ids': ['face-0'],
                  'exact_corrected_enthalpy_j': [['0x1', '0x1'], ['0x2', '0x1']],
                  'exact_retained_solver_residual_j': [['0x0', '0x1'], ['0x0', '0x1']],
                  'exact_stock_projection_residual_j': [['0x0', '0x1'], ['0x0', '0x1']],
                  'exact_cell_storage_residual_j': [['0x0', '0x1'], ['0x0', '0x1']],
                  'exact_paired_face_energy_j': [['0x3', '0x1']]}
        if ledger_change:
            ledger_change(ledger)
        raw = C.canonical(ledger)
        path = self.directory / 'heat-metadata.json'
        path.write_bytes(raw)
        metadata = {'metadata_sha256': sha256(raw).hexdigest(), 'metadata_bytes': len(raw),
                    'fields': {'native-%d' % i: 'binding-%d' % i for i in range(5)}}
        if binding_change:
            binding_change(metadata)
        arrays = {'metadata_utf8': self.description(len(raw)),
                  **{'native-%d' % i: self.description(2, '<f8') for i in range(5)}}
        if field_change:
            field_change(arrays)
        manifest = {'metadata': metadata, 'arrays': arrays}
        manifests = {'heat-key': manifest}
        summaries = {'heat-key': C.manifest_summary(manifest, len(C.canonical(manifest)))}
        checkpoint = {'invocation': 'heat-key', 'metadata': json.loads(C.canonical(metadata))}
        records = {'spatial-record:heat': self.record({'checkpoint': checkpoint})}
        calls = []

        def spool(key, name, description):
            calls.append((key, name, description))
            return path, sha256(raw).hexdigest()

        return records, manifests, summaries, SimpleNamespace(spool=spool), calls

    def test_heat_metadata_binding_dimensions_and_five_native_float64_arrays(self):
        records, manifests, summaries, scratch, calls = self.heat_fixture()
        observations, result = [], {'records': {}}
        measured = C.heat_measure(records, manifests, summaries, scratch, noop, observations.append, result)
        self.assertEqual(measured['status'], 'MEASURED')
        self.assertEqual((measured['n'], measured['nf']), (2, 1))
        self.assertEqual(measured['native_field_bytes'], 5 * 2 * 8)
        self.assertEqual(len(measured['native_fields']), 5)
        self.assertEqual(measured['rational_strings']['pair_count'], 9)
        self.assertEqual(measured['native_field_bindings'], manifests['heat-key']['metadata']['fields'])
        self.assertEqual(observations, ['structure-heat-ledger-complete'])
        self.assertEqual(calls, [('heat-key', 'metadata_utf8', manifests['heat-key']['arrays']['metadata_utf8'])])
        saved = result['records']['heat:metadata_utf8']
        self.assertEqual(saved['sha256'], manifests['heat-key']['metadata']['metadata_sha256'])
        self.assertEqual(saved['filebytes'], measured['metadata_bytes'])
        self.assertEqual(C.heat_measure({}, {}, {}, scratch, noop, observations.append, result)['status'], 'NOT_PRESENT')

    def test_heat_hash_and_checkpoint_metadata_tampering_refused(self):
        fixtures = [dict(binding_change=lambda value: value.update(metadata_sha256='0' * 64)),
                    dict(binding_change=lambda value: value.update(metadata_bytes=value['metadata_bytes'] + 1))]
        for options in fixtures:
            with self.subTest(options=options):
                records, manifests, summaries, scratch, _ = self.heat_fixture(**options)
                with self.assertRaisesRegex(ValueError, 'ledger bytes differ'):
                    C.heat_measure(records, manifests, summaries, scratch, noop, noop, {'records': {}})
        records, manifests, summaries, scratch, _ = self.heat_fixture()
        manifests['heat-key']['metadata']['fields']['native-0'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'checkpoint metadata differs'):
            C.heat_measure(records, manifests, summaries, scratch, noop, noop, {'records': {}})

    def test_heat_cell_and_face_coverage_refused(self):
        for name, message in [('exact_cell_storage_residual_j', 'cell ledger coverage'),
                              ('exact_paired_face_energy_j', 'face ledger coverage')]:
            with self.subTest(field=name):
                records, manifests, summaries, scratch, _ = self.heat_fixture(
                    ledger_change=lambda value: value[name].pop())
                with self.assertRaisesRegex(ValueError, message):
                    C.heat_measure(records, manifests, summaries, scratch, noop, noop, {'records': {}})

    def test_heat_native_count_dtype_and_shape_refused(self):
        changes = [lambda arrays: arrays.pop('native-0'),
                   lambda arrays: arrays['native-0'].update(dtype='<f4'),
                   lambda arrays: arrays['native-0'].update(shape=[1, 2])]
        for change in changes:
            with self.subTest(change=change):
                records, manifests, summaries, scratch, _ = self.heat_fixture(field_change=change)
                with self.assertRaisesRegex(ValueError, 'native field inventory differs'):
                    C.heat_measure(records, manifests, summaries, scratch, noop, noop, {'records': {}})


if __name__ == '__main__':
    unittest.main()
