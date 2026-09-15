"""Focused storage-only history checks; no native model imports or runs."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from fractions import Fraction as F
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import history as h


def row(number=1):
    repeated = {'precise_fraction': str(F(7, 2**64)),
                'explanation': 'Exact rational quantities retain their original physical meaning. ' * 8,
                'nested': [None, True, False, 0, -0.0, 1.25, '\u2603', {'a': [1, 2, 3]}]}
    return {'operation_id': f'accepted-{number}', 'start_year': str(number-1),
        'duration_years': F(1), 'parent_state_sha256': 'a'*64, 'state_sha256': 'b'*64,
        'diagnostics': {'cumulative_numeric_l1_units': number, 'extra': [number, 'unchanged']},
        'substeps': [{'hillslope': {'duration_years': F(1, 2),
            'total_bulk_allocation_error_m3': F(1, 2**80), 'full_receipt': deepcopy(repeated)},
            'surface_runoff_m3': F(10), 'surface_water_exported_m3': F(10),
            'numeric_compaction': {'total_l1_units': 1, 'complete_detail': deepcopy(repeated)},
            'channel': {'proposal': deepcopy(repeated), 'applied': deepcopy(repeated)},
            'literal_reserved_keys': {'$history_ref': 8, '$history_literal': [['x', 1]]}}
            for _ in range(2)], 'other_original_evidence': deepcopy(repeated)}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='native-history-test-')
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_direct_writer_preserves_aliases_and_exact_fraction_tuple_bytes(self):
        shared = {'fractions': (F(7, 2**64), F(-3, 2), F(0)),
                  'leaves': ['\u2603', '\\escaped\n', -0.0, None, True, 12]}
        original = {'proposal': shared, 'applied': dict(shared, changed='only this field'),
                    'another_shared_view': shared, 'tuple': (shared, shared)}
        expected = json.dumps(h._plain(original), sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        with patch.object(h, '_plain', side_effect=AssertionError('expanded intermediate tree built')):
            self.assertEqual(h._encoded(original), expected)
        self.assertIs(original['proposal'], original['another_shared_view'])
        self.assertIs(original['proposal']['leaves'], original['applied']['leaves'])
        self.assertIs(original['tuple'][0], original['tuple'][1])
        self.assertIs(type(original['proposal']['fractions'][0]), F)
        self.assertIs(type(original['tuple']), tuple)

    def test_nonstring_keys_collisions_and_subclasses_keep_original_semantics(self):
        class NamedString(str):
            def __str__(self):
                return 'normalised-subclass-key'
        class DictSubclass(dict):
            pass
        cases = [{1: 'first', '1': 'last', None: F(1, 2), False: (F(3, 4),)},
                 {'outer': {F(1, 3): ['rational key'], ('tuple', 2): 4}},
                 {NamedString('original'): 'value'},
                 {'subclass': DictSubclass({'nested': 2})}]
        for original in cases:
            expected = json.dumps(h._plain(original), sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
            with self.subTest(original=original):
                self.assertFalse(h._direct_json(original))
                self.assertEqual(h._encoded(original), expected)
        self.assertEqual(json.loads(h._encoded(cases[0]))['1'], 'last')
        self.assertEqual(json.loads(h._encoded(cases[2])), {'normalised-subclass-key': 'value'})
        # Previously unsupported contents of an unnormalised dict subclass must
        # not gain new silent conversion semantics through the direct default.
        with self.assertRaises(TypeError):
            h._encoded({'subclass': DictSubclass({'fraction': F(1, 2)})})

    def test_append_direct_summary_needs_no_full_parse_and_fallback_matches_raw(self):
        original = row()
        shared = original['substeps'][0]['channel']['proposal']
        original['substeps'][0]['channel']['applied'] = shared
        expected_raw = h._encoded(original)
        expected_summary = json.loads(h._summary(json.loads(expected_raw)))
        direct = h.History(self.root/'direct')
        with patch.object(h, '_parse', side_effect=AssertionError('direct append expanded the entire row')):
            direct.append(original)
        self.assertEqual(direct[0], expected_summary)
        self.assertEqual(list(direct.iter_raw()), [expected_raw])
        self.assertIs(original['substeps'][0]['channel']['applied'], shared)
        self.assertEqual(h.History.from_refs(direct.root, direct.refs)[0], expected_summary)

        original['diagnostics']['mixed_key_example'] = {1: 'first', '1': 'normalised winner', None: F(2, 3)}
        expected_raw = h._encoded(original)
        expected_summary = json.loads(h._summary(json.loads(expected_raw)))
        fallback = h.History(self.root/'fallback')
        with patch.object(h, '_parse', wraps=h._parse) as parse:
            fallback.append(original)
            parse.assert_called_once_with(expected_raw)
        self.assertEqual(fallback[0], expected_summary)
        self.assertEqual(fallback[0]['diagnostics']['mixed_key_example']['1'], 'normalised winner')
        self.assertEqual(h.History.from_refs(fallback.root, fallback.refs)[0], expected_summary)

    def test_exact_canonical_roundtrip_and_required_summary(self):
        original = row()
        raw = h._encoded(original)
        history = h.History.from_rows(self.root, [original])
        self.assertEqual(list(history.iter_raw()), [raw])
        self.assertEqual(history.materialize(), [json.loads(raw)])
        self.assertEqual(history[0], json.loads(h._summary(json.loads(raw))))
        self.assertNotIn('channel', history[0]['substeps'][0])
        self.assertEqual(history.refs[0]['raw_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(history.refs[0]['storage_schema'], h.RAW_SCHEMA)
        restored = h.History.from_refs(self.root, history.refs)
        self.assertEqual(list(restored.iter_raw()), [raw])
        self.assertEqual(restored.refs, history.refs)

    def test_deepcopy_append_and_decoded_values_are_independent(self):
        history = h.History.from_rows(self.root, [row()])
        following = deepcopy(history)
        self.assertIsNot(following, history)
        self.assertIs(following._entries, history._entries)
        with self.assertRaises(FrozenInstanceError):
            history._entries[0].sequence = 2
        following.append(row(2))
        self.assertEqual((len(history), len(following)), (1, 2))
        summary = history[0]
        summary['diagnostics']['extra'].append('caller edit')
        refs = history.refs
        refs[0]['summary']['diagnostics']['extra'].append('caller edit')
        materialized = history.materialize()
        materialized[0]['substeps'][0]['channel'].clear()
        self.assertEqual(history[0]['diagnostics']['extra'], [1, 'unchanged'])
        self.assertTrue(history.materialize()[0]['substeps'][0]['channel'])
        self.assertEqual(history[:], list(history))
        self.assertEqual(history[-1], list(history)[0])

    def test_repeat_and_append_only_publish_new_closed_row(self):
        first = h.History.from_rows(self.root, [row()])
        first_path = self.root / first.refs[0]['path']
        original_stat = first_path.stat()
        original_bytes = first_path.read_bytes()
        second = h.History.from_rows(self.root, [row()])
        second.append(row(2))
        self.assertEqual(first_path.stat().st_mtime_ns, original_stat.st_mtime_ns)
        self.assertEqual(first_path.read_bytes(), original_bytes)
        self.assertEqual(len(list((self.root/'history').glob('*.zst'))), 2)
        self.assertFalse(list((self.root/'history').glob('*.tmp')))

    def test_corrupt_existing_row_never_overwritten_or_container_appended(self):
        original = h.History.from_rows(self.root, [row()])
        path = self.root / original.refs[0]['path']
        damaged = path.read_bytes()[:-1] + b'x'
        path.write_bytes(damaged)
        following = h.History(self.root)
        with self.assertRaises(ValueError):
            following.append(row())
        self.assertEqual(len(following), 0)
        self.assertEqual(path.read_bytes(), damaged)
        with self.assertRaises(ValueError):
            list(original.iter_raw())

    def test_tamper_is_checked_on_each_raw_iteration(self):
        history = h.History.from_rows(self.root, [row()])
        self.assertEqual(len(list(history.iter_raw())), 1)
        path = self.root / history.refs[0]['path']
        raw = path.read_bytes()
        path.write_bytes(bytes([raw[0] ^ 1])+raw[1:])
        with self.assertRaisesRegex(ValueError, 'hash differs'):
            list(history.iter_raw())
        with self.assertRaises(ValueError):
            h.History.from_refs(self.root, history.refs)

    def test_reference_order_paths_sizes_identity_and_summary_rejected(self):
        history = h.History.from_rows(self.root, [row(), row(2)])
        changes = [lambda refs: refs.reverse(),
            lambda refs: refs[0].update(sequence=True),
            lambda refs: refs[0].update(path='../outside.json.zst'),
            lambda refs: refs[0].update(path=str(self.root/'outside.json.zst')),
            lambda refs: refs[0].update(path=refs[0]['path']+':alternate'),
            lambda refs: refs[0].update(raw_size_bytes=h.MAX_RAW_BYTES+1),
            lambda refs: refs[0].update(storage_size_bytes=True),
            lambda refs: refs[0].update(frame_size_bytes=h.compression.MAX_FRAME_BYTES+1),
            lambda refs: refs[0]['summary'].update(operation_id='invented'),
            lambda refs: refs[0]['codec'].update(version='unbound'),
            lambda refs: refs[0].update(extra='ambiguous')]
        for change in changes:
            refs = history.refs
            change(refs)
            with self.subTest(change=changes.index(change)), self.assertRaises(ValueError):
                h.History.from_refs(self.root, refs)

    def test_explicit_bounds_empty_rows_and_bad_json(self):
        history = h.History.from_rows(self.root, [])
        self.assertEqual((len(history), list(history), list(history.iter_raw()), history.refs), (0, [], [], []))
        with self.assertRaises(ValueError):
            history.append({'not': 'an accepted row'})
        with patch.object(h, 'MAX_ROWS', 1):
            history.append(row())
            with self.assertRaises(ValueError):
                history.append(row(2))
            with self.assertRaises(ValueError):
                h.History.from_refs(self.root, history.refs*2)
        with self.assertRaises(ValueError):
            h._encoded(row(), limit=32)
        for raw in (b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":Infinity}', b'\xff'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                h._parse(raw)

    def test_generic_nested_canonical_json_has_no_reserved_storage_keys(self):
        repeated = {'string': '\u2603' * 128, 'items': [{'x': 7, 'y': -0.0}] * 32,
            '$history_ref': {'$history_literal': [True, None, 'not a reference']}}
        record = {'b': deepcopy(repeated), 'a': deepcopy(repeated),
            'not_equal': dict(repeated, string='different' * 100)}
        raw = h._encoded(record)
        self.assertEqual(h._encoded(h._parse(raw)), raw)
        full = row()
        full['extra_generic_evidence'] = record
        history = h.History.from_rows(self.root, [full])
        self.assertEqual(history.materialize()[0]['extra_generic_evidence'], record)
        frame = (self.root/history.refs[0]['path']).read_bytes()
        self.assertEqual(h.compression.decode(frame, history.refs[0]['raw_size_bytes']), h._encoded(full))

    def test_authenticated_fast_raw_does_not_reparse_but_restart_does(self):
        history = h.History.from_rows(self.root, [row()])
        refs = history.refs
        with patch.object(h, '_parse', side_effect=AssertionError('old logical row reparsed')):
            self.assertEqual(list(history.iter_raw()), [h._encoded(row())])
        with patch.object(h, '_parse', wraps=h._parse) as parse:
            h.History.from_refs(self.root, refs)
            self.assertGreaterEqual(parse.call_count, 1)
        for name, replacement in (('_entries', ()), ('_root', self.root.parent), ('_codec_bytes', b'{}')):
            with self.subTest(name=name), self.assertRaises(AttributeError):
                setattr(history, name, replacement)
            with self.assertRaises(AttributeError):
                delattr(history, name)
        self.assertFalse(hasattr(history._entries[0], '__dict__'))

    def test_safe_path_reparse_and_changed_open_file_rejected(self):
        with self.assertRaises(ValueError):
            h.History(self.root/'..'/'outside')
        history = h.History.from_rows(self.root, [row()])
        path = self.root/history.refs[0]['path']
        original = Path.lstat
        def reparse(candidate, *args, **kwargs):
            info = original(candidate, *args, **kwargs)
            if candidate == path:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info
        with patch.object(Path, 'lstat', reparse):
            with self.assertRaisesRegex(ValueError, 'reparse'):
                list(history.iter_raw())
        actual = os.fstat
        def changed(descriptor):
            info = actual(descriptor)
            return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size,
                                   st_mtime_ns=info.st_mtime_ns+1)
        with patch.object(os, 'fstat', changed):
            with self.assertRaisesRegex(ValueError, 'changed during read'):
                list(history.iter_raw())

    def test_executed_source_and_codec_identity_remain_checked(self):
        history = h.History.from_rows(self.root, [row()])
        with patch.object(h, '_R12_EXECUTED_SHA256', '0'*64):
            with self.assertRaises(ValueError):
                history.to_refs()
            with self.assertRaises(ValueError):
                list(history.iter_raw())
        changed = dict(h.compression.identity(), version='changed')
        with patch.object(h.compression, 'identity', return_value=changed):
            with self.assertRaises(ValueError):
                history.append(row(2))
        with patch.object(h.compression, '_digest', return_value='0'*64):
            with self.assertRaises(ValueError):
                list(history.iter_raw())

    def test_fresh_process_reference_roundtrip(self):
        history = h.History.from_rows(self.root, [row(), row(2)])
        refs_path = self.root/'refs.json'
        refs_path.write_bytes(h._encoded(history.refs))
        script = ('import hashlib,json; from pathlib import Path; '
            'from work.native_terrain_r3.history import History; '
            'root=Path('+repr(str(self.root))+'); '
            'h=History.from_refs(root,json.loads((root/"refs.json").read_bytes())); '
            'print(json.dumps([hashlib.sha256(raw).hexdigest() for raw in h.iter_raw()]))')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        result = subprocess.run([sys.executable, '-B', '-c', script], check=True,
            capture_output=True, text=True, timeout=30, cwd=Path(__file__).resolve().parents[2], **options)
        self.assertEqual(json.loads(result.stdout), [ref['raw_sha256'] for ref in history.refs])


if __name__ == '__main__':
    unittest.main(verbosity=2)
