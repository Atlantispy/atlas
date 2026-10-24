"""Bind the native reference-pressure partition across the actual plate solve.

These are discrete partition/identity checks, not calibration of a global
reference pressure from an independently supplied Q1 field.
SPDX-License-Identifier: AGPL-3.0-only
"""
import json
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

import i03_fixtures as F
import i04_fixtures as X
from test_i04_regional_driving import mapping
from atlas_tectonics import integration_driving as D
from atlas_tectonics import integration_regional_driving as R
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.regional_execution import RegionalMechanicsScales, RegionalMechanicalSnapshot
from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES
from atlas_tectonics.resources import WorkBudget


def prepare(budget, value=None, partition='incremental'):
    args = {} if value is None else dict(pressure_reference_pa=np.full(27, value),
        pressure_reference_source='test:explicit discrete reference', pressure_load_partition=partition)
    return PreparedRegionalStokes3D((2, 2, 2), (1., 1., 1.), 1.,
        {s: ('velocity',)*3 if s[0] == 'x' else ('traction',)*3 for s in SIDES},
        scales=RegionalMechanicsScales(1., 1.), reference_viscosity_pa_s=1.,
        frame_id='test:coupled-box', vertical_datum='explicit embedded box',
        material_source='test:fixed-or-thermal-source', method='direct', budget=budget, **args)


class PressurePartition(unittest.TestCase):
    def test_incremental_coupling_preserves_rates_and_rejects_changed_reference(self):
        budget = WorkBudget(256*1024*1024)
        network = F.three_plates(sphere=F.sphere(radius=10.), time_s=0.)
        forcing = X.authored_forcing(network,
            {'A': (1., -.4, .2), 'B': (.8, 1.1, .5), 'C': (-.3, -.6, -.2)}, drag=.001)
        exterior_plan = D.prepare(network, forcing)
        exterior = D.balance(network, forcing, prepared=exterior_plan,
                             parent_state_id='0'*64, interval=(0, 1, 0., 1.))
        request = dict(parent_state_id='test:native-parent', time_s=0., epoch_id=network.epoch_id,
                       force_source='test:incremental zero force', boundary_source='test:physical walls')
        with threadpool_limits(limits=1), prepare(budget) as plain, prepare(budget, 5.) as physical:
            footprint, args, _ = mapping(network, plain)
            with R.PlateBoundaryLift(network, plain, footprint, 'boundary-m00', **args, budget=budget) as base_lift, \
                    R.PlateBoundaryLift(network, physical, footprint, 'boundary-m00', **args, budget=budget) as lift:
                self.assertNotIn('pressure_reference', base_lift.descriptor())
                self.assertEqual(lift.descriptor()['pressure_reference'], physical.descriptor()['pressure_reference'])
                with R.PreparedRegionalDriving(network, forcing, exterior, exterior_plan, base_lift, budget=budget) as base, \
                        R.PreparedRegionalDriving(network, forcing, exterior, exterior_plan, lift, budget=budget) as driver:
                    old = base.solve(plain, **request)
                    new = driver.solve(physical, **request)
                    np.testing.assert_allclose(new.exchange.array('omega_rad_s'), old.exchange.array('omega_rad_s'),
                                               rtol=R.ALGEBRA, atol=0.)
                    np.testing.assert_allclose(new.mechanical.array('physical_pressure_pa'),
                        old.mechanical.array('physical_pressure_pa')+5., rtol=R.ALGEBRA, atol=R.ALGEBRA)
                    self.assertNotEqual(base.driving_id, driver.driving_id)
                    with prepare(budget, 6.) as changed:
                        before = changed.statistics()['solves']
                        with self.assertRaisesRegex(TectonicsError, 'pressure reference'):
                            driver.solve(changed, **request)
                        self.assertEqual(changed.statistics()['solves'], before)
                    with prepare(budget, 5., 'full') as changed_partition:
                        with self.assertRaisesRegex(TectonicsError, 'pressure reference'):
                            driver.solve(changed_partition, **request)
                    # Import/restore cannot relabel a full or differently split
                    # reaction as the increment admitted by this driver.
                    record = json.loads(json.dumps(new.mechanical.descriptor()))
                    del record['plan']['pressure_reference']
                    forged = RegionalMechanicalSnapshot(record,
                        {key: new.mechanical.array(key) for key in new.mechanical.array_names})
                    with self.assertRaisesRegex(TectonicsError, 'pressure reference'):
                        driver.reconstruct(forged, parent_state_id=request['parent_state_id'], time_s=0.)
        self.assertEqual(budget.reserved_bytes, 0)
