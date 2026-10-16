"""Pure Step 3 wire fixtures: no database, codec, resolver or simulation."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
import unittest
from unittest.mock import patch

import compact_contracts as C


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def sample():
    return C.SegmentRef(
        schema='atlas.segment-ref.v1',
        root_key=C.SnapshotLocator('a' * 64, 3, 'b' * 64),
        identity=C.LogicalIdentity('caller.graph.v7', 'c' * 64, 600 * 1024 * 1024),
        logical_bytes=600 * 1024 * 1024,
        array_bindings=C.BindingIndexRef('atlas.binding-index.v1',
                                        C.SnapshotLocator('a' * 64, 1, 'd' * 64),
                                        'e' * 64, 17),
        merkle_root='f' * 64)


def assign(row, path, value):
    target = row
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


class SegmentReferenceTests(unittest.TestCase):
    def test_roundtrip_exact_six_fields_and_canonical_bytes(self):
        ref = sample()
        row = ref.to_wire()
        self.assertEqual(set(row), {'schema', 'root_key', 'identity', 'logical_bytes',
                                    'array_bindings', 'merkle_root'})
        raw = canonical(row)
        self.assertEqual(ref.to_json(), raw)
        self.assertEqual(C.SegmentRef.from_json(raw), ref)
        self.assertEqual(C.SegmentRef.from_json(raw.decode('ascii')), ref)
        self.assertEqual(C.SegmentRef.from_wire(row), ref)
        self.assertLessEqual(len(raw), 4096)

    def test_frozen_nested_values_and_detached_wire(self):
        ref = sample()
        with self.assertRaises(FrozenInstanceError):
            ref.logical_bytes = 0
        with self.assertRaises(FrozenInstanceError):
            ref.root_key.interval = 4
        row = ref.to_wire()
        row['root_key']['interval'] = 0
        row['array_bindings']['root_key']['workflow_id'] = '0' * 64
        self.assertEqual(ref.root_key.interval, 3)
        self.assertEqual(ref.array_bindings.root_key.workflow_id, 'a' * 64)

    def test_unknown_missing_and_non_object_fields_refuse_at_every_level(self):
        paths = [(), ('root_key',), ('identity',), ('array_bindings',),
                 ('array_bindings', 'root_key')]
        for path in paths:
            for mutation in ('extra', 'missing', 'list'):
                with self.subTest(path=path, mutation=mutation):
                    row = sample().to_wire()
                    target = row
                    for key in path:
                        target = target[key]
                    if mutation == 'extra':
                        target['foreign'] = 1
                    elif mutation == 'missing':
                        del target[next(iter(target))]
                    elif path:
                        assign(row, path, [])
                    else:
                        row = []
                    with self.assertRaises(C.ContractError):
                        C.SegmentRef.from_json(canonical(row))

    def test_duplicate_keys_refuse_top_level_and_nested(self):
        raw = sample().to_json()
        for token, value in ((b'"schema":', b'"schema":"duplicate",'),
                             (b'"canonical_bytes":', b'"canonical_bytes":1,'),
                             (b'"workflow_id":', b'"workflow_id":"duplicate",')):
            hostile = raw.replace(token, value + token, 1)
            with self.subTest(token=token), self.assertRaisesRegex(C.ContractError, 'duplicate'):
                C.SegmentRef.from_json(hostile)

    def test_true_top_level_duplicate_keys_refuse(self):
        # L9: the replacements above hit nested objects first (sorted keys);
        # these insert a second copy of a genuine top-level key.
        raw = sample().to_json()
        self.assertTrue(raw.startswith(b'{'))
        for key in ('schema', 'logical_bytes', 'merkle_root', 'identity'):
            value = canonical(sample().to_wire()[key])
            hostile = b'{"' + key.encode('ascii') + b'":' + value + b',' + raw[1:]
            with self.subTest(key=key), self.assertRaisesRegex(C.ContractError, 'duplicate'):
                C.SegmentRef.from_json(hostile)

    def test_all_uint_fields_reject_wrong_types_and_out_of_range(self):
        paths = [('root_key', 'interval'), ('identity', 'canonical_bytes'),
                 ('logical_bytes',), ('array_bindings', 'count'),
                 ('array_bindings', 'root_key', 'interval')]
        for path in paths:
            for bad in (True, False, -1, 1 << 64, 1.0, '1', None):
                row = sample().to_wire()
                assign(row, path, bad)
                with self.subTest(path=path, bad=bad), self.assertRaises(C.ContractError):
                    C.SegmentRef.from_json(canonical(row))

    def test_uint64_endpoints_are_not_arbitrary_smaller_integer_caps(self):
        row = sample().to_wire()
        for value in (0, (1 << 64) - 1):
            for path in [('root_key', 'interval'), ('identity', 'canonical_bytes'),
                         ('logical_bytes',), ('array_bindings', 'count'),
                         ('array_bindings', 'root_key', 'interval')]:
                assign(row, path, value)
            self.assertEqual(C.SegmentRef.from_json(canonical(row)).to_wire(), row)

    def test_all_hash_fields_require_exact_lowercase_hex(self):
        paths = [('root_key', 'workflow_id'), ('root_key', 'snapshot_key'),
                 ('identity', 'sha256'), ('array_bindings', 'digest'),
                 ('array_bindings', 'root_key', 'workflow_id'),
                 ('array_bindings', 'root_key', 'snapshot_key'), ('merkle_root',)]
        for path in paths:
            for bad in ('A' * 64, 'g' * 64, 'a' * 63, 'a' * 65, 'a' * 63 + '\n', 0, None):
                row = sample().to_wire()
                assign(row, path, bad)
                with self.subTest(path=path, bad=bad), self.assertRaises(C.ContractError):
                    C.SegmentRef.from_json(canonical(row))

    def test_version_profiles_are_exact(self):
        for path in [('schema',), ('array_bindings', 'schema')]:
            for bad in ('atlas.segment-ref.v2', '', True, None):
                row = sample().to_wire()
                assign(row, path, bad)
                with self.subTest(path=path, bad=bad), self.assertRaises(C.ContractError):
                    C.SegmentRef.from_json(canonical(row))

    def test_logical_schema_is_caller_qualified_and_utf8_byte_bounded(self):
        ref = sample()
        valid = replace(ref, identity=C.LogicalIdentity('\u00e9' * 128, 'c' * 64, 3))
        raw = valid.to_json()
        self.assertIn(b'\\u00e9', raw)
        self.assertEqual(C.SegmentRef.from_json(raw), valid)
        for bad in ('', 'x' * 257, '\u00e9' * 129, '\ud800', True, None):
            with self.subTest(bad=repr(bad)), self.assertRaises(C.ContractError):
                C.LogicalIdentity(bad, 'c' * 64, 3)

    def test_binding_owner_must_be_same_workflow_and_not_future(self):
        ref = sample()
        for interval in (0, ref.root_key.interval):
            binding = replace(ref.array_bindings, root_key=replace(ref.root_key, interval=interval))
            self.assertEqual(replace(ref, array_bindings=binding).array_bindings, binding)
        for locator in (replace(ref.root_key, interval=4),
                        replace(ref.root_key, workflow_id='0' * 64)):
            with self.subTest(locator=locator), self.assertRaises(C.ContractError):
                replace(ref, array_bindings=replace(ref.array_bindings, root_key=locator))

    def test_direct_construction_requires_typed_nested_immutable_values(self):
        ref = sample()
        for field, bad in [('root_key', ref.root_key.to_wire()),
                           ('identity', ref.identity.to_wire()),
                           ('array_bindings', ref.array_bindings.to_wire())]:
            with self.subTest(field=field), self.assertRaises(C.ContractError):
                replace(ref, **{field: bad})
        with self.assertRaises(C.ContractError):
            replace(ref.array_bindings, root_key=ref.root_key.to_wire())

    def test_noncanonical_json_spelling_refuses(self):
        ref = sample()
        raw = ref.to_json()
        candidates = [b' ' + raw, raw + b'\n', json.dumps(ref.to_wire()).encode(),
                      raw.replace(b'"interval":1', b'"interval":1.0', 1),
                      raw.replace(b'"interval":1', b'"interval":1e0', 1),
                      raw.replace(b'"interval":1', b'"interval":-0', 1),
                      raw.replace(b'caller.graph.v7', b'caller.\\u0067raph.v7')]
        for candidate in candidates:
            with self.subTest(candidate=candidate[:80]), self.assertRaises(C.ContractError):
                C.SegmentRef.from_json(candidate)

    def test_invalid_encoding_nonfinite_malformed_and_deep_json_refuse(self):
        candidates = [b'\xff', b'\xef\xbb\xbf{}', b'{} trailing', b'{',
                      b'[' * 1100 + b']' * 1100,
                      sample().to_json().replace(b'"logical_bytes":629145600',
                                                b'"logical_bytes":NaN'),
                      sample().to_json().replace(b'"logical_bytes":629145600',
                                                b'"logical_bytes":Infinity')]
        for candidate in candidates:
            with self.subTest(candidate=candidate[:80]), self.assertRaises(C.ContractError):
                C.SegmentRef.from_json(candidate)

    def test_wire_limit_checked_before_json_parse(self):
        with patch.object(C.json, 'loads', side_effect=AssertionError('oversized input parsed')):
            for raw in (b'x' * 4097, 'x' * 4097, '\u00e9' * 2049):
                with self.subTest(size=len(raw)), self.assertRaisesRegex(C.ContractError, '4096'):
                    C.SegmentRef.from_json(raw)
        # Exactly 4096 bytes reach syntax validation; 4097 never reaches parsing.
        with patch.object(C.json, 'loads', side_effect=ValueError('fixture')) as parser:
            with self.assertRaisesRegex(C.ContractError, 'invalid SegmentRef JSON'):
                C.SegmentRef.from_json(b'x' * 4096)
            parser.assert_called_once()
        for bad in (bytearray(sample().to_json()), None, {}):
            with self.assertRaises(C.ContractError):
                C.SegmentRef.from_json(bad)

    def test_wire_conversion_does_not_retain_caller_mapping(self):
        row = sample().to_wire()
        before = deepcopy(row)
        result = C.SegmentRef.from_wire(row)
        row['identity']['sha256'] = '0' * 64
        row['array_bindings']['count'] = 0
        self.assertEqual(result.to_wire(), before)


class SegmentBudgetTests(unittest.TestCase):
    def test_complete_maximum_put_and_empty_put_tallies(self):
        C.validate_segment_budget(logical_bytes=128 * 1024 * 1024, chunk_references=2048,
                                  manifest_bytes=256 * 1024, metadata_bytes=64 * 1024)
        C.validate_segment_budget(logical_bytes=0, chunk_references=0,
                                  manifest_bytes=100, metadata_bytes=0)

    def test_each_budget_refuses_independently(self):
        base = dict(logical_bytes=1, chunk_references=1, manifest_bytes=100, metadata_bytes=1)
        cases = [('logical_bytes', 128 * 1024 * 1024 + 1),
                 ('chunk_references', 2049), ('manifest_bytes', 256 * 1024 + 1),
                 ('metadata_bytes', 64 * 1024 + 1)]
        for field, bad in cases:
            row = dict(base, **{field: bad})
            with self.subTest(field=field), self.assertRaisesRegex(C.ContractError, field):
                C.validate_segment_budget(**row)

    def test_fragmentation_and_reference_mentions_still_count(self):
        # A tiny byte total cannot waive the reference-count or manifest bounds.
        with self.assertRaisesRegex(C.ContractError, 'chunk_references'):
            C.validate_segment_budget(logical_bytes=2049, chunk_references=2049,
                                      manifest_bytes=200000, metadata_bytes=10)
        with self.assertRaisesRegex(C.ContractError, 'manifest_bytes'):
            C.validate_segment_budget(logical_bytes=1, chunk_references=1,
                                      manifest_bytes=262145, metadata_bytes=10)

    def test_inconsistent_counts_refuse(self):
        with self.assertRaisesRegex(C.ContractError, 'cover'):
            C.validate_segment_budget(logical_bytes=65537, chunk_references=1,
                                      manifest_bytes=100, metadata_bytes=0)
        with self.assertRaisesRegex(C.ContractError, 'metadata'):
            C.validate_segment_budget(logical_bytes=0, chunk_references=0,
                                      manifest_bytes=10, metadata_bytes=11)

    def test_bad_tally_values_refuse(self):
        base = dict(logical_bytes=1, chunk_references=1, manifest_bytes=100, metadata_bytes=1)
        for field in base:
            for bad in (True, -1, 1.0, None, 1 << 64):
                with self.subTest(field=field, bad=bad), self.assertRaises(C.ContractError):
                    C.validate_segment_budget(**dict(base, **{field: bad}))


if __name__ == '__main__':
    unittest.main()
