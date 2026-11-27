"""P0: the I04/I05 port record's coded rows (P1 columns on the trace support, P5 motion) and the common header."""
import copy
import unittest

import numpy as np

import tests.fixtures.i04_fixtures as X
from atlas_tectonics.integration.coupling import driving as D
from atlas_tectonics.integration import ports as P
from atlas_tectonics._validation import TectonicsError


class HeaderRules(unittest.TestCase):
    def setUp(self):
        self.network = X.hemispheres(32)
        self.support = P.trace_support(self.network)
        self.header = X.header('P1', self.network, self.support)

    def fields(self, **changes):
        values = {name: getattr(self.header, name) for name in self.header.__dataclass_fields__}
        values.update(changes)
        return values

    def test_every_identity_is_required(self):
        with self.assertRaises(P.PortRefused) as caught:
            P.Header(**self.fields(frame_id=' '))
        self.assertEqual((caught.exception.code, caught.exception.detail), (P.MISSING_VALUE, 'frame'))
        # A value whose producer used no datum carries none; P1 always needs one.
        self.assertIsNone(P.Header(**self.fields(datum_id=None)).datum_id)

    def test_refusals_name_their_field_and_numpy_seconds_are_accepted(self):
        header = P.Header(**self.fields(interval=(0, 0, np.float64(0.), np.float64(0.)), endpoint_s=np.float64(0.)))
        self.assertEqual(header.endpoint_s, 0.)

    def test_interval_and_endpoint(self):
        header = P.Header(**self.fields(interval=(0, 1, 0, 1.), endpoint_s=0))
        self.assertEqual(header.interval, (0, 1, 0., 1.))

    def test_refusal_detail(self):
        refusal = P.PortRefused('wrapped', P.UNSUPPORTED, detail='REFUSED_CORE_PLACEMENT_ABSENT')
        self.assertEqual(refusal.detail, 'REFUSED_CORE_PLACEMENT_ABSENT')


class TraceSupportRules(unittest.TestCase):
    def test_points_edges_and_identity(self):
        network = X.hemispheres(32)
        support = P.trace_support(network)
        self.assertEqual(support.edges, 32)
        self.assertEqual(support.network_id, network.network_id)
        self.assertEqual(len(support.directions()), 64)
        self.assertEqual([support.point_plate(i) for i in range(2)], ['north', 'south'])
        middle = support.midpoint
        self.assertTrue(np.allclose(np.linalg.norm(middle, axis=1), 1.))
        # The left (north) plate's outward conormal at the equator points south.
        self.assertTrue(np.all(support.nu_left[:, 2] < 0))
        self.assertFalse(support.midpoint.flags.writeable)
        self.assertEqual(P.trace_support(network).support_id, support.support_id)
        self.assertNotEqual(P.trace_support(X.hemispheres(64)).support_id, support.support_id)
        self.assertIs(copy.deepcopy(support), support)
        with self.assertRaises(TypeError):
            P.TraceSupport()


class ColumnRules(unittest.TestCase):
    def setUp(self):
        self.network = X.hemispheres(32)
        self.support = P.trace_support(self.network)
        self.header = X.header('P1', self.network, self.support)
        self.n = 2*self.support.edges

    def port(self, **changes):
        n = self.n
        values = dict(offsets=np.arange(n+1), thickness_m=np.full(n, 3e4), reference_density_kg_m3=np.full(n, 2800.),
                      alpha_per_k=np.zeros(n), bottom_temperature_k=np.full(n, 1000.),
                      top_temperature_k=np.full(n, 1000.), sources=tuple('authored' for _ in range(n)))
        values.update(changes)
        return P.columns_port(self.header, **values)

    def test_values_are_owned_and_frozen(self):
        thickness = np.full(self.n, 3e4)
        port = self.port(thickness_m=thickness)
        thickness[:] = 1.
        self.assertEqual(float(port.layers(0)[0][0]), 3e4)
        self.assertFalse(port.thickness_m.flags.writeable)
        self.assertEqual(port.points, self.n)

    def test_missing_and_unknown_values(self):
        unknown = np.zeros(self.n, bool)
        unknown[0] = True
        counts = np.where(unknown, 0, 1)
        offsets = np.r_[0, np.cumsum(counts)]
        m = int(offsets[-1])
        port = self.port(offsets=offsets, thickness_m=np.full(m, 3e4), reference_density_kg_m3=np.full(m, 2800.),
                         alpha_per_k=np.zeros(m), bottom_temperature_k=np.full(m, 1000.),
                         top_temperature_k=np.full(m, 1000.), unknown=unknown)
        with self.assertRaises(P.PortRefused) as caught:
            port.layers(0)
        self.assertEqual(caught.exception.code, P.UNRESOLVED_COLUMN)
        port.layers(1)

    def test_water_only_from_a_named_source(self):
        with self.assertRaises(P.PortRefused):
            self.port(water_source='labelled test input')
        port = self.port(water_depth_m=np.full(self.n, 10.), water_source='test: labelled input')
        self.assertEqual(port.water_source, 'test: labelled input')

    def test_identity_changes_with_content(self):
        self.assertEqual(self.port().port_id, self.port().port_id)
        self.assertNotEqual(self.port().port_id, self.port(thickness_m=np.full(self.n, 3.1e4)).port_id)


class MotionRules(unittest.TestCase):
    def test_p5_is_issued_from_a_balance_only(self):
        network = X.hemispheres(32)
        state = X.state(network)
        interval = (0, 1, state.time_s, state.time_s+1e13)
        forcing = X.authored_forcing(network, {'north': (1e24, 0., 0.)})
        result = D.balance(network, forcing, parent_state_id=state.state_id, interval=interval)
        header = P.Header('P5', state.state_id, interval, state.time_s, network.network_id,
                          P.plate_support_id(network.network_id, network.plate_ids), None, forcing.forcing_id,
                          network.sphere.frame_id, 'I04', D.ROUTE)
        motion = D.motion_port(result, header)
        self.assertTrue(np.array_equal(motion.omega('north'), result.omega('north')))
        self.assertEqual(motion.balance_id, result.balance_id)
        self.assertIn('explicit', motion.evaluation)
        # No public route forges a P5 value with another omega under a real balance identity.
        self.assertFalse(hasattr(P, 'plate_motion'))
        with self.assertRaises(TypeError):
            P.PlateMotion()


if __name__ == '__main__':
    unittest.main()
