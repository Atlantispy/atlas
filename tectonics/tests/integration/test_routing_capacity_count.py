"""The fast decoded-JSON capacity count gives the byte walk's number, or the walk's refusal, on every input."""
import itertools
import json
import random
import unittest

from atlas_tectonics.integration.coupling import routing_views as R

UNITS = ['"', '\\', '{', '}', '[', ']', ':', ',', ' ', '0', '1', '-', '.', 'e', 'true', 'x']


def _outcome(function, raw):
    try:
        return 'value', function(raw)
    except Exception as error:  # noqa: BLE001 - the refusal is the result compared
        return 'refused', type(error).__name__, str(error)


def _records(rng, count, plain):
    words = ['cell', 'face', ''] if plain else ['cell', 'a"b', 'tab\there', 'back\\slash', 'é', '☃', '']
    top = 60 if plain else 120
    for i in range(count):
        cells = [dict(cell_id='c%06d' % rng.randrange(10**6), volume_m3=rng.uniform(-1e12, 1e12),
                      end=rng.choice([0.0, -0.0, 1e-300, 5e-324, 1.5e300]),
                      plate=rng.randrange(-(10**rng.randint(1, top)), 10**rng.randint(1, top)),
                      flags=[True, False, None][:rng.randint(0, 3)])
                 for _ in range(rng.randint(0, 8))]
        record = dict(cells=cells, path=[[rng.random(), [rng.randrange(9)]], {}], label=rng.choice(words))
        yield json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False,
                         ensure_ascii=i % 2 == 0).encode()


class CapacityCountTest(unittest.TestCase):
    def assert_parity(self, raws):
        for raw in raws:
            self.assertEqual(_outcome(R._decoded_json_capacity, raw), _outcome(R._walked_json_capacity, raw), raw)

    def test_every_short_byte_string_matches_the_walk(self):
        self.assert_parity(''.join(u).encode() for n in range(5) for u in itertools.product(UNITS, repeat=n))

    def test_issued_shaped_records_match_and_plain_ones_skip_the_walk(self):
        self.assert_parity(_records(random.Random(20261115), 300, plain=False))
        plain = list(_records(random.Random(20261116), 100, plain=True))
        self.assert_parity(plain)
        self.assertTrue(all(R._counted_json_capacity(raw) is not None for raw in plain))


if __name__ == '__main__':
    unittest.main()
