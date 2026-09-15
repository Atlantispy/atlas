"""Bounded persistence tests with explicit inert records; no soil generation."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from work.generator_upgrade_r13 import storage


def snapshot(spec, rows=(), reason=None):
    rows = deepcopy(list(rows))
    state = {'completed_events': len(rows), 'continuing_state': {'test': len(rows)},
             'accepted_events': rows}
    cp = {'state': state, 'state_sha256': storage.p.sha(state),
          'recipe_sha256': storage.p.sha(spec), 'source_sha256': 'a'*64}
    return {'scientific': {'events': rows, 'checkpoint': cp, 'completed_events': len(rows),
                           'status': 'STOPPED', 'reason': reason},
            'execution': {'test_only': True, 'complete': False}}


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='r13-s-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'r'
        self.spec = {'source_status': 'SYNTHETIC TEST', 'explicit_inert_fixture': True}

    def test_legacy_save_load_and_exclusive_output_unchanged(self):
        result = snapshot(self.spec, [{'event': 0}])
        self.assertEqual(storage.save(self.root, self.spec, result), self.root)
        self.assertTrue((self.root / 'e0000.json').is_file())
        self.assertFalse((self.root / 'latest.json').exists())
        self.assertEqual(storage.load(self.root), {'recipe': self.spec, **result})
        with self.assertRaisesRegex(ValueError, 'existing outputs preserved'):
            storage.Journal(self.root, self.spec)

    def test_incremental_empty_then_append_without_old_payload_reads_or_writes(self):
        journal = storage.Journal(self.root, self.spec)
        initial = snapshot(self.spec)
        journal.commit(initial)
        self.assertEqual(storage.load(self.root), {'recipe': self.spec, **initial})
        one = snapshot(self.spec, [{'event': 0, 'payload': 'first'}])
        journal.commit(one)
        ref = deepcopy(journal._refs[0])
        old = (self.root / ref['file']).read_bytes()
        stamp = (self.root / ref['file']).stat().st_mtime_ns
        reads = []
        checked = storage.p.checked
        def tracked(path, expected=None):
            reads.append(Path(path).name)
            return checked(path, expected)
        two = snapshot(self.spec, [{'event': 0, 'payload': 'first'}, {'event': 1}])
        with patch.object(storage.p, 'checked', side_effect=tracked):
            journal.commit(two)
        self.assertNotIn(ref['file'], reads)
        self.assertEqual((self.root / ref['file']).read_bytes(), old)
        self.assertEqual((self.root / ref['file']).stat().st_mtime_ns, stamp)
        self.assertEqual(storage.load(self.root), {'recipe': self.spec, **two})

    def test_oversized_event_and_failure_chunks_reconstruct_exactly(self):
        result = snapshot(self.spec, [{'event': 0, 'payload': '雪\\"'*9000}],
                          {'failure': {'accepted_steps': [{'diagnostic': 'x'*80, 'i': i} for i in range(400)]}})
        before = deepcopy(result)
        with patch.object(storage.p.shared, 'LIMIT', 1024):
            journal = storage.Journal(self.root, self.spec)
            journal.commit(result)
            self.assertEqual(storage.load(self.root), {'recipe': self.spec, **result})
            self.assertTrue(all(path.stat().st_size <= 1024 for path in self.root.iterdir()))
            self.assertIn('tree', journal._refs[0])
        self.assertEqual(result, before)

    def test_oversized_legacy_save_routes_to_bounded_journal(self):
        result = snapshot(self.spec, [{'event': 0, 'payload': 'x'*8000}])
        with patch.object(storage.p.shared, 'LIMIT', 1024):
            storage.save(self.root, self.spec, result)
            self.assertTrue((self.root / 'latest.json').is_file())
            self.assertEqual(storage.load(self.root), {'recipe': self.spec, **result})

    def test_interrupted_publication_preserves_previous_pointer_and_can_retry(self):
        journal = storage.Journal(self.root, self.spec)
        old = snapshot(self.spec, [{'event': 0}]); journal.commit(old)
        pointer = (self.root / 'latest.json').read_bytes()
        new = snapshot(self.spec, [{'event': 0}, {'event': 1}])
        with patch.object(storage.os, 'replace', side_effect=OSError('simulated interruption')):
            with self.assertRaisesRegex(OSError, 'interruption'):
                journal.commit(new)
        self.assertEqual((self.root / 'latest.json').read_bytes(), pointer)
        self.assertEqual(storage.load(self.root), {'recipe': self.spec, **old})
        journal.commit(new)
        self.assertEqual(storage.load(self.root), {'recipe': self.spec, **new})

    def test_interrupted_chunk_write_never_exposes_partial_event(self):
        with patch.object(storage.p.shared, 'LIMIT', 1024):
            journal = storage.Journal(self.root, self.spec)
            old = snapshot(self.spec); journal.commit(old)
            original = journal._write_raw
            calls = 0
            def fail_second(raw):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError('simulated chunk failure')
                return original(raw)
            with patch.object(journal, '_write_raw', side_effect=fail_second):
                with self.assertRaisesRegex(OSError, 'chunk failure'):
                    journal.commit(snapshot(self.spec, [{'payload': 'x'*9000}]))
            self.assertEqual(storage.load(self.root), {'recipe': self.spec, **old})

    def test_prefix_mutation_and_bad_checkpoint_rejected_before_publication(self):
        journal = storage.Journal(self.root, self.spec)
        old = snapshot(self.spec, [{'event': 0}]); journal.commit(old)
        for bad in (snapshot(self.spec, [{'event': 'changed'}]), snapshot(self.spec)):
            with self.assertRaisesRegex(ValueError, 'prefix'):
                journal.commit(bad)
        forged = deepcopy(old)
        forged['scientific']['checkpoint']['state_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            journal.commit(forged)
        self.assertEqual(storage.load(self.root), {'recipe': self.spec, **old})

    def test_chunk_tamper_and_reconstructed_digest_are_checked(self):
        with patch.object(storage.p.shared, 'LIMIT', 1024):
            journal = storage.Journal(self.root, self.spec)
            result = snapshot(self.spec, [{'payload': 'x'*4000}]); journal.commit(result)
            ref = journal._refs[0]
            forged = deepcopy(ref); forged['sha256'] = '0'*64
            with self.assertRaisesRegex(ValueError, 'binding differs'):
                storage._read_value(self.root, forged)
            index = storage._read_value(self.root, ref['tree'])
            part = self.root / index['chunks'][0]['file']
            part.write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError, 'no silent rebind'):
                storage.load(self.root)

    def test_reference_traversal_and_missing_record_fail_closed(self):
        journal = storage.Journal(self.root, self.spec)
        journal.commit(snapshot(self.spec, [{'event': 0}]))
        with self.assertRaisesRegex(ValueError, 'safe direct'):
            storage._read_value(self.root, {'file': '../foreign.json', 'sha256': 'a'*64})
        (self.root / journal._refs[0]['file']).unlink()
        with self.assertRaisesRegex(ValueError, 'bounded source file'):
            storage.load(self.root)


if __name__ == '__main__':
    unittest.main()
