"""Plan 18 selftest: the spatial-owner initial allocation does not depend on cell_id order.

integration_spatial_owner.py allocates each source enclosure's exterior rows sorted by cell_id. With a measure
policy it calls integration_dual_geometry.initial_allocation, which sorts the cell_id keys again; without one it
calls integration_collar_geometry._partition directly. The compact header-retention fix renumbers cell_id (a sha256
of the logical cell id and the support id), so the same cells arrive in a different order.

These tests run that allocation on the same cells under the original and the renumbered cell_ids, on both routes, and
require bitwise-identical encoded values (exact numerator and denominator) for every logical cell. A forged
order-dependent allocator, a greedy fill in row order, must be reported on both routes. Source anchors pin the lines
this test mirrors, so a change there fails here instead of silently testing something else. integration_spatial_owner
itself is not changed or imported.
"""
import hashlib
import random
import unittest
from fractions import Fraction as Q
from pathlib import Path
from unittest import mock

import atlas_tectonics
from atlas_tectonics import integration_collar_geometry as CG
from atlas_tectonics.integration_dual_geometry import _enc, initial_allocation
from atlas_tectonics.resources import WorkBudget

PACKAGE = Path(atlas_tectonics.__file__).resolve().parent
ANCHORS = {
    'integration_spatial_owner.py': (
        "rows = sorted((r for r in exterior if tuple(r['source_key']) == key), key=lambda r: r['cell_id'])",
        "volumes = _partition([tuple(map(_q, r[key_bounds])) for r in rows], total)",
        "admitted = initial_allocation({r['cell_id']: tuple(map(_q, r[key_bounds])) for r in rows}, total,",
        "relative_limits={r['cell_id']: _q(self._measure_policy['initial_relative_error']) for r in rows},",
        "volumes = tuple(admitted['booked'][r['cell_id']] for r in rows)",
        "for row, volume in zip(rows, volumes):",
    ),
    'integration_dual_geometry.py': (
        'keys = sorted(bounds)',
        'values = _partition(admitted, Q(total))',
        'booked=dict(zip(keys, values))',
        'from .integration_collar_geometry import _partition',
    ),
}
RELATIVE = Q(1, 4)
SUPPORT = 'f3' * 32


def enclosures(seed=18, count=24):
    """Exact cell bounds and a total strictly inside the admissible sum, per enclosure."""
    rng = random.Random(seed)
    result = []
    for number in range(count):
        cells = []
        for _ in range(rng.randint(2, 40)):
            low = Q(rng.randint(1, 10**6), rng.randint(1, 997))
            cells.append((low, low*(1+Q(rng.randint(0, 499), 1000))))
        admitted = [(max(a, (1-RELATIVE)*b), min(b, (1+RELATIVE)*a)) for a, b in cells]
        low, high = sum((a for a, _ in admitted), Q(0)), sum((b for _, b in admitted), Q(0))
        total = low+(high-low)*Q(rng.randint(1, 999), 1000) if high > low else low
        result.append(('enclosure-%02d' % number, cells, total))
    return result


def identities(name, cells):
    original = ['%s-cell-%05d' % (name, number) for number in range(len(cells))]
    renumbered = [hashlib.sha256((logical+'\0'+SUPPORT).encode()).hexdigest() for logical in original]
    return original, renumbered


def allocate(cells, ids, total, policy):
    """The spatial-owner block for one enclosure: rows sorted by cell_id, values keyed back by logical cell."""
    rows = sorted(({'cell_id': ids[number], 'logical': number, 'bounds': bounds}
                   for number, bounds in enumerate(cells)), key=lambda row: row['cell_id'])
    if policy is None:
        volumes = CG._partition([row['bounds'] for row in rows], total)
    else:
        admitted = initial_allocation({row['cell_id']: row['bounds'] for row in rows}, total,
                                      relative_limits={row['cell_id']: policy for row in rows},
                                      max_total_width=sum((b-a for a, b in cells), Q(0)), budget=WorkBudget(1 << 26))
        volumes = tuple(admitted['booked'][row['cell_id']] for row in rows)
    return {row['logical']: _enc(volume) for row, volume in zip(rows, volumes, strict=True)}


def order_problems(policy):
    """Enclosures whose encoded values differ between the two cell_id orders of the same cells."""
    problems = {}
    for name, cells, total in enclosures():
        original, renumbered = identities(name, cells)
        first, second = allocate(cells, original, total, policy), allocate(cells, renumbered, total, policy)
        differing = sorted(number for number in first if first[number] != second[number])
        if differing:
            problems[name] = differing
    return problems


def greedy(bounds, total):
    """Forged order-dependent allocator: lower bounds, then the remainder filled in row order."""
    values, rest = [], total-sum((a for a, _ in bounds), Q(0))
    for a, b in bounds:
        take = min(b-a, rest)
        values.append(a+take)
        rest -= take
    return tuple(values)


class SpatialAllocationOrder(unittest.TestCase):
    def test_the_two_cell_id_orders_differ(self):
        moved = 0
        for name, cells, _ in enclosures():
            original, renumbered = identities(name, cells)
            moved += sorted(range(len(cells)), key=original.__getitem__) != \
                sorted(range(len(cells)), key=renumbered.__getitem__)
        self.assertGreaterEqual(moved, 20, 'the renumbering must reorder the cells for the test to mean anything')

    def test_allocation_is_bitwise_identical_under_both_orders(self):
        for policy in (None, RELATIVE):
            with self.subTest(route='initial_allocation' if policy else '_partition'):
                self.assertEqual(order_problems(policy), {})

    def test_forged_order_dependent_allocation_is_reported(self):
        with mock.patch.object(CG, '_partition', greedy):
            for policy in (None, RELATIVE):
                with self.subTest(route='initial_allocation' if policy else '_partition'):
                    self.assertTrue(order_problems(policy), 'a greedy row-order fill must be reported')

    def test_source_anchors(self):
        for name, anchors in ANCHORS.items():
            text = (PACKAGE/name).read_text(encoding='utf-8')
            for anchor in anchors:
                with self.subTest(module=name, anchor=anchor[:48]):
                    self.assertEqual(text.count(anchor), 1)


if __name__ == '__main__':
    unittest.main()
