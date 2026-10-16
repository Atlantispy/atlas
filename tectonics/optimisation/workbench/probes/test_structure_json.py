"""Synthetic tests only: no SQLite/store access or simulation."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import structure_json as S


class StructureJSONTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sj-')
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'input.json'

    def scan(self, raw, **options):
        if isinstance(raw, str):
            raw = raw.encode('utf-8')
        self.path.write_bytes(raw)
        return S.scan(self.path, **options)

    def refused(self, raw, message=None):
        with self.assertRaisesRegex(S.StructureJSONError, message or '.'):
            self.scan(raw)

    def test_exact_unicode_escaped_spans_counts_and_byte_partition(self):
        value = {'name': 'λ雪😀', 'quoted': 'a"b\\c\n',
                 'items': [{'n': -123456789012345678901234567890, 'q': ['-0xf', '0x10']},
                           {'n': 0, 'q': ['0x0', '0x1']}],
                 'other': [True, None, False, 1.25, 3e-4], 'empty': {}}
        raw = (' \n' + json.dumps(value, ensure_ascii=False, indent=2) + '\r\n').encode('utf-8')
        report = self.scan(raw, select=lambda path, kind: True)
        self.assertEqual(report['filebytes'], len(raw))
        self.assertEqual(report['root_kind'], 'object')
        self.assertEqual(report['root_items'], len(value))
        self.assertEqual(sum(report['lexical_bytes'].values()), len(raw))
        self.assertEqual(report['max_integer_decimal_digits'], 30)
        self.assertEqual(report['counts'], {'objects': 4, 'arrays': 4, 'scalars': 13,
                                          'strings': 6, 'integers': 2, 'numbers': 2,
                                          'booleans': 2, 'nulls': 1, 'keys': 9})
        for row in report['selected']:
            expected = value
            for part in row['path']:
                expected = expected[part]
            self.assertEqual(json.loads(raw[row['start']:row['end']]), expected)
            self.assertEqual(row['bytes'], row['end'] - row['start'])
            self.assertEqual(row['items'], len(expected) if isinstance(expected, (dict, list)) else None)
        self.assertEqual([row['path'] for row in report['fields']], [[key] for key in value])
        for row in report['fields']:
            self.assertEqual(json.loads(raw[row['start']:row['end']]), value[row['path'][0]])
        self.assertEqual(sum(row['bytes'] for row in report['fields'])
                         + report['root_overhead_bytes'], len(raw))

    def test_nested_aggregate_excludes_indices_and_does_not_invent_span(self):
        value = {'rows': [{'id': 1, 'metadata': {'deep': 2}},
                          {'id': 3, 'metadata': {'deep': 4}}]}
        report = self.scan(json.dumps(value), select=lambda path, kind: len(path) == 2)
        rows = {tuple(row['path']): row for row in report['nested_fields']}
        self.assertEqual(set(rows), {('rows',), ('rows', 'id'), ('rows', 'metadata')})
        self.assertEqual(rows[('rows', 'id')]['occurrences'], 2)
        self.assertEqual(rows[('rows', 'id')]['bytes'], 2)
        self.assertNotIn('start', rows[('rows', 'id')])
        self.assertEqual(rows[('rows', 'id')]['kind_counts'], {'integer': 2})
        self.assertEqual([row['path'] for row in report['selected']], [['rows', 0], ['rows', 1]])
        self.assertEqual(report['fields'][0]['counts']['objects'], 4)
        self.assertEqual(report['fields'][0]['items'], 2)

    def test_content_id_map_is_one_aggregate_with_exact_selected_keys(self):
        value = {'material_quadrature_m3': {format(i, '064x'): i for i in range(4097)}}
        raw = json.dumps(value, separators=(',', ':')).encode()
        report = self.scan(raw, select=lambda path, kind: len(path) == 2 and path[1] == '0' * 64)
        rows = {tuple(row['path']): row for row in report['nested_fields']}
        self.assertEqual(set(rows), {('material_quadrature_m3',), ('material_quadrature_m3', None)})
        group = rows[('material_quadrature_m3', None)]
        self.assertEqual(group['occurrences'], 4097)
        self.assertEqual(group['bytes'], sum(len(str(i)) for i in range(4097)))
        self.assertTrue(group['content_id_wildcard'])
        self.assertNotIn('start', group)
        self.assertEqual(report['selected'][0]['path'], ['material_quadrature_m3', '0' * 64])
        self.assertEqual(sum(report['lexical_bytes'].values()), len(raw))

    def test_rational_candidate_widths_and_per_field(self):
        value = {'q': [['-0xf', '0x10'], ['0x0', '0x1'], ['0x2', '0x4']],
                 'not_q': [['-0x0', '0x1'], ['0x01', '0x1'], ['0xA', '0x1'],
                           ['0x1', '-0x1'], ['0x1', '0x0'], ['0x1'],
                           ['0x1', '0x2', '0x3'], ['0x1', 2]]}
        report = self.scan(json.dumps(value, separators=(',', ':')))
        stats = report['rational_strings']
        self.assertEqual(stats['count'], 3)  # Includes unreduced lexical candidate.
        self.assertEqual(stats['pair_count'], 3)
        self.assertEqual(stats['string_count'], 6)
        self.assertEqual(stats['max_numerator_chars'], 4)
        self.assertEqual(stats['max_denominator_chars'], 4)
        self.assertEqual(stats['max_encoded_bytes'], len(b'["-0xf","0x10"]'))
        self.assertEqual(stats['min_numerator_bits'], 0)
        self.assertEqual(stats['max_numerator_bits'], 4)
        self.assertEqual(stats['min_denominator_bits'], 1)
        self.assertEqual(stats['max_denominator_bits'], 5)
        self.assertEqual(report['fields'][0]['rational_strings'], stats)
        self.assertEqual(report['fields'][1]['rational_strings']['count'], 0)

    def test_large_exact_integer_never_passes_through_integer_conversion(self):
        report = self.scan(b'[-' + b'9' * 10000 + b', 1e99999]')
        self.assertEqual(report['max_integer_decimal_digits'], 10000)
        self.assertEqual(report['counts']['integers'], 1)
        self.assertEqual(report['counts']['numbers'], 1)

    def test_carry_handles_large_string_utf8_and_escape_boundaries(self):
        text = 'a' * (S.CHUNK_BYTES * 2 + 19) + 'λ雪😀' + '\\"\n'
        raw = json.dumps({'x': text}, ensure_ascii=False).encode('utf-8')
        report = self.scan(raw, select=lambda path, kind: path == ('x',))
        row = report['selected'][0]
        self.assertEqual(json.loads(raw[row['start']:row['end']]), text)
        with patch.object(S, 'CHUNK_BYTES', 7):
            raw = b'{"abcdef":"abc\\u1234\\\"\\\\\\n' + '😀'.encode() + b'"}'
            report = self.scan(raw, select=lambda path, kind: bool(path))
            row = report['selected'][0]
            self.assertEqual(json.loads(raw[row['start']:row['end']]), json.loads(raw)['abcdef'])

    def test_tokens_and_whitespace_cross_each_small_boundary(self):
        samples = [b'  null  ', b'true', b'false', b'-12345', b'1.25e-123',
                   b'[{},[],"x",null, true,false,-123,0.5e+2]',
                   b'{"a":1,"b":"\\u1234\\\\\\\""}']
        for chunk in range(1, 12):
            with patch.object(S, 'CHUNK_BYTES', chunk):
                for raw in samples:
                    with self.subTest(chunk=chunk, raw=raw):
                        report = self.scan(raw, select=lambda path, kind: not path)
                        row = report['selected'][0]
                        self.assertEqual(json.loads(raw[row['start']:row['end']]), json.loads(raw))

    def test_invalid_grammar_strings_constants_and_duplicate_keys(self):
        malformed = [b'', b' ', b'{}{}', b'1 2', b'[1,]', b'{"a":1,}',
                     b'[1 2]', b'{"a" 1}', b'{1:2}', b'{"a":}', b'{', b'[',
                     b']', b':', b',', b'NaN', b'Infinity', b'-Infinity', b'01',
                     b'-01', b'+1', b'.5', b'1.', b'1e', b'trueX', b'nul',
                     b'"bad\\x00"', b'"bad\\u01"', b'"bad\\uXYZW"',
                     b'"bad\n"', b'"unterminated', b'"\\', b'"\xff"',
                     b'\xef\xbb\xbf{}', b'{"a":1,"a":2}',
                     b'{"a":1,"\\u0061":2}', b'{"a":{"b":1,"b":2}}']
        for raw in malformed:
            with self.subTest(raw=raw):
                self.refused(raw)

    def test_same_keys_in_independent_objects_and_surrogate_escapes(self):
        report = self.scan(b'[{"a":1},{"a":2},{"\\ud800":"\\udfff"}]')
        self.assertEqual(report['counts']['objects'], 3)
        self.assertEqual(report['fields'], [])
        self.assertEqual(report['nested_fields'][0]['path'], ['a'])
        self.assertEqual(report['nested_fields'][0]['occurrences'], 2)

    def test_token_and_key_size_limits(self):
        with patch.object(S, 'MAX_TOKEN_BYTES', 12):
            self.assertEqual(self.scan(b'"' + b'x' * 10 + b'"')['max_token_bytes'], 12)
            self.refused(b'"' + b'x' * 11 + b'"', 'token byte bound')
            self.refused(b'9' * 13, 'token byte bound')
        with patch.object(S, 'MAX_KEY_BYTES', 3):
            self.scan('{"雪":1}')
            self.refused('{"雪a":1}', 'key byte bound')

    def test_depth_keycount_activekeys_aggregate_and_path_limits(self):
        with patch.object(S, 'MAX_DEPTH', 3):
            self.scan('[[[0]]]')
            self.refused('[[[[0]]]]', 'depth bound')
        with patch.object(S, 'MAX_KEYS_PER_OBJECT', 2):
            self.scan('{"a":1,"b":2}')
            self.refused('{"a":1,"b":2,"c":3}', 'key count bound')
        with patch.object(S, 'MAX_ACTIVE_KEY_BYTES', 3):
            self.scan('[{"abc":0},{"abc":1}]')
            self.refused('{"abc":{"d":0}}', 'active object key')
        with patch.object(S, 'MAX_AGGREGATE_PATHS', 2):
            self.refused('{"a":1,"b":2,"c":3}', 'aggregate path bound')
        with patch.object(S, 'MAX_REPORT_PATH_BYTES', 3):
            self.refused('{"aa":1,"bb":2}', 'report path byte bound')

    def test_selected_bound_counts_inflight_parents(self):
        with patch.object(S, 'MAX_SELECTED', 2):
            with self.assertRaisesRegex(S.StructureJSONError, 'selected span bound'):
                self.scan('[[0]]', select=lambda path, kind: True)
        with patch.object(S, 'MAX_SELECTED', 3):
            report = self.scan('[[0]]', select=lambda path, kind: True)
            self.assertEqual([row['path'] for row in report['selected']], [[], [0], [0, 0]])

    def test_large_owner_edge_object_and_peak_key_counts(self):
        owners = {'owner:vertex:m03-p%05d>vertex:m03-p%05d' % (i, i + 1): i
                  for i in range(4097)}
        # Third object-key level avoids conflating the separate aggregate-path cap
        # with the large native owner-edge table's per-container key capacity.
        report = self.scan(json.dumps({'finite_proposal': {'graph': {'owners': owners}}}))
        self.assertEqual(report['max_object_keys'], 4097)
        self.assertEqual(report['max_active_keys'], 4100)
        self.assertEqual(report['counts']['keys'], 4100)
        self.assertEqual(report['limits']['keys_per_object'], 131072)
        self.assertEqual(report['limits']['active_keys'], 131072)
        duplicate = '{"root":{"nested":{"owners":{"same":1,"same":2}}}}'
        self.refused(duplicate, 'duplicate object key')

    def test_total_active_key_bound_release_and_diagnostic_path(self):
        with patch.object(S, 'MAX_ACTIVE_KEYS', 3):
            report = self.scan('[{"a":1,"b":2,"c":3},{"a":4,"b":5,"c":6}]')
            self.assertEqual(report['max_object_keys'], 3)
            self.assertEqual(report['max_active_keys'], 3)
            with self.assertRaisesRegex(S.StructureJSONError, 'total active object key count bound') as error:
                self.scan('{"outer":{"first":1,"second":{"third":2}}}')
            self.assertIn('path ["outer","second"]', str(error.exception))
        with patch.object(S, 'MAX_KEYS_PER_OBJECT', 1):
            with self.assertRaisesRegex(S.StructureJSONError, 'object key count bound') as error:
                self.scan('{"outer":{"first":1,"second":2}}')
            self.assertIn('path ["outer"]', str(error.exception))

    def test_file_bound_and_changed_input(self):
        with patch.object(S, 'MAX_SOURCE_BYTES', 12):
            self.refused(b'[' + b'0,' * 6 + b'0]', 'source byte bound')
        changed = False

        def select(path, kind):
            nonlocal changed
            if not changed:
                stamp = self.path.stat()
                os.utime(self.path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1000000000))
                changed = True
            return False

        with self.assertRaisesRegex(S.StructureJSONError, 'source changed'):
            self.scan('[1,2]', select=select)

    def test_cancellation_is_preserved_at_chunk_boundary(self):
        class Cancelled(Exception):
            pass

        calls = 0

        def check():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise Cancelled('original cancellation')

        with self.assertRaisesRegex(Cancelled, 'original cancellation'):
            self.scan(b'"' + b'x' * (S.CHUNK_BYTES * 2) + b'"', check=check)
        self.assertEqual(calls, 3)

    def test_selection_exception_is_not_wrapped(self):
        def select(path, kind):
            raise LookupError('original selector error')

        with self.assertRaisesRegex(LookupError, 'original selector error'):
            self.scan('[]', select=select)


if __name__ == '__main__':
    unittest.main()
