"""Exact-width gate: streamed scanner against a decode-and-walk reference, and the gate rule."""
import json
import random
import unittest

import width_gate as G


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def is_hex(value):
    if type(value) is not str:
        return False
    body = value.removeprefix('-')
    return body.startswith('0x') and len(body) > 2 and not body[2:].strip('0123456789abcdef')


def reference(value):
    """Decode-and-walk reference: widths per root field, and the trajectory step count."""
    fields = {}

    def field(name):
        return fields.setdefault(name, {'count': 0, 'integers': 0,
                                        'max_numerator_bits': 0, 'max_denominator_bits': 0})

    def walk(node, name):
        if type(node) is list:
            if len(node) == 2 and all(is_hex(v) for v in node):
                row = field(name)
                row['count'] += 1
                row['max_numerator_bits'] = max(row['max_numerator_bits'], abs(int(node[0], 16)).bit_length())
                row['max_denominator_bits'] = max(row['max_denominator_bits'], abs(int(node[1], 16)).bit_length())
                return
            for item in node:
                walk(item, name)
        elif type(node) is dict:
            for item in node.values():
                walk(item, name)
        elif is_hex(node):
            row = field(name)
            row['integers'] += 1
            row['max_numerator_bits'] = max(row['max_numerator_bits'], abs(int(node, 16)).bit_length())

    steps = None
    if type(value) is dict:
        for key, item in value.items():
            walk(item, key)
        if type(value.get(G.TRAJECTORY_KEY)) is list:
            steps = len(value[G.TRAJECTORY_KEY])
    else:
        walk(value, '$')
    return dict(sorted(fields.items())), steps


def scan(raw, sizes):
    scanner, at = G.StreamScanner(), 0
    for size in sizes:
        scanner.feed(raw[at:at+size])
        at += size
    scanner.feed(raw[at:])
    return scanner.finish(), scanner.trajectory_steps


def random_value(rng, depth=0):
    choice = rng.randrange(10 if depth < 4 else 6)
    if choice == 0:
        return hex(rng.choice((0, 1, 7, 255, 1 << rng.randrange(300)) )*rng.choice((1, -1)))
    if choice == 1:
        return [hex(rng.getrandbits(rng.randrange(1, 400))), hex(rng.getrandbits(rng.randrange(1, 400)) | 1)]
    if choice == 2:
        return rng.choice(('plain', 'a"b', 'back\\slash', 'été', '0x', '0xZ', '-0x', '0X1', 'x0x1', ''))
    if choice == 3:
        return rng.choice((0, -3, 2.5, 1e-300, True, False, None, 12345678901234567890))
    if choice == 4:
        return [hex(rng.getrandbits(64)), 'not-hex']
    if choice == 5:
        return [rng.randrange(9), hex(rng.getrandbits(32))]
    if choice in (6, 7):
        return [random_value(rng, depth+1) for _ in range(rng.randrange(4))]
    return {rng.choice(('a', 'b"q', 'k\\', 'm', 'z')) + str(i): random_value(rng, depth+1)
            for i in range(rng.randrange(4))}


class WidthGateTests(unittest.TestCase):
    def test_hex_bits_without_parsing(self):
        for value in (0, 1, 2, 15, 16, 255, 256, (1 << 1000)-1, 1 << 2054538):
            for sign in (1, -1):
                self.assertEqual(G.hex_bits(hex(sign*value)), value.bit_length())
        for bad in ('0x', '1', '0X1', '-0x', '0xg', 'x1'):
            with self.assertRaises(ValueError):
                G.hex_bits(bad)

    def test_random_records_match_the_reference_in_any_chunking(self):
        rng = random.Random(20261016)
        for trial in range(300):
            value = {('k' + str(i)): random_value(rng) for i in range(rng.randrange(1, 6))}
            if trial % 3 == 0:
                value[G.TRAJECTORY_KEY] = [{'start_time_s': hex(i)} for i in range(rng.randrange(4))]
            if trial % 7 == 0:
                value = [value, random_value(rng)]
            raw = canonical(value)
            expected = reference(value)
            for sizes in ([len(raw)], [1]*len(raw), [rng.randrange(1, 9) for _ in range(len(raw)//2)]):
                self.assertEqual(scan(raw, sizes), expected, (trial, raw[:200]))

    def test_megabyte_token_split_across_chunks(self):
        numerator, denominator = (1 << 2054538) | 1, (1 << 1724159) | 3
        raw = canonical({'exact_cell_storage_residual_j': [[hex(numerator), hex(denominator)], [hex(-5), hex(7)]],
                         'trajectory_segments': [{}, {}]})
        fields, steps = scan(raw, [65536]*(len(raw)//65536))
        self.assertEqual(fields['exact_cell_storage_residual_j'],
                         {'count': 2, 'integers': 0, 'max_numerator_bits': 2054539, 'max_denominator_bits': 1724160})
        self.assertEqual(steps, 2)

    def test_incomplete_stream_refused(self):
        scanner = G.StreamScanner().feed(b'{"a":["0x1","0x')
        with self.assertRaises(ValueError):
            scanner.finish()

    def test_table_merges_records_of_one_kind(self):
        table = G.WidthTable(1)
        table.scan('heat', [canonical({'a': ['0xff', '0x1'], 'b': '0x1'})])
        table.scan('heat', [canonical({'a': ['0x1', '0xfff']})])
        table.scan('mesh', [canonical({'trajectory_segments': [{}], 'c': [['0x1', '0x3']]})])
        self.assertEqual(table.records['heat']['a'],
                         {'count': 2, 'integers': 0, 'max_numerator_bits': 8, 'max_denominator_bits': 12})
        self.assertEqual(table.records['heat']['b']['integers'], 1)
        self.assertEqual(table.trajectory_steps, 1)
        self.assertEqual(table.widths()[('heat', 'a')], 12)
        self.assertEqual(json.loads(json.dumps(table.wire()))['records']['mesh']['c']['count'], 1)

    def table(self, interval, widths):
        table = G.WidthTable(interval)
        for (kind, name), bits in widths.items():
            table.records.setdefault(kind, {})[name] = {'count': 1, 'integers': 0,
                'max_numerator_bits': bits, 'max_denominator_bits': 1}
        return table

    def test_gate_rule_at_its_boundaries(self):
        limit = G.LIMIT_BITS
        # A field absent at interval 0 takes W0 = 0: W2 = 2*W1.
        self.assertTrue(G.gate(self.table(0, {}), self.table(1, {('heat', 'x'): limit//4}))['passed'])
        self.assertFalse(G.gate(self.table(0, {}), self.table(1, {('heat', 'x'): limit//4+1}))['passed'])
        # Measured W0: W2 = W1+(W1-W0).
        result = G.gate(self.table(0, {('mesh', 'c'): 1000}), self.table(1, {('mesh', 'c'): 2*limit//5}))
        self.assertFalse(result['passed'])
        self.assertEqual(result['rows'][0]['w2_projected_bits'], 4*limit//5-1000)
        result = G.gate(self.table(0, {('mesh', 'c'): 7*limit//20}), self.table(1, {('mesh', 'c'): 2*limit//5}))
        self.assertTrue(result['passed'])
        self.assertTrue(result['rows'][0]['w0_measured'])
        # r9 interval 1: the widest heat value, absent at the root, projects to 49.0%.
        r9 = G.gate(self.table(0, {}), self.table(1, {('heat', 'exact_cell_storage_residual_j'): 2054539}))
        self.assertTrue(r9['passed'])
        self.assertAlmostEqual(r9['rows'][0]['w2_share'], 0.4898, places=4)
        self.assertAlmostEqual(r9['rows'][0]['w3_share'], 0.7348, places=4)

    def test_recorded_table_round_trips_and_gates_like_the_original(self):
        root = G.WidthTable(0)
        root.scan('mesh', [canonical({'trajectory_segments': [], 'c': [['0x1', '0x3']]})])
        interval1 = self.table(1, {('mesh', 'c'): 2*G.LIMIT_BITS//5})
        recorded = G.WidthTable.from_wire(json.loads(json.dumps(root.wire())))
        self.assertEqual(recorded.wire(), root.wire())
        self.assertEqual(G.gate(recorded, interval1), G.gate(root, interval1))
        wire = root.wire()
        for change in ({'limit_bits': 1}, {'schema': 'other'}, {'records': {'mesh': {'c': {'count': -1}}}},
                       {'records': {'mesh': {'c': dict(wire['records']['mesh']['c'], count=True)}}},
                       {'trajectory_steps': 1.5}, {'extra': 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                G.WidthTable.from_wire(dict(wire, **change))

    def test_compare_lists_every_difference(self):
        reference_rows = {'heat': {'a': {'count': 1}}, 'mesh': {'c': {'count': 2}}}
        measured = {'heat': {'a': {'count': 1}}, 'mesh': {'c': {'count': 3}, 'd': {'count': 1}}}
        self.assertEqual([(r['record'], r['field']) for r in G.compare(reference_rows, measured)],
                         [('mesh', 'c'), ('mesh', 'd')])


if __name__ == '__main__':
    unittest.main()
