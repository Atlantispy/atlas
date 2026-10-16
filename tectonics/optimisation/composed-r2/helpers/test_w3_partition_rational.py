"""W3 L20: partition_v2's rational gate refuses exactly what v1 refuses.

v1 (pack_partition + CompactPartition) requires the canonical spelling
[hex(n), hex(d)] with d > 0 and gcd(n, d) == 1. The base v2 gate checked only
the '0x' prefix, int() parsing and magnitude, so it accepted zero/negative
denominators, unreduced pairs, leading zeros, '_' and whitespace. Each case
is packed through both routes on the same honest-hashed synthetic
partition; canonical pairs (including 1 MiB-wide magnitudes) keep identical
v2 record identities with the base module (w3ref_partition_v2), and every
reservation is released.
"""
import gc
import sys
import unittest
from copy import deepcopy
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_partition_tables import D, WorkBudget, tiny_partition  # runtime path

# isort: split
import partition_tables as P
import partition_v2 as V2
import w3ref_partition_v2 as BASE
from content_cache import create_retained_scope

WIDE = (1 << (8*(1 << 20)-1))+1  # odd, exactly 1 MiB of magnitude
REFUSED = {
    'zero_denominator': ['0x1', '0x0'],
    'unreduced_2_over_4': ['0x2', '0x4'],
    'negative_denominator': ['0x1', '-0x3'],
    'leading_zero_hex': ['0x01', '0x3'],
    'underscore_hex': ['0x_1', '0x3'],
    'upper_case_hex': ['0xA', '0x3'],
    'negative_zero': ['-0x0', '0x1'],
    'trailing_space': ['0x1 ', '0x3'],
    'zero_over_two': ['0x0', '0x2'],
    'wide_unreduced': [hex(2*WIDE), '0x2'],
    'unreduced_64k_over_3': [hex((1 << (8*65536-1))+1), '0x3'],  # 2**odd+1 is divisible by 3
}
ACCEPTED = {
    'canonical': ['0x1', '0x3'],
    'negative': ['-0x5', '0x3'],
    'zero': ['0x0', '0x1'],
    'wide_numerator': [hex(WIDE), '0x2'],
    'wide_denominator': ['-0x1', hex(WIDE)],
    'numerator_64k': [hex((1 << (8*65536-1))+1), '0x2'],
}
# 1 MiB canonical magnitudes: v1 accepts, but the base v2 already refuses them on
# another unchanged bound (pre-existing, reported); these prove v2 decides as the base did.
WIDE_CASES = ('wide_numerator', 'wide_denominator')


def body_rows(budget, pair):
    body, rows = tiny_partition(budget)
    rows = deepcopy(rows)
    rows[0]['constraints'] = deepcopy(rows[0]['constraints'])
    rows[0]['constraints']['plane']['offset'] = list(pair)
    body = deepcopy(body)
    body['support_ids'] = [D._record_hash(r) for r in rows]
    return body, rows, D._record_hash(body)


def route(kind, pair, module=V2):
    budget = WorkBudget(1 << 30)
    scope = create_retained_scope(budget, process_epoch='w3-l20')
    body, rows, pid = body_rows(budget, pair)
    result = None
    try:
        if kind == 'v1':
            metadata, arrays = P.pack_partition(body, iter(rows), expected_partition_id=pid, budget=budget)
            view = P.CompactPartition(metadata, arrays, expected_partition_id=pid, budget=budget)
            result = ('accepted', None)
            del view, metadata, arrays
        else:
            view = module.pack_partition_v2(body, iter(rows), expected_partition_id=pid, scope=scope)
            result = ('accepted', view._record.identity())
            view.close()
    except ValueError as error:  # ContractError, PartitionTablesRefused and int() parsing
        result = ('refused', type(error).__name__)
        error = None
    gc.collect()
    scope.close()
    return result, budget.reserved_bytes


class RationalGateTests(unittest.TestCase):
    def test_v2_refuses_what_v1_refuses(self):
        for name, pair in REFUSED.items():
            with self.subTest(case=name):
                v1, left1 = route('v1', pair)
                v2, left2 = route('v2', pair)
                self.assertEqual(v1[0], 'refused')
                self.assertEqual(v2[0], 'refused')
                self.assertEqual((left1, left2), (0, 0))

    def test_canonical_pairs_accepted_with_unchanged_identity(self):
        for name, pair in ACCEPTED.items():
            with self.subTest(case=name):
                v1, _ = route('v1', pair)
                v2, left = route('v2', pair)
                base, left_base = route('v2', pair, BASE)
                print('W3 L20', name, 'v1', v1, 'v2', v2[0], 'base', base[0], flush=True)
                self.assertEqual(v2, base)
                if name not in WIDE_CASES:
                    self.assertEqual((v1[0], v2[0]), ('accepted', 'accepted'))
                self.assertEqual((left, left_base), (0, 0))


if __name__ == '__main__':
    unittest.main()
