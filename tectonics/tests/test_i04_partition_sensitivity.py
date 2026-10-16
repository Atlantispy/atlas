"""Local GPE trace-partition sensitivity with genuine nonlinear D2 belts.

The retained reviewer probe supplies the stepped P1 field and genuine P2/BeltTerm. Central differences change
the actual trace partition, keeping material fixed; this tests the nonlinear response independently of the
reported tangent back-solve. These are bounded source regressions, not scientific acceptance.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np

import i04_fixtures as F4
import i04_strength_fixtures as Z
from atlas_tectonics import integration_driving as D
from atlas_tectonics import integration_feedback as B
from atlas_tectonics import integration_ports as P
from atlas_tectonics import integration_properties as R
from atlas_tectonics import integration_strength as G


class BeltPartitionSensitivity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state, moving = Z.twin_case()
        cls.interval, cls.inputs = Z.interval(cls.state), Z.inputs()
        cls.network = cls.state.network
        cls.support = P.trace_support(cls.network)
        header = B._header('P2', cls.state.state_id, cls.state, cls.interval, cls.interval[2],
                           R.piece_support_id(cls.state), cls.inputs.datum, moving.moving_id)
        strength = R.strength_port(moving, cls.state, header, cls.inputs.datum, healing_law_id=G.HEALING_NONE)
        cls.term = G.BeltTerm(cls.state, cls.support, strength, cls.inputs.declaration, cls.inputs.datum, moving)

    def columns(self, field, **changes):
        original = F4.single_layer_columns(self.network, self.support, field, state_id=self.state.state_id,
                                             **changes)
        header = replace(original.header, interval=self.interval, endpoint_s=self.interval[2])
        return P.columns_port(header, original.offsets, original.thickness_m, original.reference_density_kg_m3,
                              original.alpha_per_k, original.bottom_temperature_k, original.top_temperature_k,
                              sources=original.sources)

    def balance(self, forcing, columns):
        return D.balance(self.network, forcing, support=self.support, columns_port=columns, datum=self.inputs.datum,
                         parent_state_id=self.state.state_id, interval=self.interval, belt_term=self.term)

    def test_local_sensitivity_matches_nonlinear_partition_perturbations(self):
        columns = self.columns(lambda d, side: F4.degree_one(d, side)
                               +(4000. if side == 0 else 0.)*(1+float(d[1])))
        forcing = replace(self.inputs.forcing, gamma=.01, omitted=('slab_pull', 'mantle_traction'))
        result = self.balance(forcing, columns)
        _, half_response, peak = result.partition_motion[0]
        self.assertEqual(result.partition_motion_evaluation, D.PARTITION_LOCAL)
        self.assertEqual(result.record()['partition_motion_evaluation'], D.PARTITION_LOCAL)
        self.assertEqual(peak, float(np.max(np.linalg.norm(half_response, axis=1)))*self.term.radius)

        # A symmetric +/- 0.01 trace-partition change; the existing belt-tangent central-difference gate is 1e-4.
        # The old belt-free diagnostic misses this derivative by 835%, so this test detects the actual omission.
        h, base = .01, D.TRACE_PARTITION
        with patch.object(D, 'TRACE_PARTITION', base+h):
            plus = self.balance(forcing, columns).omega_rad_s
        with patch.object(D, 'TRACE_PARTITION', base-h):
            minus = self.balance(forcing, columns).omega_rad_s
        derivative = (plus-minus)/(2*h)
        self.assertGreater(float(np.linalg.norm(derivative)), 0.)
        relative = np.linalg.norm(2*half_response-derivative)/np.linalg.norm(derivative)
        self.assertLess(float(relative), 1e-4)

    def test_an_at_rest_belt_keeps_its_zero_motion_without_claiming_a_finite_tangent(self):
        # A uniform mantle-density column has exactly zero GPE anomaly with this power-of-two thickness.
        columns = self.columns(lambda d, side: 2.**15, density=self.inputs.datum.mantle_density_kg_m3,
                               alpha=0.)
        self.assertTrue(np.array_equal(D.trace_anomaly(self.inputs.datum, columns),
                                       np.zeros(2*self.support.edges)))
        forcing = Z.forcing(0., gamma=.01, omitted=('slab_pull', 'mantle_traction'))
        result = self.balance(forcing, columns)
        self.assertTrue(np.array_equal(result.omega_rad_s, np.zeros_like(result.omega_rad_s)))
        self.assertEqual(result.partition_motion, ())
        self.assertEqual(result.partition_motion_evaluation, D.PARTITION_AT_REST)
        self.assertEqual(result.belt['dissipation_w'], 0.)


if __name__ == '__main__':
    unittest.main()
