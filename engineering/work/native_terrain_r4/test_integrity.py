"""Focused history-integrity checks; no native numerical model execution."""
from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from work.native_terrain_r3 import history as h
from work.native_terrain_r3 import provenance as oldp
from work.native_terrain_r3.test_history import row
from . import integrity as i


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='native-r4-integrity-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rows = [row(), row(2)]
        self.history = h.History.from_rows(self.root, self.rows)
        self.body = {'state': {'elapsed_years': [2, 1]}, 'history': self.history,
                     'source_status': 'WORKING NON-CANON', 'unchanged_evidence': [None, '\u2603']}

    def test_explicit_version_and_exact_scientific_sha_roundtrip(self):
        original = dict(self.body, history=self.rows)
        expected = oldp.retained.sha(original)
        self.assertEqual(i.scientific_sha(self.body), expected)
        digest = i.commitment(self.body)
        projected = {'schema': i.SCHEMA, 'body': dict(self.body, history=self.history.refs)}
        self.assertEqual(digest, oldp.retained.sha(projected))
        self.assertNotEqual(digest, expected)
        restored = h.History.from_refs(self.root, self.history.refs)
        self.assertEqual(i.commitment(dict(self.body, history=restored)), digest)
        self.assertEqual(i.scientific_sha(dict(self.body, history=restored)), expected)

    def test_hot_commitment_reads_each_frame_without_decompression_or_materialisation(self):
        expected = i.commitment(self.body)
        with patch.object(h.compression, 'decode', side_effect=AssertionError('old row decompressed')):
            with patch.object(h.History, 'materialize', side_effect=AssertionError('history materialised')):
                with patch.object(h, '_read', wraps=h._read) as read:
                    self.assertEqual(i.commitment(self.body), expected)
                    self.assertEqual(read.call_count, len(self.history))

    def test_full_verification_decodes_each_row_without_parsing_it(self):
        # Reference conversion legitimately parses the tiny summary/codec. A
        # full logical-row parse is the work that must remain load-only.
        large = row()
        large['other_original_evidence']['explanation'] = 'X' * (h.MAX_SUMMARY_BYTES + 1)
        history = h.History.from_rows(self.root / 'large', [large])
        original_parse = h._parse
        def bounded_parse(raw):
            if len(raw) > h.MAX_SUMMARY_BYTES:
                raise AssertionError('full logical row parsed')
            return original_parse(raw)
        references = history.refs
        with patch.object(h, '_parse', side_effect=bounded_parse):
            with patch.object(h.History, '_raw', wraps=history._raw) as raw:
                self.assertEqual(i.verify_history(history, full=True), references)
                self.assertEqual(raw.call_count, len(history))
                self.assertTrue(all(call.kwargs == {} for call in raw.call_args_list))

    def test_same_size_and_mtime_corruption_is_rejected_in_every_mode(self):
        entry = self.history.refs[0]
        path = self.root / entry['path']
        before, info = path.read_bytes(), path.stat()
        corrupt = bytearray(before)
        corrupt[-1] ^= 1
        path.write_bytes(corrupt)
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        self.assertEqual(path.stat().st_size, info.st_size)
        self.assertEqual(path.stat().st_mtime_ns, info.st_mtime_ns)
        for action in (lambda: i.commitment(self.body),
                       lambda: i.verify_history(self.history, full=True),
                       lambda: i.scientific_sha(self.body)):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'frame hash differs'):
                action()

    def test_active_fields_order_summaries_and_logical_detail_are_bound(self):
        before = i.commitment(self.body)
        changed = dict(self.body, state={'elapsed_years': [3, 1]})
        self.assertNotEqual(i.commitment(changed), before)
        references = self.history.refs
        references[0]['summary']['diagnostics']['extra'].append('tampered')
        self.assertEqual(i.commitment(self.body), before)
        with self.assertRaisesRegex(ValueError, 'summary differs'):
            h.History.from_refs(self.root, references)
        with self.assertRaisesRegex(ValueError, 'identity/order/path/codec differs'):
            h.History.from_refs(self.root, list(reversed(self.history.refs)))
        changed_rows = deepcopy(self.rows)
        changed_rows[0]['other_original_evidence']['explanation'] += ' Extra evidence.'
        changed_history = h.History.from_rows(self.root / 'changed', changed_rows)
        self.assertEqual(list(changed_history), list(self.history))
        self.assertNotEqual(i.commitment(dict(self.body, history=changed_history)), before)
        independent = deepcopy(self.history)
        independent.append(row(3))
        self.assertNotEqual(i.commitment(dict(self.body, history=independent)), before)
        self.assertEqual(i.commitment(self.body), before)

    def test_full_verification_checks_logical_hash_not_only_valid_compressed_frame(self):
        # Deliberately bypass frozen construction to isolate the full verifier's
        # logical-hash guard; ordinary callers cannot replace these fields.
        bad = deepcopy(self.history)
        forged = replace(bad._entries[0], raw_sha256='0' * 64)
        object.__setattr__(bad, '_entries', (forged, *bad._entries[1:]))
        with self.assertRaisesRegex(ValueError, 'logical history SHA256/size differs'):
            i.verify_history(bad, full=True)

    def test_source_codec_and_invalid_input_checks_are_retained(self):
        for module in (i, h):
            with self.subTest(module=module.__name__):
                with patch.object(module, '_R12_EXECUTED_SHA256', '0' * 64):
                    with self.assertRaises(ValueError):
                        i.commitment(self.body)
        with patch.object(h.compression, '_digest', return_value='0' * 64):
            with self.assertRaises(ValueError):
                i.commitment(self.body)
        with self.assertRaises(ValueError):
            i.commitment(dict(self.body, history=self.rows))
        with self.assertRaises(ValueError):
            i.verify_history(self.history, full=1)

    def test_empty_history_is_explicitly_bound(self):
        history = h.History(self.root / 'empty')
        body = dict(self.body, history=history)
        self.assertEqual(i.verify_history(history, full=True), [])
        self.assertEqual(i.scientific_sha(body), oldp.retained.sha(dict(body, history=[])))
        self.assertNotEqual(i.commitment(body), i.commitment(self.body))


if __name__ == '__main__':
    unittest.main(verbosity=2)
