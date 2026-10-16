"""Rebuild the takeover test_spatial_records_patch.py by reversing my edits.

Writes before-src/test_spatial_records_patch.py only if the result hashes to the
takeover hash recorded in baseline-hashes-takeover.json.
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
C = HERE.parents[2]/'compact-geometry-r1'
NAME = 'test_spatial_records_patch.py'

ADDED_TEST = '''        self.assertIn('_COMPACT_RECORDS.publication_check(check, self._store, row', transformed)
        # Step 8: the certification booking width accepts a live compact graph.
        self.assertNotIn('len(solution.graph._json)', transformed)
        self.assertIn('_COMPACT_RECORDS.holder_bytes(solution.graph)', transformed)

    def test_holder_bytes_matches_native_width_and_compact_canonical_bytes(self):
        from types import SimpleNamespace
        raw = b'{"a":[1,2,3],"b":"x"}'
        self.assertEqual(P.holder_bytes(SimpleNamespace(_json=raw)), len(raw))
        budget = WorkBudget(1 << 28)
        scope = create_retained_scope(budget, process_epoch='step8-holder-bytes')
        packed = RecordCodec().pack_record({'a': [1, 2, 3], 'b': 'x'}, record_schema='atlas.test.v1',
                                           scope=scope, check=lambda: None)
        self.assertEqual(P.holder_bytes(SimpleNamespace(_json=packed)), len(raw))
        packed.close()
        scope.close()
'''
ORIGINAL_TEST = "        self.assertIn('_COMPACT_RECORDS.publication_check(check, self._store, row', transformed)\n"


def main():
    raw = (C/NAME).read_bytes()
    text = raw.decode('utf8')
    newline = '\r\n' if '\r\n' in text else '\n'
    text = text.replace('\r\n', '\n')
    assert text.count(ADDED_TEST) == 1 and text.count('from record_tables import RecordCodec, canonical\n') == 1
    text = text.replace(ADDED_TEST, ORIGINAL_TEST).replace(
        'from record_tables import RecordCodec, canonical\n', 'from record_tables import canonical\n')
    rebuilt = text.replace('\n', newline).encode('utf8')
    recorded = json.loads((HERE/'baseline-hashes-takeover.json').read_text(encoding='utf8'))
    want = recorded['compact-geometry-r1/'+NAME]['sha256']
    got = hashlib.sha256(rebuilt).hexdigest()
    print('takeover', want)
    print('rebuilt ', got)
    if got != want:
        raise SystemExit('rebuilt original differs; not written')
    (HERE/'before-src'/NAME).write_bytes(rebuilt)
    print('written before-src/'+NAME)


if __name__ == '__main__':
    main()
