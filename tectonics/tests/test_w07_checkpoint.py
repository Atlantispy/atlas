"""W07 codec checks with real snapshot objects and bounded synthetic fields.

These exercise lossless storage, not geological acceptance or solver accuracy.
ArrayStore transactions and workflow source/parent checks belong to their owner.
"""
from concurrent.futures import CancelledError
from copy import deepcopy
import hashlib
import json
from threading import Event
import unittest

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.regional_checkpoint import pack_regional_snapshots, restore_regional_snapshots
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.resources import MemoryLimitError, WorkBudget


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def seal(metadata):
    metadata['content_id'] = digest({k: v for k, v in metadata.items() if k != 'content_id'})
    return metadata


def snapshots():
    velocity = np.arange(20., dtype=np.float64).reshape(4, 5)
    mechanical = RegionalMechanicalSnapshot({
        'schema': 'atlas.regional-mechanical-snapshot.v1', 'source_status': 'WORKING NON-CANON',
        'request_id': 'a'*64, 'context_id': 'b'*64, 'steady_snapshot': True,
        'definition': {'nx': 4, 'nz': 4, 'height_m': 4000., 'width_m': 4000.},
        'diagnostics': {'iterations': 1, 'physical_pressure_defined': True},
        'provenance': ['synthetic SI fixture', '\u03bc source'],
    }, {'u_m_s': velocity, 'force_u_n_m3': np.zeros((4, 5)),
        'physical_pressure_pa': velocity.reshape(5, 4),
        'accounts': np.array([-0., 0., 1.]), 'exports': np.empty((0, 3)),
        'time_s': np.array(2.)})
    surface = RegionalMechanicalSnapshot({
        'schema': 'atlas.regional-surface-state.v1', 'source_status': 'WORKING NON-CANON',
        'mechanical_result_id': mechanical.result_id, 'parent_state_id': None,
        'time_s': 2., 'thermal_owner': 'retained explicit input',
    }, {'u_m_s': velocity.copy(), 'phase_fraction': np.zeros((4, 5)),
        'surface_height_m': np.arange(5.), 'temperature_k': np.arange(16.).reshape(4, 4)+273.,
        'exports': np.empty((0, 3)), 'time_s': np.array(2.)})
    return {'mechanics': mechanical, 'surface': surface}


def forged(fields, metadata=None):
    """Bypass construction only to exercise refusal of malformed typed inputs."""
    metadata = {'schema': 'synthetic'} if metadata is None else metadata
    value = object.__new__(RegionalMechanicalSnapshot)
    object.__setattr__(value, '_metadata', encoded(metadata))
    object.__setattr__(value, '_fields', fields)
    object.__setattr__(value, 'result_id', digest({'metadata': metadata, 'arrays': {
        name: {'shape': shape, 'sha256': hashlib.sha256(raw).hexdigest()}
        for name, shape, raw in fields}}))
    return value


class RegionalCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.source = snapshots()

    def test_roundtrip_preserves_every_byte_descriptor_identity_and_immutability(self):
        budget = WorkBudget(128*1024*1024)
        arrays, metadata = pack_regional_snapshots(self.source, budget=budget)
        # JSON/storage decoding does not change catalogue meaning.
        supplied = {key: value.copy() for key, value in arrays.items()}
        received = json.loads(encoded(metadata))
        restored = restore_regional_snapshots(supplied, received, budget=budget)
        self.assertEqual(set(restored), set(self.source))
        for name, source in self.source.items():
            result = restored[name]
            self.assertIs(type(result), RegionalMechanicalSnapshot)
            self.assertIsNot(result, source)
            self.assertEqual(result.result_id, source.result_id)
            self.assertEqual(result.descriptor(), source.descriptor())
            self.assertEqual(result.array_names, source.array_names)
            for field in source.array_names:
                actual, expected = result.array(field), source.array(field)
                self.assertEqual(actual.shape, expected.shape)
                self.assertEqual(actual.dtype, expected.dtype)
                self.assertEqual(actual.tobytes(), expected.tobytes())
                with self.assertRaises(ValueError):
                    actual.setflags(write=True)
            with self.assertRaises(TectonicsError):
                result.result_id = 'changed'
        for value in supplied.values():
            value.fill(42.)
        received['snapshots'][0]['metadata']['source_status'] = 'altered caller data'
        self.assertEqual(restored['mechanics'].descriptor(), self.source['mechanics'].descriptor())
        self.assertEqual(restored['mechanics'].array('u_m_s').tobytes(),
                         self.source['mechanics'].array('u_m_s').tobytes())
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(budget.peak_reserved_bytes, metadata['resources']['restore_work_bytes'])

    def test_dedup_precedes_copy_and_keeps_shape_signed_zero_small_and_empty_fields(self):
        arrays, metadata = pack_regional_snapshots(self.source)
        resources = metadata['resources']
        self.assertEqual(resources['logical_array_bytes'], 1008)
        self.assertEqual(resources['stored_array_bytes'], 680)
        self.assertEqual(resources['stored_array_bytes'], sum(value.nbytes for value in arrays.values()))
        self.assertEqual(resources['field_count'], 12)
        self.assertEqual(len(arrays), 8)
        fields = {row['name']: {f['name']: f['array'] for f in row['fields']}
                  for row in metadata['snapshots']}
        self.assertEqual(fields['mechanics']['u_m_s'], fields['surface']['u_m_s'])
        self.assertEqual(fields['mechanics']['force_u_n_m3'], fields['surface']['phase_fraction'])
        self.assertNotEqual(fields['mechanics']['u_m_s'], fields['mechanics']['physical_pressure_pa'])
        for value in arrays.values():
            with self.assertRaises(ValueError):
                value.setflags(write=True)
        self.assertEqual(arrays[fields['mechanics']['exports']].shape, (0, 3))
        self.assertEqual(arrays[fields['mechanics']['time_s']].shape, ())
        self.assertTrue(np.signbit(arrays[fields['mechanics']['accounts']][0]))
        # Names/order of the input mapping have no effect on codec content.
        again, other = pack_regional_snapshots(dict(reversed(tuple(self.source.items()))))
        self.assertEqual(other, metadata)
        self.assertEqual(tuple(again), tuple(arrays))

    def test_missing_extra_wrong_dtype_shape_layout_and_modified_payload_refused(self):
        arrays, metadata = pack_regional_snapshots(self.source)
        key = next(key for key, value in arrays.items() if value.shape == (4, 5))
        wrong = dict(arrays); wrong[key] = arrays[key].copy(); wrong[key][0, 0] += 1.
        cases = [dict(arrays, extra=np.zeros(1)), {k: v for k, v in arrays.items() if k != key},
            dict(arrays, **{key: arrays[key].astype(np.float32)}),
            dict(arrays, **{key: arrays[key].reshape(5, 4)}),
            dict(arrays, **{key: np.asfortranarray(arrays[key])}), wrong]
        for index, values in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(TectonicsError):
                restore_regional_snapshots(values, metadata)

    def test_metadata_corruption_missing_extra_duplicate_records_and_bindings_refused(self):
        arrays, original = pack_regional_snapshots(self.source)
        def changed(edit):
            value = deepcopy(original); edit(value); return value
        cases = [
            changed(lambda m: m.update(version=2)),
            changed(lambda m: m.update(version=True)),
            changed(lambda m: m.update(extra='unknown')),
            changed(lambda m: m.pop('schema')),
            changed(lambda m: m['snapshots'].append(deepcopy(m['snapshots'][0]))),
            changed(lambda m: m['arrays'].append(deepcopy(m['arrays'][0]))),
            changed(lambda m: m['snapshots'][0]['fields'].append(deepcopy(m['snapshots'][0]['fields'][0]))),
            changed(lambda m: m['snapshots'][0]['fields'].pop()),
            changed(lambda m: m['snapshots'][0]['fields'][0].update(array='missing')),
            changed(lambda m: m['snapshots'][0].update(result_id='0'*64)),
            changed(lambda m: m['snapshots'][0]['metadata'].update(source_status='altered')),
            changed(lambda m: m['resources'].update(logical_array_bytes=1)),
            changed(lambda m: m.update(content_id='0'*64)),
        ]
        for index, metadata in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(TectonicsError):
                restore_regional_snapshots(arrays, metadata)

    def test_self_consistent_unreferenced_array_catalogue_entry_refused(self):
        arrays, metadata = pack_regional_snapshots(self.source)
        metadata = deepcopy(metadata)
        record = metadata['snapshots'][0]
        field = next(f for f in record['fields'] if f['name'] == 'accounts')
        record['fields'].remove(field)
        entries = {entry['name']: entry for entry in metadata['arrays']}
        record['result_id'] = digest({'metadata': record['metadata'], 'arrays': {
            f['name']: {'shape': entries[f['array']]['shape'], 'sha256': entries[f['array']]['sha256']}
            for f in record['fields']}})
        seal(metadata)
        with self.assertRaisesRegex(TectonicsError, 'unreferenced'):
            restore_regional_snapshots(arrays, metadata)

    def test_shape_name_and_metadata_bounds_checked_before_payload_allocation(self):
        small = np.zeros(1).tobytes()
        invalid = [forged((('field', (2_097_153,), b''),)),
                   forged((('field', (2_097_152, 2_097_152), b''),)),
                   forged((('field', (1,)*9, small),)),
                   forged((('../field', (1,), small),)),
                   forged((('field', (True,), small),)),
                   forged((('field', (2,), small),)),
                   forged((('field', (1,), small),), {'text': 'x'*140000})]
        for index, value in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(TectonicsError):
                pack_regional_snapshots({'snapshot': value})
        arrays, metadata = pack_regional_snapshots(self.source)
        oversized = deepcopy(metadata)
        oversized['arrays'][0]['shape'] = [2_097_152, 2_097_152]
        with self.assertRaisesRegex(TectonicsError, 'byte limit'):
            restore_regional_snapshots(arrays, oversized)
        oversized = deepcopy(metadata)
        oversized['snapshots'][0]['metadata'] = {'text': 'x'*600000}
        with self.assertRaisesRegex(TectonicsError, 'text limit'):
            restore_regional_snapshots(arrays, oversized)

    def test_nonfinite_fields_and_forged_snapshot_identity_refused(self):
        nonfinite = forged((('temperature_k', (1,), np.array([np.nan]).tobytes()),))
        with self.assertRaisesRegex(TectonicsError, 'nonfinite'):
            pack_regional_snapshots({'thermal': nonfinite})
        source = snapshots()['mechanics']
        object.__setattr__(source, 'result_id', '0'*64)
        with self.assertRaisesRegex(TectonicsError, 'identity mismatch'):
            pack_regional_snapshots({'mechanics': source})

    def test_budget_refusal_and_cancellation_release_all_reservations(self):
        tiny = WorkBudget(1024)
        with self.assertRaises(MemoryLimitError):
            pack_regional_snapshots(self.source, budget=tiny)
        arrays, metadata = pack_regional_snapshots(self.source)
        with self.assertRaises(MemoryLimitError):
            restore_regional_snapshots(arrays, metadata, budget=tiny)
        self.assertEqual(tiny.reserved_bytes, 0)
        cancelled = Event(); cancelled.set()
        for function, args in ((pack_regional_snapshots, (self.source,)),
                               (restore_regional_snapshots, (arrays, metadata))):
            with self.assertRaises(CancelledError):
                function(*args, cancel=cancelled)
        class DuringWork:
            calls = 0
            def is_set(self):
                self.calls += 1
                return self.calls >= 4
        budget = WorkBudget(128*1024*1024)
        for function, args in ((pack_regional_snapshots, (self.source,)),
                               (restore_regional_snapshots, (arrays, metadata))):
            with self.assertRaises(CancelledError):
                function(*args, cancel=DuringWork(), budget=budget)
            self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
