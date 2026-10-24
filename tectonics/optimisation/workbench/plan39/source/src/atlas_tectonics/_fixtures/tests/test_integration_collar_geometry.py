"""One-time actual-source collar funding, not a shared-clock acceptance claim.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import contextmanager
from fractions import Fraction as Q
import unittest

import numpy as np

from atlas_tectonics import integration_collar_geometry as G
from atlas_tectonics import integration_volume as V
from atlas_tectonics.constitutive import BoussinesqMaterial
from atlas_tectonics.regional_collar3d import PreparedRegionalCollar3D
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
import test_i04_regional_owner as F


@contextmanager
def fixture(*, interior=True):
    budget = WorkBudget(256 << 20)
    source = list(F.physical_source(budget))
    if interior:
        # NEW collar fixture, not a moved old assertion. Its entire padded box
        # has global radial coordinate 7.5..9.5, transverse coordinates bounded
        # by |x|<=1 and .5<=y<=2.5: 7<r<10 and latitude strictly inside band2.
        # Only the original two meridian-adjacent source patches are needed.
        source[-1] = (-.5, 1., -2.)
    source = tuple(source)
    volume_map = F.physical_map(source, budget)
    material = BoussinesqMaterial('test:physical-density', 'synthetic-control',
        1.1, 1., .1, 0., 1., 0., 0., (1., 2.))
    with F.prepare(source[4], budget, material) as native, F.physical_owner(native, source, volume_map, budget) as owner:
        with PreparedRegionalCollar3D(native, volume_map, ((1, 1),)*3, budget=budget) as collar:
            yield source, owner, collar, budget


def fund(source, owner, collar, budget):
    return G.fund_full_cells(*source[:2], collar, owner, max_cell_volume_width_m3=Q(1, 10**8),
        max_field_errors=dict(mass_kg=Q(0), enthalpy_j=Q(1, 10**7), source_kappa_mass_kg=Q(0)),
        max_leaves=512, budget=budget)


def decode(pair):
    return Q(int(pair[0], 16), int(pair[1], 16))


class CollarFundingAlgebra(unittest.TestCase):
    def test_partition_allocation_is_bounded_exact_and_label_invariant(self):
        bounds = ((Q(1, 10), Q(2, 5)), (Q(1, 4), Q(1, 2)), (Q(0), Q(1, 5)))
        volume = Q(4, 5)
        values = G._partition(bounds, volume)
        self.assertEqual(sum(values), volume)
        self.assertTrue(all(a <= v <= b for v, (a, b) in zip(values, bounds)))
        for order in ((2, 1, 0), (1, 2, 0), (0, 2, 1)):
            self.assertEqual(G._partition(tuple(bounds[i] for i in order), volume), tuple(values[i] for i in order))
        with self.assertRaises(V.VolumeError):
            G._partition(((Q(0), Q(1, 10)),), 1)  # cannot normalise missing material
        self.assertEqual(G._partition(((Q(1, 3), Q(1, 3)), (Q(2, 3), Q(2, 3))), 1), (Q(1, 3), Q(2, 3)))


class ActualCollarFunding(unittest.TestCase):
    def test_source_debits_remainder_inner_identity_and_exact_restore(self):
        with fixture() as (source, owner, collar, budget):
            result = fund(source, owner, collar, budget)
            record, arrays = result.descriptor(), result.arrays()
            self.assertEqual(record['source']['moving_id'], source[1].moving_id)
            self.assertEqual(record['collar_plan_id'], collar.plan_id)
            self.assertEqual(record['cells'], [4, 4, 4])
            for name, value in arrays.items():
                self.assertFalse(value.flags.writeable)
                self.assertTrue(np.array_equal(collar._slice(name, value), owner.initial_state.native_state.array(name)))
            source_rows = {(r['patch_id'], r['sublayer']): r for r in record['source_accounts']}
            for row in result.exterior_remainder():
                account = source_rows[(row['patch_id'], row['sublayer'])]
                for name, remainder in row['stocks'].items():
                    self.assertEqual(decode(account['source'][name]), decode(account['debit'][name])+decode(remainder))
            total = sum((decode(row['debit']['volume_m3']) for row in source_rows.values()), Q(0))
            self.assertEqual(total, sum((cell.volume_m3 for cell in collar.cell_geometries()), Q(0)))
            self.assertTrue(all(decode(row['field_error_bounds']['mass_kg']) == 0 for row in record['cell_accounts']))
            for name in ('tracer:damage', 'tracer:accumulated_strain_ii'):
                self.assertTrue(np.all(arrays[name] == 0))
            self.assertTrue(np.all(arrays['tracer:source_kappa'] > 0))
            restored = G.FullCellFunding.restore(record, arrays, *source[:2], collar, owner, budget=budget)
            self.assertEqual(restored.funding_id, result.funding_id)
            changed = result.arrays()
            changed['enthalpy_j'] = changed['enthalpy_j'].copy()
            changed['enthalpy_j'][0, 0, 0] += 1
            with self.assertRaises(V.VolumeError):
                G.FullCellFunding.restore(record, changed, *source[:2], collar, owner, budget=budget)

    def test_original_box_padding_with_missing_sources_is_not_zero_filled(self):
        with fixture(interior=False) as (source, owner, collar, budget):
            before = owner.initial_state.owner_state_id
            with self.assertRaisesRegex(V.VolumeError, 'uncovered'):
                fund(source, owner, collar, budget)
            self.assertEqual(owner.initial_state.owner_state_id, before)

    def test_malformed_huge_request_is_admitted_before_integer_conversion(self):
        request = dict(schema='atlas.full-cell-collar-funding.v1', integration_request=dict(
            max_cell_volume_width_m3=['0x'+'f'*2000, '0x1'],
            max_field_errors={k: ['0x0', '0x1'] for k in G.FIELDS}, max_leaves=1))
        budget = WorkBudget(65536)
        with self.assertRaises(MemoryLimitError):
            G.FullCellFunding.restore(request, {}, None, None, None, None, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
