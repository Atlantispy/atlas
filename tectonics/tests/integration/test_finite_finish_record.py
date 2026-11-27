"""The finished finite-stock record without the issue/decode round trip (wave 5-6 unit T-2).

`finish_record` must give exactly the record the issued successor state gives: same fields, and a state_id equal to
the hash of the bytes the issue step writes. Fixture: the one-cell analytical case of
tools/e4_collar_finite_adoption.py.
"""
from fractions import Fraction
import unittest

from threadpoolctl import threadpool_limits

from atlas_tectonics.integration.coupling.spatial_reservoir import PreparedFiniteStocks
from atlas_tectonics.integration.coupling.spatial_transport import PreparedSpatialTransport
from atlas_tectonics.integration.heat.mimetic_heat import _enc
from atlas_tectonics.integration.resources import WorkBudget

NAMES = ('component_mass_kg:0', 'component_mass_kg:1', 'enthalpy_j', 'tracer:damage', 'tracer:accumulated_strain_ii')
NONNEGATIVE = tuple(name for name in NAMES if name != 'enthalpy_j')


class FinishRecordTests(unittest.TestCase):
    def test_finish_record_equals_the_issued_successor_record(self):
        graph = dict(cells=[dict(cell_id='physical', kind='exterior', start_volume_m3=_enc(1), end_volume_m3=_enc(2))],
                     transfers=[], source='independently declared analytical one-cell fixture',
                     physical_measure_receipts=[{'source_sha256': 'a' * 64}])
        stock = dict(stock_id='ridge', kind='source', lineage=dict(source='declared analytical stock:ridge'),
                     volume_m3=_enc(1), exact=dict(zip(NAMES, map(_enc, (3, 1, -2, 0, 0)), strict=True)))
        donor = {name: (amount,) for name, amount in
                 zip(NAMES, (Fraction(3, 2), Fraction(1, 2), Fraction(3), Fraction(0), Fraction(0)), strict=True)}
        exchange = dict(stock_id='ridge', physical_cell_id='physical', direction='supply', face_id='ridge:wall',
                        volume_m3=_enc(1), physical_certificate_id='analytic unit wall')
        budget = WorkBudget(64 << 20)
        with PreparedFiniteStocks('finish registry', [stock], field_names=NAMES, nonnegative_fields=NONNEGATIVE,
                                  budget=budget) as owner:
            proposal = owner.prepare(owner.initial(), graph, donor, [exchange], source_stage_id='source',
                                     transport_parent_id='spatial-parent')
            augmented, stocks = proposal._transport_inputs()
            with threadpool_limits(1), PreparedSpatialTransport(augmented, budget=budget) as operator:
                result = operator.advance(stocks, state_id='spatial-parent', source_stage_id='source',
                                          max_projection_errors=dict.fromkeys(NAMES, Fraction(1, 10**11)),
                                          nonnegative_fields=NONNEGATIVE)
            record = owner.finish_record(proposal, result)
            issued = owner._state({k: v for k, v in record.items() if k != 'state_id'}).record()
            self.assertEqual(record, issued)
            self.assertEqual(record['intervals'], 1)
            self.assertEqual(record['parent_state_id'], owner.initial().state_id)


if __name__ == '__main__':
    unittest.main()
