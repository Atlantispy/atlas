"""Independent W08 analytic parcel, history and conservative crop checks."""
from dataclasses import replace
from concurrent.futures import CancelledError
import math
from threading import Event
import unittest
from unittest import mock
import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.materials import MaterialState, MaterialCohort
from atlas_tectonics.mesh import ColumnGrid1D
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.shortening import (PreparedShortening, ShorteningInterval,
                                       boundary_flux_kg_s)


def fixture(cells=8, *, width=1000., context=None, budget=None, histories=None,
            edges=None, enthalpy=True):
    if edges is None: edges = np.linspace(0., 1000., cells+1)
    grid = ColumnGrid1D(edges, frame_id='synthetic-cartesian', budget=budget)
    n = grid.cells
    cohorts = (MaterialCohort('a', 'upper-crust', 'initial-A', -10.),
               MaterialCohort('b', 'lower-crust', 'initial-B', None))
    material = MaterialState(grid, cohorts, np.array([np.full(n, 10000.), np.full(n, 20000.)]),
                             time_s=0., epoch_id='synthetic-seconds', budget=budget)
    if histories is None:
        histories = (ShorteningInterval(1., math.log(.8), 0., 0., 'test-rate'),)
    return PreparedShortening(material, histories, density_kg_m3=[2700., 2850.],
        width_m=width, datum_id='initial-datum', source_id='test-source',
        specific_enthalpy_j_kg=(np.array([np.linspace(10., 20., n), np.linspace(-4., 4., n)]) if enthalpy else None),
        enthalpy_source=('synthetic-relative-enthalpy' if enthalpy else None),
        context=context, budget=budget)


class ShorteningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = ExecutionContext('reference')

    @classmethod
    def tearDownClass(cls):
        cls.context.close()

    def plan(self, **kwargs):
        return fixture(context=self.context, **kwargs)

    def project(self, plan, state, edges):
        return plan.project(state, ColumnGrid1D(edges, frame_id='synthetic-cartesian'),
                            exterior_ids=('left-retained', 'right-retained'), source_id='fixed-view')

    def test_frozen_A01_twenty_and_fifty_percent_shortening(self):
        for factor, expected in ((.8, 37500.), (.5, 60000.)):
            history = (ShorteningInterval(1., math.log(factor), 0., 0., 'A01'),)
            with self.plan(histories=history) as plan:
                result = plan.evaluate(1.)
                np.testing.assert_allclose(result.material.total_thickness(backend='reference'), expected, rtol=1e-14)
                self.assertAlmostEqual(result.material.grid.edges_m[-1], 1000.*factor)
                self.assertEqual(result.material.cohorts, plan.initial.material.cohorts)
                self.assertEqual(result.material.ages_s(), (11., None))
                view = self.project(plan, result, [-100., 1000.])
                np.testing.assert_allclose(np.sum(view.mass_kg, axis=1), [2.7e13, 5.7e13], rtol=1e-14)
                self.assertEqual(float(view.outside_mass_kg.sum()), 0.)

    def test_nonuniform_parcels_and_exact_history_partition(self):
        endpoints = [0., 3., 11., 100., 510., 1000.]
        results = []
        for count in (1, 2, 4):
            events = tuple(ShorteningInterval((i+1)/count, math.log(.5), 3., 27., 'same-law') for i in range(count))
            with self.plan(edges=endpoints, histories=events) as plan:
                r = plan.evaluate(1.)
                results.append(r.material)
                s = .5; b = 27.*(1-s)+3.*math.expm1(math.log(s))/math.log(s)
                np.testing.assert_allclose(r.material.grid.edges_m, s*np.array(endpoints)+b, rtol=1e-14)
        for r in results[1:]:
            np.testing.assert_allclose(r.grid.edges_m, results[0].grid.edges_m, rtol=1e-14)
            np.testing.assert_allclose(r.thickness_m, results[0].thickness_m, rtol=1e-14)

    def test_noncommuting_stop_restart_and_translation(self):
        first = ShorteningInterval(1., math.log(.5), 0., 0., 'compress')
        second = ShorteningInterval(2., 0., 100., 0., 'translate')
        third = ShorteningInterval(3., 0., 0., 0., 'stop')
        with self.plan(histories=(first, second, third)) as plan:
            np.testing.assert_allclose(plan.evaluate(2.).material.grid.edges_m,
                                       .5*plan.initial.material.grid.edges_m+100.)
            np.testing.assert_array_equal(plan.evaluate(2.).material.thickness_m,
                                          plan.evaluate(3.).material.thickness_m)
            self.assertEqual(plan.evaluate(3.).intervals, 3)
        with self.plan(histories=(replace(second, end_time_s=1.), replace(first, end_time_s=2.))) as plan:
            self.assertAlmostEqual(plan.evaluate(2.).material.grid.edges_m[0], 50.)

    def test_crop_matches_independent_scalar_intersections_and_heat(self):
        with self.plan(cells=16) as plan:
            state = plan.evaluate(.73)
            y = np.array([40., 90., 211., 390., 690.])
            view = self.project(plan, state, y)
            x = state.material.grid.edges_m
            h = state.material.thickness_m
            expected = np.zeros_like(view.volume_m3)
            for k in range(2):
                for j in range(len(y)-1):
                    expected[k, j] = math.fsum(max(0., min(x[i+1], y[j+1])-max(x[i], y[j]))*h[k, i]*1000.
                                               for i in range(len(x)-1))
            np.testing.assert_allclose(view.volume_m3, expected, rtol=1e-14)
            np.testing.assert_allclose(view.mass_kg, expected*np.array([2700., 2850.])[:, None], rtol=1e-14)
            for k in range(3):
                source = plan._inventories()[k]
                field = view._field(k); outside = view._exterior(k)
                for row in range(2):
                    scale = math.fsum(abs(float(v)) for v in source[row])
                    self.assertLessEqual(abs(math.fsum([*field[row], *outside[row], *(-source[row])])), 128*np.finfo(float).eps*scale)
            self.assertEqual(view.descriptor()['exterior_ids'], ['left-retained', 'right-retained'])

    def test_completely_disjoint_crop_and_source_never_lost(self):
        with self.plan() as plan:
            state = plan.evaluate(1.)
            empty = self.project(plan, state, [2000., 3000.])
            self.assertFalse(np.any(empty.volume_m3))
            self.assertGreater(empty.outside_mass_kg[:, 0].sum(), 0.)
            full = self.project(plan, state, [-1., 1001.])
            self.assertAlmostEqual(full.mass_kg.sum(), 8.4e13)
            self.assertFalse(np.any(full.outside_mass_kg))

    def test_A03_boundary_relative_flux_and_tangential_control(self):
        kw = dict(thickness_m=3., density_kg_m3=4., width_m=2.)
        for shift in (0., 11., -5.):
            self.assertEqual(boundary_flux_kg_s(**kw, material_normal_velocity_m_s=.5+shift,
                boundary_normal_velocity_m_s=.25+shift), 6.)
        self.assertEqual(boundary_flux_kg_s(**kw, material_normal_velocity_m_s=0.,
            boundary_normal_velocity_m_s=0.), 0.)

    def test_prepared_view_reuse_immutable_and_provenance_bound(self):
        with self.plan() as plan:
            state = plan.evaluate(1.)
            a = self.project(plan, state, [-10., 1010.])
            b = self.project(plan, state, [-10., 1010.])
            self.assertIs(a, b)
            with self.assertRaises(ValueError): a.mass_kg[0, 0] = 0.
            x = a.mass_kg; x.shape = (2,)
            self.assertEqual(a.mass_kg.shape, (2, 1))
            record = a.descriptor(); record['source'] = 'changed'
            self.assertNotEqual(a.descriptor()['source'], 'changed')
            with self.assertRaises(AttributeError): plan.width_m = 2.

    def test_missing_enthalpy_stays_explicitly_unknown(self):
        with self.plan(enthalpy=False) as plan:
            view = self.project(plan, plan.evaluate(1.), [-10., 1010.])
            self.assertFalse(view.descriptor()['enthalpy_present'])
            self.assertIsNone(view.descriptor()['enthalpy_source'])

    def test_input_history_geometry_and_foreign_state_refusals(self):
        with self.assertRaises(TectonicsError): ShorteningInterval(1., .1, 0., 0., 'no-extension')
        with self.assertRaises(TectonicsError): self.plan(histories=(ShorteningInterval(0., 0., 0., 0., 'zero'),))
        with self.assertRaises(TectonicsError): self.plan(histories=tuple(ShorteningInterval(i+1., 0., 0., 0., 'x') for i in range(257)))
        with self.plan() as plan, self.plan(width=5.) as other:
            for time in (-1., 2., float('nan'), True):
                with self.assertRaises(TectonicsError): plan.evaluate(time)
            with self.assertRaises(TectonicsError): self.project(plan, other.evaluate(1.), [-1., 1001.])
            with self.assertRaises(TectonicsError): self.project(plan, replace(plan.evaluate(1.), stretch=.9), [-1., 1001.])
            wrong = ColumnGrid1D([0., 1000.], frame_id='different')
            with self.assertRaises(TectonicsError): plan.project(plan.initial, wrong, exterior_ids=('l','r'), source_id='x')

    def test_cancellation_budget_release_and_closed_owner(self):
        with self.assertRaises(MemoryLimitError): self.plan(budget=WorkBudget(1024))
        budget = WorkBudget(16*1024**2)
        plan = self.plan(budget=budget)
        stop = Event(); stop.set()
        with self.assertRaises(CancelledError): plan.evaluate(1., cancel=stop)
        self.project(plan, plan.evaluate(1.), [-10., 1010.])
        self.assertGreater(budget.reserved_bytes, 0)
        plan.close()
        self.assertEqual(budget.reserved_bytes, 0)
        with self.assertRaises(TectonicsError): plan.evaluate(1.)

    def test_loaded_code_mutation_cannot_hit_view_cache(self):
        import atlas_tectonics.shortening as module
        with self.plan() as plan:
            state = plan.evaluate(1.)
            self.project(plan, state, [-10., 1010.])
            with mock.patch.object(module, '_segment', lambda *args: (1., 0.)):
                with self.assertRaises(TectonicsError): self.project(plan, state, [-10., 1010.])

    def test_unresolvable_translation_refuses_and_cache_counts_metadata(self):
        history = (ShorteningInterval(1., 0., 1e-20, 0., 'tiny-motion'),)
        with self.plan(histories=history) as plan:
            with self.assertRaisesRegex(TectonicsError, 'unresolvable'): plan.evaluate(1.)
        with self.plan() as plan:
            view = self.project(plan, plan.evaluate(1.), [-10., 1010.])
            expected = sum(map(len, (view.material._payload, view.material.grid._edges,
                view.material._transition_payload, view._fields, view._outside, view._record)))
            self.assertEqual(view.nbytes, expected)


if __name__ == '__main__': unittest.main()
