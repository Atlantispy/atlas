"""Narrow donor-stage and full-cell collar controls; no moving-globe claim.

Before execution: ordinary versus extracted source/transport/heat/endpoint
arrays and IDs must be identical. The collar preserves every original native
face sample exactly and refuses a different rigid normal field. A physically
funded two-material grid carries a derived closed Q2 circulation, sources heat
only inside, conducts once across the shared grid and restores bitwise. Existing
native flow, inventory and heat gates remain the acceptance criteria.
SPDX-License-Identifier: AGPL-3.0-only
"""
import gc
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

import test_regional_evolution3d as E
import test_integration_collar_geometry as G
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.regional_collar3d import RigidCollarMotion
from atlas_tectonics.regional_execution3d import SIDES
from atlas_tectonics.resources import WorkBudget


def native_driving(velocity=0., body=0., heat=0.):
    return dict(velocity_m_s=velocity, dynamic_traction_pa={s: 0. for s in SIDES},
        gravity_m_s2=(0., 0., 0.), additional_body_force_n_m3=body,
        driving_source='test:explicit manufactured driving', heat_source_w_m3=heat,
        heat_source='test:explicit interior-only external source')


class RegionalCollarTests(unittest.TestCase):
    def test_extracted_donor_stage_matches_ordinary_advance_bitwise(self):
        budget = WorkBudget(256 << 20)
        with threadpool_limits(1), E.prepare(heating=True, mechanics_method='direct', budget=budget) as plan:
            state = E.initial(plan, histories={'formation': 7.})
            xyz = np.indices((5, 5, 5)).reshape(3, -1).T/4
            velocity = np.zeros_like(xyz); velocity[:, 0] = xyz[:, 1]
            driving = native_driving(velocity, heat=.125)
            stocks = E.full_stocks(plan, history=7.)
            boundaries = {s: ('flux', 0.) for s in SIDES}
            ordinary = plan.advance(state, .001, boundary_stocks=stocks,
                heat_boundaries=boundaries, **driving)
            stage = plan.source_stage(state, .001, **driving)
            fields = {k: stage.inventory.array(k) for k in stage.inventory.array_names}
            transported = plan._transport.advect(fields['component_mass_kg'], fields['enthalpy_j'],
                {k[7:]: a for k, a in fields.items() if k.startswith('tracer:')},
                stage.flow, .001, boundary_stocks=stocks)
            heat = plan._heat.advance(transported.array('enthalpy_j'), .001, boundaries,
                                      0., source_id=driving['heat_source'])
            output = {k: transported.array(k) for k in fields}
            output['enthalpy_j'] = heat.array('enthalpy_j')
            endpoint = plan.endpoint_from_sources(stage, output,
                transport_id=transported.result_id, heat_id=heat.result_id)
            self.assertEqual(ordinary.state.result_id, endpoint.state.result_id)
            self.assertEqual(ordinary.mechanics.result_id, endpoint.mechanics.result_id)
            self.assertEqual(ordinary.source_audit.result_id, stage.source_audit.result_id)
            self.assertEqual(ordinary.transport.result_id, transported.result_id)
            self.assertEqual(ordinary.heat.result_id, heat.result_id)
            for key in state.array_names:
                np.testing.assert_array_equal(ordinary.state.array(key), endpoint.state.array(key))
        self.assertEqual(budget.reserved_bytes, 0)

    def test_physical_funding_exact_rigid_streams_and_one_full_grid_step(self):
        with threadpool_limits(1), G.fixture() as (source, owner, collar, budget):
            funding = G.fund(source, owner, collar, budget)
            state = collar.initial_state_from_funding(funding, owner)
            native = collar._native
            motion = RigidCollarMotion((.01, 0., 0.), 'test:one actual global rigid omega')
            stage = native.source_stage(state.native_state, .001,
                **native_driving(collar.interior_velocity(motion)))
            flow = collar._flow(stage, motion, None)
            self.assertGreater(max(np.max(np.abs(flow.array('normal_'+c+'_m_s'))) for c in 'xyz'), 0.)
            for axis, label in enumerate('xyz'):
                at = list(collar._inner)
                at[axis] = slice(collar._lower[axis], collar._lower[axis]+native.cells[axis]+1)
                for prefix in ('raw_normal_', 'normal_'):
                    np.testing.assert_array_equal(flow.array(prefix+label+'_m_s')[tuple(at)],
                                                  stage.flow.array(prefix+label+'_m_s'))
            with self.assertRaisesRegex(TectonicsError, 'no flux repair'):
                collar._flow(stage, RigidCollarMotion((.02, 0., 0.), 'test:incompatible omega'), None)
            # psi=a*x(1-x)*z(1-z): exact Q2 incompressible velocity; all six
            # wall normals vanish. f=-eta*laplacian(u), eta=1, is supplied at
            # the actual 3x3x3 Gauss points. No velocity projection is invented.
            a = .01
            xyz = np.indices((5, 5, 5)).reshape(3, -1).T/4
            x, _, z = xyz.T
            velocity = np.stack((a*x*(1-x)*(1-2*z), np.zeros(len(x)),
                                 -a*(1-2*x)*z*(1-z)), axis=-1)
            g = np.polynomial.legendre.leggauss(3)[0]
            q = np.stack(np.meshgrid(g, g, g, indexing='ij'), axis=-1).reshape(-1, 3)
            points = (np.indices((2, 2, 2)).reshape(3, -1).T[:, None, :]+(q+1)/2)/2
            body = np.zeros_like(points)
            body[..., 0] = 2*a*(1-2*points[..., 2])
            body[..., 2] = -2*a*(1-2*points[..., 0])
            names = tuple(k[7:] for k in state.native_state.array_names if k.startswith('tracer:'))
            stocks = collar._transport.empty_boundary_stocks(len(native._composition), names)
            driving = native_driving(velocity, body, .125)
            result = collar.advance(state, .001,
                rigid_motion=RigidCollarMotion((0., 0., 0.), 'test:stationary rigid exterior'),
                boundary_stocks=stocks, heat_boundaries={s: ('flux', 0.) for s in SIDES}, **driving)
            self.assertGreater(np.max(np.abs(result.flow.array('normal_x_m_s'))), 0.)
            self.assertEqual(result.heat.descriptor()['source_energy_j'], 0.)
            audit = result.source_stage.source_audit
            np.testing.assert_array_equal(audit.array('external_heat_source_w_m3'), np.full((2, 2, 2), .125))
            self.assertFalse(np.array_equal(state.fields.array('enthalpy_j'), result.state.fields.array('enthalpy_j')))
            for key in state.native_state.array_names:
                np.testing.assert_array_equal(collar._slice(key, result.state.fields.array(key)),
                                              result.state.native_state.array(key))
            restored = collar.restore(result.state.record(), result.state.arrays())
            self.assertEqual(restored.result_id, result.state.result_id)
            self.assertEqual(state.result_id, collar.initial_state_from_funding(funding, owner).result_id)
            del funding
            # A retained collar stage holds its bytes while its advance
            # result is alive; release the results before asking for zero.
            del result, restored, audit, stocks, driving, state
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
