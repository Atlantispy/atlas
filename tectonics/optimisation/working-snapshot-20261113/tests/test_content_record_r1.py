"""Unit H (issue 96, content identifiers), T-1: content_record drops the nine code fields at any depth and nothing else.
  python -B -I test_content_record_r1.py <package parent folder>"""
import json
import sys
import unittest

if __name__ == '__main__':
    sys.path.insert(0, sys.argv.pop(1))
from atlas_tectonics import reuse  # noqa: E402
from atlas_tectonics._validation import TectonicsError  # noqa: E402

NAMES = ('execution', 'execution_id', 'source_execution_id', 'source_sha256', 'context', 'context_id',
         'generator_source_sha256', 'pressure_source_sha256', 'helper_source_sha256')
A, B = 'a'*64, 'b'*64


class ContentRecordTests(unittest.TestCase):
    def test_the_list_is_the_nine_names(self):
        self.assertEqual(reuse._CODE_FIELDS, frozenset(NAMES))

    def test_each_name_is_dropped_at_depth_and_a_code_change_gives_equal_bytes(self):
        for name in NAMES:
            with self.subTest(name=name):
                record = dict(schema='s', execution_backend='scipy', heat_source_sha256=B,
                              plan=dict(rows=[dict(k=1, **{name: A}), (dict(**{name: None}), 2)], **{name: A}), **{name: A})
                before = json.dumps(record, sort_keys=True)
                want = dict(schema='s', execution_backend='scipy', heat_source_sha256=B, plan=dict(rows=[dict(k=1), (dict(), 2)]))
                self.assertEqual(reuse.content_record(record), want)
                self.assertEqual(type(reuse.content_record(record)['plan']['rows'][1]), tuple)
                self.assertEqual(json.dumps(record, sort_keys=True), before)
                other = json.loads(before.replace(A, B))
                self.assertEqual(reuse._json(reuse.content_record(record)), reuse._json(reuse.content_record(other)))
                other['plan']['rows'][0]['k'] = 2
                self.assertNotEqual(reuse._json(reuse.content_record(record)), reuse._json(reuse.content_record(other)))

    def test_near_names_are_kept(self):
        record = dict(execution_backend='x', execution_identity=A, heat_source_sha256=A, contexts=A, source_sha=A)
        self.assertEqual(reuse.content_record(record), record)

    def test_a_record_under_a_dropped_name_is_kept_and_read_through(self):
        world = dict(frame='f', calendar='c', helper_source_sha256=A, execution=dict(backend='scipy', execution_id=B))
        out = reuse.content_record(dict(context=world, rows=[dict(execution_id=world)]))
        kept = dict(frame='f', calendar='c', execution=dict(backend='scipy'))
        self.assertEqual(out, dict(context=kept, rows=[dict(execution_id=kept)]))

    def test_untouched_subtrees_are_shared_not_copied(self):
        cells = dict(rows=[[1, 2], (3, dict(k=4))])
        record = dict(cells=cells, plan=dict(rows=[cells, dict(execution=A)]))
        out = reuse.content_record(record)
        self.assertIs(reuse.content_record(cells), cells)
        self.assertIs(out['cells'], cells)
        self.assertIs(out['plan']['rows'][0], cells)
        self.assertEqual(out['plan']['rows'][1], {})
        self.assertIsNot(out['plan'], record['plan'])

    def test_refuses_a_named_field_that_is_not_a_digest(self):
        for name in NAMES:
            for bad in ('A'*64, 'a'*63, 7, [A], (A,)):
                with self.subTest(name=name, bad=bad), self.assertRaisesRegex(TectonicsError, 'content identity refused'):
                    reuse.content_record(dict(rows=[{name: bad}]))


if __name__ == '__main__':
    unittest.main()
