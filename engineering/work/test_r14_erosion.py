"""Small arithmetic-only R14 checks; no soil solver or terrain acceptance."""
from fractions import Fraction as F
import hashlib
import math
from pathlib import Path
import unittest

from work.generator_upgrade_r14 import erosion
from work.generator_upgrade_r3 import terrain_transport


NATIVE = terrain_transport.landscape
EVIDENCE = 'Explicit synthetic arithmetic fixture; not Diadem parameters'


def prop(name, value, unit):
    return NATIVE.PhysicalProperty(name, value, unit, EVIDENCE, 'SYNTHETIC TEST')


def layer(name='a', mass=10, density=2, porosity=F(1, 2)):
    return NATIVE.Layer(name, mass, density, porosity, 'mobile_sediment', EVIDENCE)


def forcing():
    return {'a': NATIVE.Forcing(prop('discharge', 1., 'm3/year'),
                               prop('hydraulic_slope', 1., '1'))}


def laws(rates):
    return [NATIVE.ErosionLaw(name, 'mobile_sediment',
        prop('erosion_coefficient_at_reference_runoff', rate, '1/year'),
        prop('reference_runoff', 1., 'm/year')) for name, rate in rates.items()]


def state(layers, elapsed=F()):
    return NATIVE.LandscapeState((('a', NATIVE.Column(1, 0, tuple(layers), 'SYNTHETIC TEST')),), elapsed)


def run(initial, rates, duration, depositions=()):
    return erosion._advance(NATIVE, initial, forcing(), laws(rates), duration, depositions)


def masses(layers):
    result = {}
    for item in layers:
        result[item.material_id] = result.get(item.material_id, F())+item.mass_kg
    return result


def discrepancy(a, b):
    return sum((abs(a.get(key, F())-b.get(key, F())) for key in a.keys() | b.keys()), F())


class ErosionArithmeticTests(unittest.TestCase):
    def assert_balances(self, result):
        for row in result.receipt['global_material_balance']:
            self.assertEqual(row['residual_mass_kg'], [0, 1])
            self.assertEqual(row['residual_solid_volume_m3'], [0, 1])
        for row in result.receipt['columns']:
            accounted = sum((F(*row[key]) for key in
                ('erosion_active_years', 'zero_rate_years', 'stock_exhausted_years')), F())
            self.assertEqual(accounted, F(*result.receipt['end_year'])-F(*result.receipt['start_year']))

    def test_exact_native_parity_contacts_and_private_globals(self):
        source = state([layer('bottom', 10), layer('top', 1)])
        rates = {'top': F(1, 2), 'bottom': 2}
        previous = dict(NATIVE.advance.__globals__)
        original_source = hashlib.sha256(Path(NATIVE.__file__).read_bytes()).hexdigest()
        actual = run(source, rates, 3)
        expected = NATIVE.advance(source, forcing(), laws(rates), 3)
        self.assertEqual(actual.state, expected.state)
        self.assertEqual(actual.eroded_parcels, expected.eroded_parcels)
        self.assertEqual(actual.receipt['local_mass_representation_error_bound_kg'], '0')
        self.assertEqual(actual.receipt['schema'], erosion.SCHEMA)
        self.assertEqual(set(previous), set(NATIVE.advance.__globals__))
        self.assertTrue(all(NATIVE.advance.__globals__[key] is value for key, value in previous.items()))
        self.assertEqual(original_source, hashlib.sha256(Path(NATIVE.__file__).read_bytes()).hexdigest())
        self.assert_balances(actual)

    def test_fast_lower_material_receives_propagated_contact_time_bound(self):
        source = state([layer('fast', 10**13), layer('slow', 1, 3, F(1, 3))])
        rates = {'slow': F(1, 3), 'fast': 10**12}
        actual = run(source, rates, 2)
        expected = NATIVE.advance(source, forcing(), laws(rates), 2)
        records = actual.receipt['numerical_representation']
        self.assertEqual(len(records), 2)
        propagated = F(records[1]['contact_time_propagation_component_bound_kg'])
        local_only = F(records[0]['mass_rate_error_component_bound_kg'])
        self.assertGreater(propagated, local_only*10**10)
        bound = F(actual.receipt['local_mass_representation_error_bound_kg'])
        final_error = discrepancy(masses(actual.state.column_map['a'].layers), masses(expected.state.column_map['a'].layers))
        exported_error = discrepancy(masses(p.source_layer for p in actual.eroded_parcels),
                                     masses(p.source_layer for p in expected.eroded_parcels))
        self.assertGreater(final_error, local_only)
        self.assertLessEqual(final_error, bound)
        self.assertLessEqual(exported_error, bound)
        self.assert_balances(actual)

    def test_timed_deposition_preserves_original_reference_stock_and_replay_guard(self):
        source = state([layer('base', 10, 3, F(1, 3))])
        pulse = NATIVE.Deposition('p', 'a', F(1, 3), 0, layer('pulse', F(1, 4)), 'SYNTHETIC TEST')
        rates = {'base': F(1, 3), 'pulse': 1}
        actual = run(source, rates, 2, [pulse])
        expected = NATIVE.advance(source, forcing(), laws(rates), 2, [pulse])
        bound = F(actual.receipt['local_mass_representation_error_bound_kg'])
        self.assertLessEqual(discrepancy(masses(actual.state.column_map['a'].layers),
                                       masses(expected.state.column_map['a'].layers)), bound)
        self.assertEqual(actual.state.applied_deposition_ids, ('p',))
        self.assertEqual(len(actual.receipt['numerical_representation']), 3)
        self.assert_balances(actual)
        with self.assertRaisesRegex(ValueError, 'replay/duplicate'):
            run(actual.state, rates, 1, [pulse])

    def test_zero_rate_and_exhaustion_are_exact_and_have_no_fictitious_error(self):
        source = state([layer(mass=1)])
        stopped = run(source, {'a': 0}, 3)
        self.assertEqual(stopped.state.column_map, source.column_map)
        self.assertEqual(stopped.receipt['numerical_representation'], [])
        self.assertEqual(stopped.receipt['local_mass_representation_error_bound_kg'], '0')
        exhausted = run(source, {'a': 1}, 3)
        self.assertEqual(exhausted.state.column_map['a'].layers, ())
        self.assertEqual(exhausted.eroded_parcels[0].source_layer.mass_kg, 1)
        self.assert_balances(stopped)
        self.assert_balances(exhausted)

    def test_contact_branch_change_is_rejected_not_clipped(self):
        source = state([layer(mass=1, density=3, porosity=F(1, 3))])
        # Original 2/3 kg/year reaches the contact exactly; its represented
        # mass rate would leave a positive residue. Neither branch is hidden.
        with self.assertRaisesRegex(ValueError, 'changes a contact branch'):
            run(source, {'a': F(1, 3)}, F(3, 2))
        self.assertEqual(source.column_map['a'].mass_kg, 1)

    def test_rounded_partial_cannot_destroy_retained_or_removed_positive_branch(self):
        source = state([layer(mass=1)])
        with self.assertRaisesRegex(ValueError, 'crosses a contact'):
            run(source, {'a': 1}, 1-F(1, 2**55))
        with self.assertRaisesRegex(ValueError, 'positive branch lost'):
            run(source, {'a': 1}, F(1, 2**1100))
        with self.assertRaisesRegex(ValueError, 'positive branch lost'):
            run(source, {'a': F(1, 2**1100)}, 1)

    def test_persistent_and_transient_bounds_stay_explicit(self):
        with self.assertRaisesRegex(ValueError, 'duration exceeds bounded exact-arithmetic resources'):
            run(state([layer()]), {'a': 1}, F(1, 2**8192))
        with self.assertRaisesRegex(ValueError, 'scratch arithmetic budget'):
            erosion._scratch(F(1, 2**erosion.SCRATCH_BITS))
        value = F(1, 2**9000)
        reference = erosion._reference(value)
        self.assertEqual(reference['representation'], 'BOUNDED_EXACT_SCRATCH_REFERENCE_DIGEST')
        self.assertEqual(len(reference['sha256']), 64)
        self.assertGreaterEqual(erosion._upper(value), value)

    def test_reconciled_geometry_sequence_reproduces_predecessor_failure_only(self):
        # Rebuild precisely the R14 seam on EVERY update: authoritative H is
        # binary64 while native phi is reconstructed from the exact dry mass.
        # A fixed-porosity loop would not reproduce the old denominator growth.
        density, physical_phi = F(2500), F(.37)
        initial_mass = F(2500*(1-.37)*.125)
        dt, coefficient, steps = F(1, 100), F(1, 1000), 210

        def sequence(successor):
            mass, clock, exported, bounds = initial_mass, F(), F(), F()
            for index in range(steps):
                try:
                    height = F(float(mass/density/(1-physical_phi)))
                    phi = 1-mass/(density*height)
                    source = state([layer(mass=mass, density=density, porosity=phi)], clock)
                    result = (run(source, {'a': coefficient}, dt) if successor else
                              NATIVE.advance(source, forcing(), laws({'a': coefficient}), dt))
                except ValueError as error:
                    return index, str(error), mass, exported, bounds
                self.assert_balances(result)
                exported += sum((p.source_layer.mass_kg for p in result.eroded_parcels), F())
                mass = result.state.column_map['a'].mass_kg
                clock = result.state.elapsed_years
                self.assertEqual(initial_mass, mass+exported)
                if successor:
                    bounds += F(result.receipt['local_mass_representation_error_bound_kg'])
                    self.assertLessEqual(max(mass.numerator.bit_length(), mass.denominator.bit_length()), 8192)
            return steps, '', mass, exported, bounds

        old = sequence(False)
        self.assertLess(old[0], steps)
        self.assertIn('bounded exact-arithmetic resources', old[1])
        new = sequence(True)
        self.assertEqual(new[:2], (steps, ''))
        self.assertEqual(initial_mass, new[2]+new[3])
        self.assertLess(float(new[4]), 1e-10)

    def test_represented_fixed_height_repacking_refines_to_explicit_reference(self):
        # This separate synthetic repacking case holds H=1 and reconstructs
        # phi from M at each step: dM/dt=-K*M/H has an independent exponential
        # oracle. It tests ordinary first-order convergence, not regional law.
        def integrate(count):
            mass = F(1)
            for index in range(count):
                source = state([layer(mass=mass, density=2, porosity=1-mass/2)], F(index, count))
                result = run(source, {'a': F(1, 4)}, F(1, count))
                self.assert_balances(result)
                mass = result.state.column_map['a'].mass_kg
            return abs(float(mass)-math.exp(-.25))
        errors = [integrate(n) for n in (4, 8, 16)]
        self.assertGreater(errors[0]/errors[1], 1.9)
        self.assertGreater(errors[1]/errors[2], 1.9)


if __name__ == '__main__':
    unittest.main()
