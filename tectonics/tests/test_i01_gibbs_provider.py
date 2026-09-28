"""Independent analytical common-Gamma checks; not G25 calibration.

SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError, replace
import importlib.util
import math
from pathlib import Path
import sys
import threading
import time
import unittest


PATH = Path(__file__).resolve().parents[1]/'tools/i01_gibbs_provider.py'
SPEC = importlib.util.spec_from_file_location('i01_gibbs_provider_tested', PATH)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


class BinaryIdeal:
    """Exact binary solid/liquid common tangent, with independent caloric data.

    Endmember h=h0+cp*(T-Tr)+v*(P-Pr), s=s0+cp*ln(T/Tr).
    Both phases have ideal molar mixing. Liquid adds latent h and s.
    At the reference P and 1500 K, K=(2,1/2), xs=(1/3,2/3),
    xl=(2/3,1/3); a bulk x_A=1/2 contains equal phase mole amounts.
    """
    identity = 'analytical-binary-full-gibbs-v1'
    component_ids = ('a', 'b')
    molar_mass_kg = (.04, .10)
    R, tr, pr, tc = 8.31446261815324, 1000., 1e9, 1500.
    h0, s0, cp = (-100000., -160000.), (20., 30.), (55., 85.)
    latent = (30000., 45000.)
    vs, vl = (1.1e-5, 2.2e-5), (1.7e-5, 2.7e-5)

    def __init__(self, transform=None, cancel_on_solve=None):
        self.requests = []
        self.transform = transform
        self.cancel_on_solve = cancel_on_solve

    def validate(self, p, t, bulk):
        if not (0 < p < 3e9 and 1200 < t < 1800):
            raise ValueError('outside analytical fixture domain')
        if len(bulk) != 2 or min(bulk) < 0 or abs(sum(bulk)-1.) > 1e-12:
            raise ValueError('invalid analytical fixture composition')

    def endmember_hsv(self, key, p, t):
        liquid = key == 'liq'
        vols = self.vl if liquid else self.vs
        h, s = [], []
        for i, k in enumerate((2., .5)):
            ds = self.latent[i]/self.tc+self.R*math.log(k)
            h.append(self.h0[i]+self.cp[i]*(t-self.tr)+vols[i]*(p-self.pr)
                     +(self.latent[i] if liquid else 0.))
            s.append(self.s0[i]+self.cp[i]*math.log(t/self.tr)
                     +(ds if liquid else 0.))
        return tuple(h), tuple(s), vols

    def phases(self, p, t, bulk):
        hs, ss, _ = self.endmember_hsv('solid', p, t)
        hl, sl, _ = self.endmember_hsv('liq', p, t)
        k = tuple(math.exp(-((b-t*d)-(a-t*c))/(self.R*t))
                  for a, b, c, d in zip(hs, hl, ss, sl))
        xs = (1.-k[1])/(k[0]-k[1])
        xl = k[0]*xs
        if 0 < xs < bulk[0] < xl < 1:
            f = (bulk[0]-xs)/(xl-xs)
            return (('solid', (xs, 1-xs), 1-f), ('liq', (xl, 1-xl), f))
        key = 'solid' if bulk[0] <= xs else 'liq'
        return ((key, bulk, 1.),)

    def molar_g(self, key, p, t, composition):
        h, s, _ = self.endmember_hsv(key, p, t)
        return sum(x*(hi-t*si+self.R*t*math.log(x))
                   for x, hi, si in zip(composition, h, s) if x)

    def expected_hsv(self, key, p, t, moles):
        # Expected properties use explicit thermodynamic primitives, never Gamma
        # differences, production dot(), or the adapter's returned H/S/V.
        h, s, v = self.endmember_hsv(key, p, t)
        amount = sum(moles)
        return (sum(n*hi for n, hi in zip(moles, h)),
                sum(n*si for n, si in zip(moles, s))
                -self.R*sum(n*math.log(n/amount) for n in moles if n),
                sum(n*vi for n, vi in zip(moles, v)))

    def expected_total_h(self, mass, p, t):
        n = tuple(a/w for a, w in zip(mass, self.molar_mass_kg))
        total = sum(n)
        bulk = tuple(a/total for a in n)
        return sum(self.expected_hsv(key, p, t, tuple(total*f*x for x in comp))[0]
                   for key, comp, f in self.phases(p, t, bulk))

    def solve(self, p, t, bulk, *, cancel=None, deadline=None):
        self.requests.append((p, t, bulk))
        phases = self.phases(p, t, bulk)
        key, comp, _ = phases[0]
        h, s, _ = self.endmember_hsv(key, p, t)
        mu = tuple(hi-t*si+self.R*t*math.log(x) if x else float('nan')
                   for x, hi, si in zip(comp, h, s))
        point = m.Point(self.identity, p, t, bulk, mu,
                        sum(x*u for x, u in zip(bulk, mu) if x),
                        tuple(m.PhasePoint(key, tuple(f*x for x in comp), (comp[0],))
                              for key, comp, f in phases))
        if self.cancel_on_solve is not None:
            self.cancel_on_solve.set()
        return self.transform(point) if self.transform else point


class RestrictedFormula:
    """Single stoichiometric phase; one nullspace and one absent component."""
    identity = 'analytical-restricted-formula-v1'
    component_ids = ('a', 'b', 'absent')
    molar_mass_kg = (.04, .10, .06)

    def __init__(self, gauge=True):
        self.gauge = gauge

    def validate(self, p, t, bulk):
        if bulk != (.25, .75, 0.):
            raise ValueError('fixed formula required')

    def solve(self, p, t, bulk, **kwargs):
        h = -120000.+70.*(t-1000.)+2e-5*(p-1e9)
        s = 25.+70.*math.log(t/1000.)
        g = h-t*s
        q = 37.*(t-1500.)**2+1e-3*(p-1e9) if self.gauge else 0.
        return m.Point(self.identity, p, t, bulk, (g+3*q, g-q, float('nan')),
                       g, (m.PhasePoint('solid', bulk),))


class GibbsProviderTests(unittest.TestCase):
    def setUp(self):
        self.backend = BinaryIdeal()
        # The expected-value assertions and receiver request below need tighter
        # derivatives than the production default's 1 K numerical stencil.
        self.controls = replace(m.Controls(), temperature_step_k=.1,
                                pressure_step_pa=1e5)
        self.provider = m.Provider(self.backend, self.controls)
        self.mass, self.p, self.t = (2., 5.), 1e9, 1500.

    def branch(self, mass=None, bounds=(1490., 1510.), *, provider=None):
        return (provider or self.provider).declare_thermal_branch(
            self.mass if mass is None else mass, self.p, bounds,
            phase_keys=('solid', 'liq'),
            support='Analytical BinaryIdeal two-phase common-tangent interval; '
                    'declared test assumption, not inferred from inversion samples')

    def test_independent_binary_phase_mass_enthalpy_entropy_volume(self):
        state = self.provider.equilibrate(self.mass, self.p, self.t)
        expected = {'solid': (50./3, 100./3), 'liq': (100./3, 50./3)}
        totals = [0., 0., 0.]
        for phase in state.phases:
            n = expected[phase.key]
            for actual, ni, molar_mass in zip(phase.component_mass_kg, n,
                                             self.backend.molar_mass_kg):
                self.assertAlmostEqual(actual, ni*molar_mass, delta=1e-12)
            h, s, v = self.backend.expected_hsv(phase.key, self.p, self.t, n)
            self.assertAlmostEqual(phase.enthalpy_j, h, delta=.25)
            self.assertAlmostEqual(phase.entropy_j_k, s, delta=2e-4)
            self.assertAlmostEqual(phase.volume_m3, v, delta=1e-10)
            totals = [a+b for a, b in zip(totals, (h, s, v))]
        for actual, expected, tolerance in zip(
                (state.enthalpy_j, state.entropy_j_k, state.volume_m3),
                totals, (.5, 4e-4, 2e-10)):
            self.assertAlmostEqual(actual, expected, delta=tolerance)
        self.assertLess(max(map(abs, state.component_residual_kg)), 1e-12)

    def test_moving_phase_gibbs_derivative_is_not_phase_entropy(self):
        dt = .001
        values = []
        comps = []
        for t in (self.t-dt, self.t+dt):
            key, comp, _ = self.backend.phases(self.p, t, (.5, .5))[0]
            comps.append(comp)
            values.append(self.backend.molar_g(key, self.p, t, comp))
        self.assertNotEqual(comps[0], comps[1])
        wrong_entropy = -50.*(values[1]-values[0])/(2*dt)
        correct_entropy = self.backend.expected_hsv(
            'solid', self.p, self.t, (50./3, 100./3))[1]
        self.assertGreater(abs(wrong_entropy-correct_entropy), 100.)
        solid = self.provider.equilibrate(self.mass, self.p, self.t).phases[0]
        self.assertAlmostEqual(solid.entropy_j_k, correct_entropy, delta=2e-4)

    def test_restricted_formula_gauge_and_absent_nan_potential(self):
        states = [m.Provider(RestrictedFormula(gauge), self.controls).equilibrate(
                  (1., 7.5, 0.), self.p, self.t) for gauge in (False, True)]
        h, s, v = 100.*(-120000.+70.*500.), 100.*(25.+70.*math.log(1.5)), .002
        for state in states:
            self.assertEqual(state.phases[0].component_mass_kg, (1., 7.5, 0.))
            self.assertAlmostEqual(state.enthalpy_j, h, delta=.1)
            self.assertAlmostEqual(state.entropy_j_k, s, delta=1e-4)
            self.assertAlmostEqual(state.volume_m3, v, delta=1e-10)
        self.assertAlmostEqual(states[0].enthalpy_j, states[1].enthalpy_j, delta=1e-5)

    def test_phase_appearance_and_order_branch_refuse(self):
        def appearance(point):
            if point.temperature_k < self.t:
                return replace(point, phases=(m.PhasePoint('solid', point.bulk),))
            return point

        def order_jump(point):
            coordinate = 0. if point.temperature_k == self.t else .2
            return replace(point, phases=tuple(replace(s, coordinates=(coordinate,))
                                               for s in point.phases))
        for transform, message in ((appearance, 'phase boundary'),
                                   (order_jump, 'composition/order branch')):
            with self.subTest(message=message):
                provider = m.Provider(BinaryIdeal(transform))
                with self.assertRaisesRegex(ValueError, message):
                    provider.equilibrate(self.mass, self.p, self.t)

    def test_nested_derivative_noise_discrepancy_refuses(self):
        def noisy(point):
            noise = math.sin(math.pi*(point.temperature_k-self.t))
            return replace(point, mu_j_mol=tuple(x+noise for x in point.mu_j_mol),
                           gibbs_j_mol=point.gibbs_j_mol+noise)
        with self.assertRaisesRegex(ValueError, 'thermodynamic derivative unresolved'):
            m.Provider(BinaryIdeal(noisy)).equilibrate(self.mass, self.p, self.t)

    def test_empty_and_invalid_inventory_do_not_call_backend(self):
        empty = self.provider.equilibrate((0., 0.), self.p, self.t)
        self.assertIsNone(empty.temperature_k)
        self.assertEqual((empty.enthalpy_j, empty.entropy_j_k, empty.volume_m3),
                         (0., 0., 0.))
        self.assertEqual(empty.phases, ())
        self.assertEqual(empty.provider_id, self.backend.identity)
        for mass in ((-1., 2.), (float('nan'), 2.), (1.,), (True, 2.)):
            with self.subTest(mass=mass), self.assertRaises(ValueError):
                self.provider.equilibrate(mass, self.p, self.t)
        self.assertEqual(self.backend.requests, [])

    def test_kg_scaling_cache_hits_bulk_invalidation_and_bounded_eviction(self):
        a = self.provider.equilibrate(self.mass, self.p, self.t)
        calls = self.provider.calls
        self.assertEqual(calls, 9)
        self.assertEqual(self.provider.equilibrate(self.mass, self.p, self.t), a)
        b = self.provider.equilibrate(tuple(4*x for x in self.mass), self.p, self.t)
        self.assertEqual(self.provider.calls, calls)
        self.assertEqual(self.provider.hits, 18)
        for attr in ('enthalpy_j', 'entropy_j_k', 'volume_m3'):
            self.assertAlmostEqual(getattr(b, attr), 4*getattr(a, attr), delta=1e-7)
        self.provider.equilibrate((3., 5.), self.p, self.t)
        self.assertEqual(self.provider.calls, calls+9)
        bounded = m.Provider(BinaryIdeal(), replace(m.Controls(), cache_points=5))
        bounded.equilibrate(self.mass, self.p, self.t)
        self.assertEqual(len(bounded.cache), 5)
        bounded.point(self.p, self.t, (.5, .5))
        self.assertEqual(bounded.calls, 10)
        self.assertEqual(len(bounded.cache), 5)

    def test_finite_extraction_depletion_and_immutable_source(self):
        state = self.provider.equilibrate(self.mass, self.p, self.t)
        left, parcel = self.provider.extract(state, .4)
        n = (40./3, 20./3)
        expected_h = self.backend.expected_hsv('liq', self.p, self.t, n)[0]
        self.assertAlmostEqual(parcel.enthalpy_j, expected_h, delta=.1)
        for initial, residue, taken, ni, mm in zip(self.mass, left.component_mass_kg,
                parcel.component_mass_kg, n, self.backend.molar_mass_kg):
            self.assertAlmostEqual(taken, ni*mm, delta=1e-12)
            self.assertAlmostEqual(residue+taken, initial, delta=1e-12)
        self.assertAlmostEqual(left.enthalpy_j+parcel.enthalpy_j, state.enthalpy_j,
                               delta=1e-8)
        recovered = self.provider.flash(left.component_mass_kg, self.p, left.enthalpy_j,
            (1490., 1510.), branch=self.branch(left.component_mass_kg),
            constraint='enthalpy_j', tolerance=2.)
        self.assertAlmostEqual(recovered.temperature_k, self.t, delta=.001)
        remaining_liquid = next(s for s in recovered.phases if s.key == 'liq')
        original_liquid = next(s for s in state.phases if s.key == 'liq')
        for a, b in zip(remaining_liquid.component_mass_kg, original_liquid.component_mass_kg):
            self.assertAlmostEqual(a, .6*b, delta=1e-7)
        self.assertEqual(state.component_mass_kg, self.mass)
        with self.assertRaises(FrozenInstanceError):
            state.enthalpy_j = 0.
        for fraction in (-.1, 1.1, True):
            with self.assertRaises(ValueError):
                self.provider.extract(state, fraction)

    def test_common_provider_receiver_h_and_entropy_inversion(self):
        donor = self.provider.equilibrate(self.mass, self.p, self.t)
        _, parcel = self.provider.extract(donor, .2)
        receiver_mass = (4., 10.)
        receiver = self.provider.equilibrate(receiver_mass, self.p, 1480.)
        target_h = receiver.enthalpy_j+parcel.enthalpy_j
        mixed_mass = tuple(a+b for a, b in zip(receiver_mass, parcel.component_mass_kg))
        mixed = self.provider.receive(receiver, parcel, (1450., 1550.),
            branch=self.branch(mixed_mass, (1450., 1550.)), tolerance_j=5.)
        self.assertGreater(mixed.temperature_k, receiver.temperature_k)
        self.assertLess(mixed.temperature_k, donor.temperature_k)
        self.assertAlmostEqual(mixed.enthalpy_j, target_h, delta=5.)
        independent_h = self.backend.expected_total_h(mixed.component_mass_kg,
                                                       self.p, mixed.temperature_k)
        self.assertAlmostEqual(independent_h, target_h, delta=5.)
        for a, b, c in zip(mixed.component_mass_kg, receiver_mass, parcel.component_mass_kg):
            self.assertAlmostEqual(a, b+c, delta=1e-12)
        recovered = self.provider.flash(self.mass, self.p, donor.entropy_j_k,
            (1490., 1510.), branch=self.branch(), constraint='entropy_j_k', tolerance=.002)
        self.assertAlmostEqual(recovered.temperature_k, self.t, delta=1e-6)

    def test_flash_refuses_wide_solid_to_liquid_bracket(self):
        bounds = (1201., 1799.)
        self.assertEqual([[x[0] for x in self.backend.phases(self.p, t, (.5, .5))]
                          for t in bounds], [['solid'], ['liq']])
        target = self.backend.expected_total_h(self.mass, self.p, self.t)
        # Deliberately overbroad declaration: the API must not trust its phase
        # assumption when a sampled endpoint already contradicts it.
        with self.assertRaisesRegex(ValueError, 'sampled phase identities'):
            self.provider.flash(self.mass, self.p, target, bounds,
                branch=self.branch(bounds=bounds), constraint='enthalpy_j', tolerance=1.)

    def test_flash_checks_interior_even_when_endpoint_phases_match(self):
        def interior_phase_change(point):
            if abs(point.temperature_k-self.t) <= 1.:
                return replace(point, phases=tuple(replace(s, key=s.key+'-other')
                                                   for s in point.phases))
            return point
        provider = m.Provider(BinaryIdeal(interior_phase_change), self.controls)
        a = provider.equilibrate(self.mass, self.p, 1490.)
        b = provider.equilibrate(self.mass, self.p, 1510.)
        self.assertEqual([s.key for s in a.phases], [s.key for s in b.phases])
        target = self.backend.expected_total_h(self.mass, self.p, self.t)
        with self.assertRaisesRegex(ValueError, 'sampled phase identities'):
            provider.flash(self.mass, self.p, target, (1490., 1510.),
                branch=self.branch(provider=provider), constraint='enthalpy_j', tolerance=1.)

    def test_flash_same_branch_subinterval_and_inventory_scaling_contract(self):
        target = self.backend.expected_total_h(self.mass, self.p, self.t)
        branch = self.branch()
        state = self.provider.flash(self.mass, self.p, target, (1495., 1505.),
            branch=branch, constraint='enthalpy_j', tolerance=1.)
        self.assertEqual(state.temperature_k, self.t)
        self.assertEqual(tuple(sorted(s.key for s in state.phases)), branch.phase_keys)
        self.assertAlmostEqual(state.enthalpy_j, target, delta=1.)
        # Extensive inputs are bound exactly: changing even only scale needs a
        # new explicit declaration, although equilibrium point reuse remains valid.
        with self.assertRaisesRegex(ValueError, 'outside declared thermal branch'):
            self.provider.flash(tuple(2*x for x in self.mass), self.p, 2*target,
                (1495., 1505.), branch=branch, constraint='enthalpy_j', tolerance=1.)

    def test_thermal_branch_admission_is_explicit_bound_and_not_inferred(self):
        branch = self.branch()
        self.assertEqual(self.backend.requests, [])  # declaration is not a proof by sampling
        with self.assertRaises(FrozenInstanceError):
            branch.support = 'changed'
        with self.assertRaises(TypeError):
            self.provider.flash(self.mass, self.p, 0., (1490., 1510.),
                                constraint='enthalpy_j', tolerance=1.)
        invalid = (None, replace(branch, provider_id='another-provider'),
                   replace(branch, controls=replace(self.controls, temperature_step_k=.2)),
                   replace(branch, component_ids=('b', 'a')),
                   replace(branch, component_mass_kg=(3., 5.)),
                   replace(branch, pressure_pa=self.p+1.),
                   replace(branch, temperature_bounds_k=(1495., 1505.)),
                   replace(branch, phase_keys=('liq', 'liq')), replace(branch, support=''))
        for wrong in invalid:
            with self.subTest(branch=wrong), self.assertRaises(ValueError):
                self.provider.flash(self.mass, self.p, 0., (1490., 1510.),
                    branch=wrong, constraint='enthalpy_j', tolerance=1.)
        self.assertEqual(self.backend.requests, [])

    def test_cancel_deadline_and_mid_solve_cancel_return_no_state(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(CancelledError):
            self.provider.equilibrate(self.mass, self.p, self.t, cancel=event)
        with self.assertRaises(TimeoutError):
            self.provider.equilibrate(self.mass, self.p, self.t,
                                      deadline=time.perf_counter()-1.)
        self.assertEqual(self.provider.calls, 0)
        event.clear()
        provider = m.Provider(BinaryIdeal(cancel_on_solve=event))
        with self.assertRaises(CancelledError):
            provider.equilibrate(self.mass, self.p, self.t, cancel=event)
        self.assertEqual(len(provider.cache), 0)

    def test_point_budget_exhaustion_and_unbracketed_target_refuse(self):
        provider = m.Provider(BinaryIdeal(), replace(m.Controls(), max_points=8))
        with self.assertRaisesRegex(TimeoutError, 'point budget exhausted'):
            provider.equilibrate(self.mass, self.p, self.t)
        self.assertEqual(provider.calls, 8)
        with self.assertRaisesRegex(ValueError, 'target not bracketed'):
            self.provider.flash(self.mass, self.p, 1e100, (1490., 1510.),
                                branch=self.branch(), constraint='enthalpy_j', tolerance=1.)

    def test_result_integrity_and_transfer_compatibility_refuse(self):
        transforms = (
            lambda r: replace(r, provider_id='another-provider'),
            lambda r: replace(r, bulk=(.51, .49)),
            lambda r: replace(r, gibbs_j_mol=r.gibbs_j_mol+10.),
            lambda r: replace(r, phases=(replace(r.phases[0], amounts=(.5, .5)),
                                          r.phases[1])),
        )
        for transform in transforms:
            with self.subTest(transform=transform), self.assertRaises(ValueError):
                m.Provider(BinaryIdeal(transform)).equilibrate(self.mass, self.p, self.t)
        state = self.provider.equilibrate(self.mass, self.p, self.t)
        _, parcel = self.provider.extract(state, .2)
        for bad in (replace(parcel, provider_id='another-provider'),
                    replace(parcel, pressure_pa=self.p+1.)):
            with self.subTest(parcel=bad), self.assertRaisesRegex(ValueError, 'matching provider'):
                self.provider.receive(state, bad, (1490., 1510.),
                                      branch=self.branch(), tolerance_j=5.)
        self.backend.identity = 'changed-provider-bytes'
        with self.assertRaisesRegex(ValueError, 'backend identity changed'):
            self.provider.equilibrate(self.mass, self.p, self.t)


if __name__ == '__main__':
    unittest.main()
