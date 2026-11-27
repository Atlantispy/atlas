"""One assembly decodes its rays once (wave 5-6 unit T-1).

The assembly's first `_unpack` stores (rays, base) in its list; later calls clear the history tables and reset them
to base. A foreign entry added between calls is gone, every ray's history entry is the same object, and a digest
computed before the reset survives it (the base holds the same digest list).

SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from pathlib import Path
import types
import unittest

from atlas_tectonics.integration.geometry import differential_geometry as DG
from atlas_tectonics.integration.geometry import wall_measures as W
from atlas_tectonics.integration.resources import WorkBudget


def _rows(n, shift=0):
    return DG._history_record(tuple(((Q(1+i+shift, 7), Q(-2, 9+i), Q(3, 11)), Q(5+i, 3)) for i in range(n)))


def _geometry(budget):
    geometry = object.__new__(DG.CurrentGeometry)
    object.__setattr__(geometry, '_resource', budget)
    vec = _rows(1)[0]['angular_velocity_rad_s']
    record = dict(plate_ids=[1, 2], ownership_fans=[dict(plate_id=1, ray_ids=['a', 'b'])],
                  rays={key: dict(direction=vec, angular_velocity_rad_s=vec, prior_rotations=_rows(n, n))
                        for key, n in (('a', 2), ('b', 3))})
    return geometry, record


class UnpackRayReset(unittest.TestCase):
    def setUp(self):
        DG._history_rows.clear(); W._history_digests.clear()

    def check(self, unpack):
        budget = WorkBudget(1 << 30)
        geometry, record = _geometry(budget)
        pair = []
        _, _, rays, fans = unpack(geometry, 1, budget, _record=record, _rays=pair)
        self.assertIs(pair[0], rays)
        self.assertEqual(fans, (('a', 'b'),))
        history = rays['a'][2]
        digest = W._history_digest(history)
        entry = W._history_digests[id(history)]
        foreign = DG._history(_rows(4, 9))
        self.assertIn(id(foreign), W._history_digests)
        _, _, again, _ = unpack(geometry, 2, budget, _record=record, _rays=pair)
        self.assertIs(again, rays)
        self.assertNotIn(id(foreign), W._history_digests)
        for key, row in record['rays'].items():
            self.assertIs(DG._history(row['prior_rotations']), rays[key][2])
        self.assertIs(W._history_digests[id(history)], entry)
        self.assertIs(entry[2], W._history_digests[id(history)][2])
        self.assertIs(W._history_digest(history), digest)

    def test_reset_to_base(self):
        self.check(DG._unpack)

    def test_no_clear_before_reset_mutant_is_killed(self):
        source = Path(DG.__file__).read_text(encoding='utf-8')
        old = '        _history_rows.clear()\n        W._history_digests.clear()\n        if _rays:'
        self.assertEqual(source.count(old), 1)
        mutant = types.ModuleType('differential_geometry_mutant')
        mutant.__dict__.update(__file__=DG.__file__, __package__=DG.__package__)
        exec(compile(source.replace(old, '        if _rays:'), DG.__file__, 'exec'), mutant.__dict__)
        mutant._history_rows, mutant.CurrentGeometry = DG._history_rows, DG.CurrentGeometry
        with self.assertRaisesRegex(AssertionError, "unexpectedly found"):  # the foreign entry survives
            self.check(mutant._unpack)


if __name__ == '__main__':
    unittest.main()
