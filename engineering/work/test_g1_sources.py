"""Focused source-pass equivalence and individually measured deduplication."""
from copy import deepcopy
from statistics import median
import time
import unittest
from unittest.mock import patch
from work.generator_upgrade_r18 import provenance as previous
from work.geology_r1 import native, provenance

RECORD = {}


class Sources(unittest.TestCase):
    def test_exact_fresh_passes_and_measure(self):
        binding = previous.identity()
        self.assertEqual(native.guarded(previous, 'identity'), binding)
        pairs = []
        for n in range(3):
            row = {}
            for kind in (('old','new') if n % 2 == 0 else ('new','old')):
                start = time.perf_counter()
                if kind == 'old': previous.verify(binding)
                else: native.guarded(previous, 'verify', binding)
                row[kind] = time.perf_counter()-start
            pairs.append(row)
        before, after = (median(row[key] for row in pairs) for key in ('old','new'))
        RECORD.update(scope='One complete retained R18 source-verification pass, not a full geology build',
                      pairs=pairs,before_seconds=before,after_seconds=after,
                      saved_seconds=before-after,saved_percent=100*(before-after)/before,
                      native_identity_equal=True)
        changed = deepcopy(binding)
        changed['sources'][next(iter(changed['sources']))] = '0'*64
        with self.assertRaises(ValueError): native.guarded(previous, 'verify', changed)
        with patch.object(provenance.preflight, '_R12_EXECUTED_SHA256', '0'*64):
            with self.assertRaisesRegex(ValueError, 'helper executed source'):
                provenance.sources()
        self.assertEqual(native.regional.build.__code__, native.original.build.__code__)
        self.assertEqual(native.build_columns.__code__, native.columns.build_columns.__code__)


if __name__ == '__main__': unittest.main()
