"""x-mesh-booking (A5): pack_mesh booking covers transient copies of wide rationals.

The adversarial reviewer (aw2_mesh_bigint.py) found W3's derived booking 2.1x
below the traced peak for an admissible mesh with ONE wide canonical rational
(8,388,600 bits: booked 2,529,585, peak about 5.4 MB): the input stream and
the canonical-spelling check keep transient str/bytes copies of the widest
tokens that the 1.1 B per hex digit term does not cover. The booking now adds
2*max(L1, P)+256: L1 the widest scalar token, P the widest sum of two scalar
tokens that are neighbours in one list (consecutive stream chunks; re-check
defect 4 replaced 2*(L1+L2), which over-booked about 2x for two wide tokens
that are not neighbours). Every case below must have traced peak <= booked,
and output identical to W3's module (w3ref_mesh_tables).
tracemalloc measures memory only, never timing.
"""
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_mesh_tables  # noqa: F401  (side effect: puts the runtime path on sys.path)

# isort: split
import mesh_tables as M
import test_w3_mesh_booking as W
import w3ref_mesh_tables as BASE


def wide_int(bits, rng, negative=False):
    value = (1 << (bits-1)) | rng.getrandbits(bits-1) | 1
    return -value if negative else value


def q(n, d=1):
    return [hex(n), hex(d)]


def reproducer(bits):
    # aw2_mesh_bigint.py exactly: one wide numerator, denominator 1.
    record = W.build(n_cells=4, n_faces=8, face_bits=64, cell_bits=64)
    record['cells'][0]['volume_m3'] = q((1 << (bits-1)) | 1)
    return record


def max_width_negative():
    # The widest admitted integer (MAX_INTEGER_BYTES), negative: abs copies.
    record = reproducer(8)
    record['cells'][0]['volume_m3'] = q(-((1 << (8*M.MAX_INTEGER_BYTES-1)) | 1))
    return record


def moderately_wide():
    # Several 200k-500k-bit rationals spread over cells, faces and a grid
    # line; negative numerators (abs copies) and wide denominators.
    rng = random.Random(3)
    record = W.build(n_cells=20, n_faces=100, face_bits=800, cell_bits=4000)
    record['cells'][1]['volume_m3'] = q(wide_int(500_000, rng, True))
    record['cells'][2]['centroid_m'][1] = q(1, wide_int(300_000, rng))
    record['cells'][3]['volume_centroid_m'][2] = q(wide_int(200_000, rng))
    record['faces'][5]['vertices_m'][0][0] = q(wide_int(250_000, rng, True))
    record['grid_lines'] = [[q(0), q(wide_int(400_000, rng))], [q(0), q(1)], [q(0), q(1)]]
    return record


def many_wide():
    # Every cell rational and every face rational wide (all unique).
    rng = random.Random(5)
    record = W.build(n_cells=6, n_faces=12, face_bits=64, cell_bits=64)
    for row in record['cells']:
        row['volume_m3'] = q(wide_int(120_000, rng, rng.random() < 0.5))
        row['centroid_m'] = [q(wide_int(120_000, rng, rng.random() < 0.5)) for _ in range(3)]
        row['physical_volume_bounds_m3'] = [q(1, wide_int(120_000, rng)), q(wide_int(120_000, rng))]
        row['geometry_volume_max_deviation_m3'] = q(1, wide_int(120_000, rng))
        row['volume_centroid_m'] = [q(wide_int(120_000, rng, True)) for _ in range(3)]
    for row in record['faces']:
        row['centroid_m'] = [q(wide_int(20_000, rng)) for _ in range(3)]
        row['area_vector_m2'] = [q(wide_int(20_000, rng, True)) for _ in range(3)]
        row['vertices_m'] = [[q(wide_int(20_000, rng)) for _ in range(3)] for _ in range(4)]
    return record


def both_wide(bits):
    # Two consecutive wide tokens (numerator AND denominator): the stream
    # holds copies of both at once. gcd(2^k+1, 2^k+3) = 1.
    record = W.build(n_cells=4, n_faces=8, face_bits=64, cell_bits=64)
    base = 1 << (bits-1)
    record['cells'][0]['volume_m3'] = q(-(base+1), base+3)
    return record


def shared_plus_wide():
    # Shared (deduplicated) small rationals plus a wide rational repeated in
    # three places (duplicate-lookup transients) and a second wide one.
    rng = random.Random(9)
    record = W.build(n_cells=150, n_faces=1500, face_bits=800, cell_bits=4000, shared=True)
    big = q(wide_int(4_000_000, rng, True))
    record['cells'][0]['volume_m3'] = big
    record['cells'][1]['volume_m3'] = list(big)
    record['cells'][2]['centroid_m'][0] = list(big)
    record['faces'][3]['area_vector_m2'][1] = q(1, wide_int(1_000_000, rng))
    return record


def supports_plus_wide():
    rng = random.Random(13)
    record = W.build(n_cells=60, n_faces=600, face_bits=800, cell_bits=4000, supports=2000)
    record['cells'][5]['volume_m3'] = q(wide_int(6_000_000, rng))
    return record


def header_wide():
    # Header tokens are encoded by the stream but not pooled.
    rng = random.Random(17)
    record = W.build(n_cells=4, n_faces=8, face_bits=64, cell_bits=64)
    record['time_s'] = q(wide_int(4_000_000, rng))
    return record


def nonadjacent(count, bits):
    # Re-check defect 4: equally wide numerators in different cells are never
    # consecutive stream chunks; each one's neighbour is its small denominator.
    rng = random.Random(21)
    record = W.build(n_cells=4, n_faces=8, face_bits=64, cell_bits=64)
    for row in record['cells'][:count]:
        row['volume_m3'] = q(wide_int(bits, rng))
    return record


def header_list_pair():
    # Two wide strings that ARE neighbours in one header list.
    record = W.build(n_cells=4, n_faces=8, face_bits=64, cell_bits=64)
    record['source'] = {'fixture_only': True, 'notes': ['0x' + 'f'*900_000, '0x' + 'e'*900_000]}
    return record


CASES = {
    'aw2-reproducer-8388600': lambda: reproducer(8*(1 << 20)-8),
    'aw2-reproducer-4194304': lambda: reproducer(4*(1 << 20)),
    'max-width-negative': max_width_negative,
    'moderately-wide': moderately_wide,
    'many-wide': many_wide,
    'both-wide-4194304': lambda: both_wide(4*(1 << 20)),
    'shared-plus-wide': shared_plus_wide,
    'supports-plus-wide': supports_plus_wide,
    'header-wide': header_wide,
    'nonadjacent-2x4Mbit': lambda: nonadjacent(2, 4 << 20),
    'header-list-adjacent-pair': header_list_pair,
}


class WideRationalBookingTests(unittest.TestCase):
    def test_booking_covers_traced_peak_with_wide_rationals(self):
        for label, make in CASES.items():
            with self.subTest(case=label):
                record = make()
                metadata, columns, blobs, booked, peak, budget = W.pack(M, record, trace=True)
                base = W.pack(BASE, record, trace=False)
                print('XMB', label, 'booked', booked, 'traced peak', peak, f'booked/peak {booked/peak:.3f}',
                      'W3 booked', base[3], flush=True)
                self.assertLessEqual(peak, booked)
                self.assertEqual(M.canonical(metadata), BASE.canonical(base[0]))
                self.assertEqual(columns, base[1])
                self.assertEqual(blobs, base[2])
                self.assertEqual(budget.reserved_bytes, 0)
                del record, metadata, columns, blobs, base

    def test_width_unchanged_and_top_two_tracked(self):
        rng = random.Random(21)
        values = [None, True, 0, -5, 2.5, '', 'a"b\\c', '\x00\x1f', 'é\U0001f642', hex(rng.getrandbits(4000)),
                  {'k': ['0x' + 'f'*100, -(1 << 900), {'deep': '0x' + 'e'*300}]}, [[q(7), q(-9, 11)]]*3,
                  ['0x' + 'a'*50, [1], '0x' + 'b'*70, None, '0x' + 'c'*9], {'x': '0x' + 'd'*40, 'y': ['0x1', 2]}]
        for value in values:
            top = [0, 0, 0]
            self.assertEqual(M._width(value, 0, top), M._width(value))
            self.assertEqual(M._width(value), BASE._width(value))
            scalars, pairs = [], [0]

            def walk(v, scalars=scalars, pairs=pairs):
                if type(v) is list:
                    for i, x in enumerate(v):
                        walk(x)
                        if type(x) not in (list, dict):
                            # A scalar plus its preceding scalar neighbour (None/bool
                            # included); none before it, or a container, adds 0.
                            before = v[i-1] if i else []
                            pairs.append(M._width(x)+(0 if type(before) in (list, dict) else M._width(before)))
                elif type(v) is dict:
                    for k, x in v.items():
                        walk(k)
                        walk(x)
                elif type(v) in (str, int, float):
                    # None/bool (5 B) are not tracked; the 256 B constant covers them.
                    scalars.append(M._width(v))
            walk(value)
            expected = sorted(scalars, reverse=True)+[0, 0]
            self.assertEqual(top[:2], expected[:2], repr(value)[:80])
            self.assertEqual(top[2], max(pairs), repr(value)[:80])

    def test_refusals_unchanged(self):
        # Over-wide integer and header still refuse with W3's message.
        budget = W.WorkBudget(1 << 30)
        over = reproducer(8)
        over['cells'][0]['volume_m3'] = q((1 << (8*M.MAX_INTEGER_BYTES)) | 1)
        head = reproducer(8)
        head['time_s'] = q((1 << 8_400_000) | 1)
        for bad in (over, head):
            with self.assertRaises(Exception) as new:
                M.pack_mesh(bad, support_writer=lambda h, raw: None, budget=budget)
            with self.assertRaises(Exception) as old:
                BASE.pack_mesh(bad, support_writer=lambda h, raw: None, budget=budget)
            self.assertEqual((type(new.exception).__name__, str(new.exception)),
                             (type(old.exception).__name__, str(old.exception)))
            self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
